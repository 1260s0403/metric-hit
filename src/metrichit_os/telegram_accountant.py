"""Small, dependency-free Telegram accountant MVP.

The module deliberately keeps its own SQLite file.  It can be used as a
library by an application process, while :class:`TelegramAccountantBot`
provides the minimal Telegram Bot API polling adapter.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Protocol
from urllib.request import Request, urlopen


class TelegramTransport(Protocol):
    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True)
class Transaction:
    chat_id: int
    kind: str
    amount_cents: int
    label: str
    occurred_at: str


class AccountantStore:
    """Transaction storage scoped by Telegram ``chat_id``."""

    def __init__(self, database_path: str | Path, now: Callable[[], datetime] | None = None):
        self.database_path = str(database_path)
        self._now = now or (lambda: datetime.now(UTC))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS accountant_transactions (
                    id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    label TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_accountant_chat_date "
                "ON accountant_transactions(chat_id, occurred_at)"
            )

    def add(self, chat_id: int, kind: str, amount: str, label: str) -> Transaction:
        if kind not in {"income", "expense"}:
            raise ValueError("kind must be income or expense")
        cleaned_label = label.strip()
        if not cleaned_label:
            raise ValueError("source or category is required")
        cents = parse_amount(amount)
        occurred_at = self._now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO accountant_transactions(chat_id, kind, amount_cents, label, occurred_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, kind, cents, cleaned_label, occurred_at),
            )
        return Transaction(chat_id, kind, cents, cleaned_label, occurred_at)

    def balance_cents(self, chat_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(CASE kind WHEN 'income' THEN amount_cents ELSE -amount_cents END), 0) "
                "AS total FROM accountant_transactions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["total"])

    def totals(self, chat_id: int, start: str | None = None, end: str | None = None) -> tuple[int, int]:
        where, parameters = self._date_filter(chat_id, start, end)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(CASE WHEN kind = 'income' THEN amount_cents END), 0) AS income, "
                "COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount_cents END), 0) AS expense "
                f"FROM accountant_transactions WHERE {where}", parameters
            ).fetchone()
        return int(row["income"]), int(row["expense"])

    def breakdown(self, chat_id: int, kind: str, start: str | None = None, end: str | None = None) -> list[tuple[str, int]]:
        if kind not in {"income", "expense"}:
            raise ValueError("kind must be income or expense")
        where, parameters = self._date_filter(chat_id, start, end)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT label, SUM(amount_cents) AS total FROM accountant_transactions "
                f"WHERE {where} AND kind = ? GROUP BY label ORDER BY total DESC, label ASC",
                (*parameters, kind),
            ).fetchall()
        return [(str(row["label"]), int(row["total"])) for row in rows]

    @staticmethod
    def _date_filter(chat_id: int, start: str | None, end: str | None) -> tuple[str, tuple[object, ...]]:
        conditions = ["chat_id = ?"]
        parameters: list[object] = [chat_id]
        if start:
            validate_date(start)
            conditions.append("occurred_at >= ?")
            parameters.append(f"{start}T00:00:00Z")
        if end:
            validate_date(end)
            conditions.append("occurred_at < ?")
            parameters.append(f"{end}T23:59:59Z")
        return " AND ".join(conditions), tuple(parameters)


def parse_amount(value: str) -> int:
    """Convert a positive ruble amount to integer kopecks without floats."""
    try:
        amount = Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("amount must be a number") from exc
    cents = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if not amount.is_finite() or cents <= 0:
        raise ValueError("amount must be greater than zero")
    return int(cents)


def validate_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute = abs(cents)
    return f"{sign}{absolute // 100:,}.{absolute % 100:02d} ₽".replace(",", " ")


class AccountantCommands:
    HELP = (
        "Команды:\n"
        "/income <сумма> <источник> — добавить доход\n"
        "/expense <сумма> <категория> — добавить расход\n"
        "/balance — текущий остаток\n"
        "/report [YYYY-MM-DD YYYY-MM-DD] — доходы и расходы за период\n"
        "/sources [YYYY-MM-DD YYYY-MM-DD] — источники доходов\n"
        "/destinations [YYYY-MM-DD YYYY-MM-DD] — направления расходов"
    )

    def __init__(self, store: AccountantStore):
        self.store = store

    def handle(self, chat_id: int, text: str) -> str:
        parts = text.strip().split()
        if not parts:
            return self.HELP
        command = parts[0].split("@", 1)[0].lower()
        try:
            if command in {"/start", "/help"}:
                return self.HELP
            if command in {"/income", "/expense"}:
                if len(parts) < 3:
                    return "Укажите сумму и источник/категорию.\n" + self.HELP
                kind = "income" if command == "/income" else "expense"
                item = self.store.add(chat_id, kind, parts[1], " ".join(parts[2:]))
                action = "Доход добавлен" if kind == "income" else "Расход добавлен"
                return f"{action}: {format_money(item.amount_cents)} — {item.label}."
            if command == "/balance":
                return f"Остаток: {format_money(self.store.balance_cents(chat_id))}."
            if command in {"/report", "/sources", "/destinations"}:
                start, end = parse_period(parts[1:])
                period = period_title(start, end)
                if command == "/report":
                    income, expense = self.store.totals(chat_id, start, end)
                    return (
                        f"Отчёт{period}:\nДоходы: {format_money(income)}\n"
                        f"Расходы: {format_money(expense)}\nИтог: {format_money(income - expense)}"
                    )
                kind = "income" if command == "/sources" else "expense"
                heading = "Источники доходов" if kind == "income" else "Направления расходов"
                values = self.store.breakdown(chat_id, kind, start, end)
                lines = [f"{label}: {format_money(amount)}" for label, amount in values]
                return f"{heading}{period}:\n" + ("\n".join(lines) if lines else "Нет операций.")
        except ValueError as exc:
            return f"Ошибка: {exc}."
        return self.HELP


def parse_period(parts: list[str]) -> tuple[str | None, str | None]:
    if not parts:
        return None, None
    if len(parts) != 2:
        raise ValueError("укажите две даты: YYYY-MM-DD YYYY-MM-DD")
    start, end = parts
    validate_date(start)
    validate_date(end)
    if start > end:
        raise ValueError("первая дата должна быть не позже второй")
    return start, end


def period_title(start: str | None, end: str | None) -> str:
    return f" за {start} — {end}" if start and end else " за всё время"


class UrllibTelegramTransport:
    """Minimal HTTPS client for the official Telegram Bot API."""

    def __init__(self, token: str):
        if not token:
            raise ValueError("TELEGRAM_ACCOUNTANT_BOT_TOKEN is required")
        self._base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            self._base_url + method,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=35) as response:  # noqa: S310 - fixed Telegram API URL
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed: {result}")
        return result


class TelegramAccountantBot:
    """Polling adapter.  Constructing it does not contact Telegram."""

    def __init__(self, store: AccountantStore, token: str | None = None, transport: TelegramTransport | None = None):
        actual_token = token if token is not None else os.environ.get("TELEGRAM_ACCOUNTANT_BOT_TOKEN")
        self.transport = transport or UrllibTelegramTransport(actual_token or "")
        self.commands = AccountantCommands(store)
        self.offset: int | None = None

    def poll_once(self, timeout: int = 25) -> int:
        payload: dict[str, object] = {"timeout": timeout}
        if self.offset is not None:
            payload["offset"] = self.offset
        result = self.transport.call("getUpdates", payload)
        updates = result.get("result", [])
        if not isinstance(updates, list):
            raise RuntimeError("Telegram returned invalid updates")
        handled = 0
        for update in updates:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self.offset = update_id + 1
            message = update.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("text"), str):
                continue
            chat = message.get("chat")
            if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
                continue
            reply = self.commands.handle(chat["id"], message["text"])
            self.transport.call("sendMessage", {"chat_id": chat["id"], "text": reply})
            handled += 1
        return handled

    def run_forever(self) -> None:
        while True:
            self.poll_once()
            time.sleep(0.2)
