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
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Protocol
from urllib.request import Request, urlopen

EXPENSE_CATEGORIES = ("Бытовые", "Сервисы", "Продвижение", "Выплаты")


class TelegramTransport(Protocol):
    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True)
class Transaction:
    chat_id: int
    kind: str
    amount_cents: int
    label: str
    occurred_at: str
    details: str = ""


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
                    occurred_at TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT ''
                )"""
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(accountant_transactions)")
            }
            if "details" not in columns:
                connection.execute(
                    "ALTER TABLE accountant_transactions ADD COLUMN details TEXT NOT NULL DEFAULT ''"
                )
            if "category" not in columns:
                connection.execute(
                    "ALTER TABLE accountant_transactions ADD COLUMN category TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_accountant_chat_date "
                "ON accountant_transactions(chat_id, occurred_at)"
            )

    def add(
        self,
        chat_id: int,
        kind: str,
        amount: str,
        label: str,
        occurred_date: str | None = None,
        details: str = "",
        category: str = "",
    ) -> Transaction:
        if kind not in {"income", "expense"}:
            raise ValueError("kind must be income or expense")
        cleaned_label = label.strip()
        if not cleaned_label:
            raise ValueError("source or category is required")
        cents = parse_amount(amount)
        if occurred_date:
            validate_date(occurred_date)
            occurred_at = f"{occurred_date}T00:00:00Z"
        else:
            occurred_at = self._now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        cleaned_details = details.strip()
        cleaned_category = category.strip()
        if kind == "expense" and cleaned_category and cleaned_category not in EXPENSE_CATEGORIES:
            raise ValueError("unknown expense category")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO accountant_transactions(chat_id, kind, amount_cents, label, occurred_at, details, category) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, kind, cents, cleaned_label, occurred_at, cleaned_details, cleaned_category),
            )
        return Transaction(chat_id, kind, cents, cleaned_label, occurred_at, cleaned_details)

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

    def expense_category_totals(
        self, chat_id: int, start: str | None = None, end: str | None = None
    ) -> list[tuple[str, int]]:
        where, parameters = self._date_filter(chat_id, start, end)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT category, SUM(amount_cents) AS total FROM accountant_transactions "
                f"WHERE {where} AND kind = 'expense' GROUP BY category",
                parameters,
            ).fetchall()
        totals = {str(row["category"]): int(row["total"]) for row in rows}
        return [(category, totals.get(category, 0)) for category in EXPENSE_CATEGORIES]

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
                    category_lines = "\n".join(
                        f"{category}: {format_money(amount)}"
                        for category, amount in self.store.expense_category_totals(chat_id, start, end)
                    )
                    return (
                        f"Отчёт{period}:\nДоходы: {format_money(income)}\n"
                        f"Расходы: {format_money(expense)}\nРасходы по категориям:\n"
                        f"{category_lines}\nИтог: {format_money(income - expense)}"
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

    def __init__(
        self,
        store: AccountantStore,
        token: str | None = None,
        transport: TelegramTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        actual_token = token if token is not None else os.environ.get("TELEGRAM_ACCOUNTANT_BOT_TOKEN")
        self.transport = transport or UrllibTelegramTransport(actual_token or "")
        self.commands = AccountantCommands(store)
        self._now = now or (lambda: datetime.now(UTC))
        self.offset: int | None = None
        self._flows: dict[int, dict[str, str]] = {}
        self._report_states: dict[int, dict[str, object]] = {}

    @staticmethod
    def reply_keyboard() -> dict[str, object]:
        return {
            "keyboard": [
                [{"text": "Доход"}, {"text": "Расход"}, {"text": "Отчёты"}],
                [{"text": "Назад в меню"}],
            ],
            "resize_keyboard": True,
        }

    @staticmethod
    def date_keyboard() -> dict[str, object]:
        return {
            "keyboard": [
                [{"text": "Сегодня"}, {"text": "Вчера"}],
                [{"text": "Другая дата"}],
                [{"text": "Назад в меню"}],
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }

    @staticmethod
    def expense_category_keyboard() -> dict[str, object]:
        return {
            "keyboard": [
                *[[{"text": category}] for category in EXPENSE_CATEGORIES],
                [{"text": "Назад в меню"}],
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }

    @staticmethod
    def custom_period_keyboard() -> dict[str, object]:
        return {
            "keyboard": [[{"text": "Назад в меню"}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }

    @staticmethod
    def report_keyboard() -> dict[str, object]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Сводка", "callback_data": "report:summary"},
                    {"text": "Доходы", "callback_data": "report:income"},
                    {"text": "Расходы", "callback_data": "report:expense"},
                ],
                [
                    {"text": "Сегодня", "callback_data": "report:today"},
                    {"text": "Неделя", "callback_data": "report:week"},
                    {"text": "Месяц", "callback_data": "report:month"},
                ],
                [{"text": "Выбрать период", "callback_data": "report:custom"}],
                [{"text": "Назад в меню", "callback_data": "report:back"}],
            ]
        }

    def _new_report_state(self, message_id: int) -> dict[str, object]:
        return {"message_id": message_id, "tab": "summary", "start": None, "end": None, "period": "За всё время"}

    def _report_period(self, key: str) -> tuple[str | None, str | None, str]:
        today = self._now().astimezone(UTC).date()
        if key == "today":
            value = today.isoformat()
            return value, value, "Сегодня"
        if key == "week":
            start = today - timedelta(days=today.weekday())
            return start.isoformat(), today.isoformat(), "Эта неделя"
        if key == "month":
            start = today.replace(day=1)
            return start.isoformat(), today.isoformat(), "Этот месяц"
        raise ValueError("unknown report period")

    def _render_dashboard(self, chat_id: int, state: dict[str, object]) -> str:
        start = state["start"] if isinstance(state["start"], str) else None
        end = state["end"] if isinstance(state["end"], str) else None
        period = str(state["period"])
        tab = str(state["tab"])
        if tab == "income":
            values = self.commands.store.breakdown(chat_id, "income", start, end)
            lines = [f"{label} — {format_money(amount)}" for label, amount in values]
            return f"Доходы · {period}\n\n" + ("\n".join(lines) if lines else "Нет поступлений.")
        if tab == "expense":
            lines = [
                f"{category} — {format_money(amount)}"
                for category, amount in self.commands.store.expense_category_totals(chat_id, start, end)
            ]
            return f"Расходы · {period}\n\n" + "\n".join(lines)
        income, expense = self.commands.store.totals(chat_id, start, end)
        categories = self.commands.store.expense_category_totals(chat_id, start, end)
        largest_category, largest_amount = max(categories, key=lambda item: item[1])
        largest = f"{largest_category} — {format_money(largest_amount)}" if largest_amount else "нет расходов"
        return (
            f"Финансы · {period}\n\n"
            f"Баланс  {format_money(self.commands.store.balance_cents(chat_id))}\n"
            f"Доходы  {format_money(income)}\n"
            f"Расходы  {format_money(expense)}\n\n"
            f"Крупнее всего: {largest}"
        )

    def _show_dashboard(self, chat_id: int) -> tuple[str, dict[str, object]]:
        state = self._new_report_state(0)
        return self._render_dashboard(chat_id, state), self.report_keyboard()

    def _handle_callback(self, callback: dict[str, object]) -> bool:
        callback_id = callback.get("id")
        if not isinstance(callback_id, str):
            return False
        self.transport.call("answerCallbackQuery", {"callback_query_id": callback_id})
        message = callback.get("message")
        data = callback.get("data")
        if not isinstance(message, dict) or not isinstance(data, str):
            return True
        chat = message.get("chat")
        message_id = message.get("message_id")
        if not isinstance(chat, dict) or not isinstance(chat.get("id"), int) or not isinstance(message_id, int):
            return True
        chat_id = chat["id"]
        state = self._report_states.get(chat_id)
        if state is None or state.get("message_id") != message_id:
            return True
        action = data.removeprefix("report:") if data.startswith("report:") else ""
        if action == "back":
            self._report_states.pop(chat_id, None)
            self._flows.pop(chat_id, None)
            self.transport.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "Возвращаю в главное меню.",
                    "reply_markup": {"inline_keyboard": []},
                },
            )
            self.transport.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": "Главное меню.",
                    "reply_markup": self.reply_keyboard(),
                },
            )
            return True
        if action in {"summary", "income", "expense"}:
            state["awaiting_custom"] = False
            state["tab"] = action
        elif action in {"today", "week", "month"}:
            state["awaiting_custom"] = False
            state["start"], state["end"], state["period"] = self._report_period(action)
        elif action == "custom":
            state["awaiting_custom"] = True
            self.transport.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": "Введите две даты: YYYY-MM-DD YYYY-MM-DD.",
                    "reply_markup": self.custom_period_keyboard(),
                },
            )
            return True
        else:
            return True
        self.transport.call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": self._render_dashboard(chat_id, state), "reply_markup": self.report_keyboard()},
        )
        return True

    def _handle_custom_period(self, chat_id: int, text: str) -> bool:
        state = self._report_states.get(chat_id)
        if state is None or not state.get("awaiting_custom"):
            return False
        try:
            start, end = parse_period(text.strip().split())
        except ValueError:
            self.transport.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": "Введите две даты: YYYY-MM-DD YYYY-MM-DD.",
                    "reply_markup": self.custom_period_keyboard(),
                },
            )
            return True
        state.update({"start": start, "end": end, "period": f"{start} — {end}", "awaiting_custom": False})
        self.transport.call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": state["message_id"], "text": self._render_dashboard(chat_id, state), "reply_markup": self.report_keyboard()},
        )
        return True

    def _handle_message(self, chat_id: int, text: str) -> tuple[str, dict[str, object]]:
        if text == "Доход":
            self._flows[chat_id] = {"kind": "income", "step": "label"}
            return "Введите ник клиента.", self.reply_keyboard()
        if text == "Расход":
            self._flows[chat_id] = {"kind": "expense", "step": "category"}
            return "Выберите категорию расхода.", self.expense_category_keyboard()
        if text == "Отчёты":
            return self._show_dashboard(chat_id)
        if text.startswith("/"):
            self._flows.pop(chat_id, None)
            return self.commands.handle(chat_id, text), self.reply_keyboard()
        flow = self._flows.get(chat_id)
        if flow is None:
            return self.commands.handle(chat_id, text), self.reply_keyboard()
        reply = self._continue_flow(chat_id, text, flow)
        keyboard = (
            self.date_keyboard()
            if self._flows.get(chat_id) is flow and flow.get("step") in {"date", "manual_date"}
            else self.expense_category_keyboard()
            if self._flows.get(chat_id) is flow and flow.get("step") == "category"
            else self.reply_keyboard()
        )
        return reply, keyboard

    def _return_to_main_menu(self, chat_id: int) -> None:
        """Cancel an unfinished form or custom report period for one chat."""
        self._flows.pop(chat_id, None)
        self._report_states.pop(chat_id, None)
        self.transport.call(
            "sendMessage",
            {"chat_id": chat_id, "text": "Главное меню.", "reply_markup": self.reply_keyboard()},
        )

    def _continue_flow(self, chat_id: int, text: str, flow: dict[str, str]) -> str:
        value = text.strip()
        kind = flow["kind"]
        step = flow["step"]
        if step == "category":
            if value not in EXPENSE_CATEGORIES:
                return "Выберите категорию кнопкой."
            flow["category"] = value
            flow["step"] = "label"
            return "Введите, куда ушли деньги."
        if step == "label":
            if not value:
                return "Поле не может быть пустым. Введите значение ещё раз."
            flow["label"] = value
            flow["step"] = "amount"
            return "Введите сумму."
        if step == "amount":
            try:
                parse_amount(value)
            except ValueError:
                return "Введите корректную сумму больше нуля."
            flow["amount"] = value
            flow["step"] = "date"
            return "Выберите дату."
        if step == "date":
            if value == "Сегодня":
                flow["date"] = self._now().astimezone(UTC).date().isoformat()
                return self._continue_after_date(chat_id, flow)
            if value == "Вчера":
                flow["date"] = (self._now().astimezone(UTC).date() - timedelta(days=1)).isoformat()
                return self._continue_after_date(chat_id, flow)
            if value == "Другая дата":
                flow["step"] = "manual_date"
                return "Введите дату в формате YYYY-MM-DD."
            return "Выберите дату кнопкой или нажмите «Другая дата»."
        if step == "manual_date":
            try:
                validate_date(value)
            except ValueError:
                return "Введите дату в формате YYYY-MM-DD."
            flow["date"] = value
            return self._continue_after_date(chat_id, flow)
        if step == "details":
            if not value:
                return "Поле не может быть пустым. Введите вид пополнения."
            flow["details"] = value
            return self._save_flow(chat_id, flow)
        raise RuntimeError("unknown accountant flow step")

    def _continue_after_date(self, chat_id: int, flow: dict[str, str]) -> str:
        if flow["kind"] == "income":
            flow["step"] = "details"
            return "Введите вид пополнения."
        return self._save_flow(chat_id, flow)

    def _save_flow(self, chat_id: int, flow: dict[str, str]) -> str:
        item = self.commands.store.add(
            chat_id,
            flow["kind"],
            flow["amount"],
            flow["label"],
            occurred_date=flow["date"],
            details=flow.get("details", ""),
            category=flow.get("category", ""),
        )
        self._flows.pop(chat_id, None)
        action = "Доход добавлен" if item.kind == "income" else "Расход добавлен"
        suffix = f" ({item.details})" if item.details else ""
        return f"{action}: {format_money(item.amount_cents)} — {item.label}{suffix}, дата {flow['date']}."

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
            callback = update.get("callback_query")
            if isinstance(callback, dict):
                if self._handle_callback(callback):
                    handled += 1
                continue
            message = update.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("text"), str):
                continue
            chat = message.get("chat")
            if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
                continue
            chat_id = chat["id"]
            text = message["text"]
            if text == "Назад в меню":
                self._return_to_main_menu(chat_id)
                handled += 1
                continue
            if self._handle_custom_period(chat_id, text):
                handled += 1
                continue
            reply, reply_markup = self._handle_message(chat_id, text)
            result = self.transport.call(
                "sendMessage",
                {"chat_id": chat_id, "text": reply, "reply_markup": reply_markup},
            )
            if text == "Отчёты":
                sent = result.get("result")
                if isinstance(sent, dict) and isinstance(sent.get("message_id"), int):
                    self._report_states[chat_id] = self._new_report_state(sent["message_id"])
            handled += 1
        return handled

    def run_forever(self) -> None:
        while True:
            self.poll_once()
            time.sleep(0.2)
