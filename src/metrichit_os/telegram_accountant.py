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
from calendar import monthcalendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Protocol
from urllib.request import Request, urlopen

EXPENSE_CATEGORIES = ("Бытовые", "Сервисы", "Продвижение", "Выплаты")
PAYMENT_METHODS = ("СБП", "Оплата по счёту", "USDT", "BTC")
PAYMENT_METHOD_SLUGS = {"sbp": "СБП", "invoice": "Оплата по счёту", "usdt": "USDT", "btc": "BTC"}
MONTH_NAMES = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
COLLABORATOR_USERNAME = "ametric_hit"
ACCESS_DENIED_MESSAGE = "Доступ к бухгалтерии закрыт."


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
    """Transaction storage with an optional two-user shared ledger."""

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
            connection.execute(
                """CREATE TABLE IF NOT EXISTS accountant_access (
                    role TEXT PRIMARY KEY CHECK(role IN ('owner', 'collaborator')),
                    chat_id INTEGER UNIQUE,
                    expected_username TEXT NOT NULL DEFAULT '',
                    bound_username TEXT NOT NULL DEFAULT '',
                    bound_at TEXT
                )"""
            )
            connection.execute(
                "INSERT OR IGNORE INTO accountant_access(role, expected_username) "
                "VALUES ('collaborator', ?)",
                (COLLABORATOR_USERNAME,),
            )
            owner = connection.execute(
                "SELECT chat_id FROM accountant_access WHERE role = 'owner'"
            ).fetchone()
            if owner is None:
                legacy_chat_ids = connection.execute(
                    "SELECT DISTINCT chat_id FROM accountant_transactions ORDER BY chat_id"
                ).fetchall()
                if len(legacy_chat_ids) == 1:
                    connection.execute(
                        "INSERT INTO accountant_access(role, chat_id, bound_at) VALUES ('owner', ?, ?)",
                        (int(legacy_chat_ids[0]["chat_id"]), self._now().astimezone(UTC).isoformat()),
                    )

    def shared_ledger_enabled(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM accountant_access WHERE role = 'owner' AND chat_id IS NOT NULL"
            ).fetchone()
        return row is not None

    def authorize_private_user(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        *,
        allow_collaborator_binding: bool = False,
    ) -> bool:
        """Authorize a private-chat user and atomically bind the invited username once."""
        if not self.shared_ledger_enabled():
            return True
        if chat_id != user_id:
            return False
        normalized_username = (username or "").strip().lstrip("@").casefold()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM accountant_access WHERE chat_id = ?", (user_id,)
            ).fetchone()
            if existing is not None:
                return True
            if not allow_collaborator_binding or normalized_username != COLLABORATOR_USERNAME:
                return False
            changed = connection.execute(
                "UPDATE accountant_access SET chat_id = ?, bound_username = ?, bound_at = ? "
                "WHERE role = 'collaborator' AND chat_id IS NULL AND expected_username = ?",
                (
                    user_id,
                    normalized_username,
                    self._now().astimezone(UTC).isoformat(),
                    COLLABORATOR_USERNAME,
                ),
            ).rowcount
            return changed == 1

    def is_authorized(self, chat_id: int) -> bool:
        if not self.shared_ledger_enabled():
            return True
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM accountant_access WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return row is not None

    def _scope_filter(self, chat_id: int) -> tuple[str, tuple[object, ...]]:
        if not self.shared_ledger_enabled():
            return "chat_id = ?", (chat_id,)
        if not self.is_authorized(chat_id):
            raise PermissionError("Telegram user is not allowed to access the shared ledger")
        return "1 = 1", ()

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
        self._scope_filter(chat_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO accountant_transactions(chat_id, kind, amount_cents, label, occurred_at, details, category) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, kind, cents, cleaned_label, occurred_at, cleaned_details, cleaned_category),
            )
        return Transaction(chat_id, kind, cents, cleaned_label, occurred_at, cleaned_details)

    def balance_cents(self, chat_id: int) -> int:
        where, parameters = self._scope_filter(chat_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(CASE kind WHEN 'income' THEN amount_cents ELSE -amount_cents END), 0) "
                f"AS total FROM accountant_transactions WHERE {where}",
                parameters,
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

    def details_breakdown(
        self, chat_id: int, kind: str, start: str | None = None, end: str | None = None
    ) -> list[tuple[str, int]]:
        """Aggregate operations by their optional details value."""
        if kind not in {"income", "expense"}:
            raise ValueError("kind must be income or expense")
        where, parameters = self._date_filter(chat_id, start, end)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT CASE WHEN TRIM(details) = '' THEN 'Не указан' ELSE details END AS value, "
                "SUM(amount_cents) AS total FROM accountant_transactions "
                f"WHERE {where} AND kind = ? GROUP BY value ORDER BY total DESC, value ASC",
                (*parameters, kind),
            ).fetchall()
        return [(str(row["value"]), int(row["total"])) for row in rows]

    def latest(self, chat_id: int, kind: str, limit: int = 5) -> list[sqlite3.Row]:
        """Return the most recent operations visible in the caller's ledger."""
        if kind not in {"income", "expense"}:
            raise ValueError("kind must be income or expense")
        where, parameters = self._scope_filter(chat_id)
        with self._connect() as connection:
            return connection.execute(
                "SELECT amount_cents, label, occurred_at, details, category "
                f"FROM accountant_transactions WHERE {where} AND kind = ? "
                "ORDER BY occurred_at DESC, id DESC LIMIT ?",
                (*parameters, kind, limit),
            ).fetchall()

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

    def _date_filter(self, chat_id: int, start: str | None, end: str | None) -> tuple[str, tuple[object, ...]]:
        scope, scope_parameters = self._scope_filter(chat_id)
        conditions = [scope]
        parameters: list[object] = list(scope_parameters)
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
        sleep: Callable[[float], None] | None = None,
        retry_delay: float = 1.0,
    ):
        actual_token = token if token is not None else os.environ.get("TELEGRAM_ACCOUNTANT_BOT_TOKEN")
        self.transport = transport or UrllibTelegramTransport(actual_token or "")
        self.commands = AccountantCommands(store)
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep or time.sleep
        self._retry_delay = max(0.0, min(retry_delay, 30.0))
        self.offset: int | None = None
        self._flows: dict[int, dict[str, object]] = {}
        self._report_states: dict[int, dict[str, object]] = {}
        self._section_states: dict[int, dict[str, object]] = {}

    @staticmethod
    def reply_keyboard() -> dict[str, object]:
        return {
            "keyboard": [[{"text": "Доход"}, {"text": "Расход"}, {"text": "Отчёты"}]],
            "resize_keyboard": True,
        }

    def calendar_keyboard(self, target: str, shown: date | None = None) -> dict[str, object]:
        """Build a compact inline calendar; all callback payloads stay below Telegram's limit."""
        shown = shown or self._now().astimezone(UTC).date().replace(day=1)
        shown = shown.replace(day=1)
        previous = (shown - timedelta(days=1)).replace(day=1)
        following = (shown.replace(day=28) + timedelta(days=4)).replace(day=1)
        rows: list[list[dict[str, str]]] = [
            [{"text": f"{MONTH_NAMES[shown.month]} {shown.year}", "callback_data": f"cal:{target}:noop"}],
            [{"text": value, "callback_data": f"cal:{target}:noop"} for value in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")],
        ]
        for week in monthcalendar(shown.year, shown.month):
            rows.append([
                {
                    "text": str(day_number) if day_number else " ",
                    "callback_data": (
                        f"cal:{target}:d:{shown.year:04d}-{shown.month:02d}-{day_number:02d}"
                        if day_number
                        else f"cal:{target}:noop"
                    ),
                }
                for day_number in week
            ])
        rows.extend(
            [
                [
                    {"text": "‹", "callback_data": f"cal:{target}:n:{previous.year:04d}-{previous.month:02d}"},
                    {"text": "Сегодня", "callback_data": f"cal:{target}:today"},
                    {"text": "›", "callback_data": f"cal:{target}:n:{following.year:04d}-{following.month:02d}"},
                ],
                [{"text": "Назад", "callback_data": f"cal:{target}:back"}],
            ]
        )
        return {"inline_keyboard": rows}

    @staticmethod
    def payment_method_keyboard() -> dict[str, object]:
        return {
            "inline_keyboard": [
                [{"text": "СБП", "callback_data": "pay:sbp"}, {"text": "Оплата по счёту", "callback_data": "pay:invoice"}],
                [{"text": "USDT", "callback_data": "pay:usdt"}, {"text": "BTC", "callback_data": "pay:btc"}],
                [{"text": "Назад", "callback_data": "pay:back"}],
            ]
        }

    @staticmethod
    def expense_category_keyboard() -> dict[str, object]:
        return {
            "keyboard": [
                *[[{"text": category}] for category in EXPENSE_CATEGORIES],
                [{"text": "Назад"}, {"text": "Отменить и в меню"}],
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }

    @staticmethod
    def wizard_keyboard() -> dict[str, object]:
        return {
            "keyboard": [[{"text": "Назад"}, {"text": "Отменить и в меню"}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }

    @staticmethod
    def section_keyboard(kind: str, child: bool = False) -> dict[str, object]:
        if kind == "income":
            rows = [
                [{"text": "Добавить доход", "callback_data": "section:income:add"}],
                [{"text": "Последние поступления", "callback_data": "section:income:latest"}],
                [{"text": "По клиентам", "callback_data": "section:income:labels"}],
                [{"text": "По способу оплаты", "callback_data": "section:income:details"}],
            ]
        elif kind == "expense":
            rows = [
                [{"text": "Добавить расход", "callback_data": "section:expense:add"}],
                [{"text": "Последние расходы", "callback_data": "section:expense:latest"}],
                [{"text": "По категориям", "callback_data": "section:expense:categories"}],
                [{"text": "По получателям", "callback_data": "section:expense:labels"}],
            ]
        else:
            raise ValueError("unknown section kind")
        if child:
            rows = [[{"text": "Назад", "callback_data": f"section:{kind}:root"}]]
        rows.append([{"text": "Назад в меню", "callback_data": f"section:{kind}:back"}])
        return {"inline_keyboard": rows}

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

    def _month_dates(self) -> tuple[str, str]:
        today = self._now().astimezone(UTC).date()
        return today.replace(day=1).isoformat(), today.isoformat()

    def _render_section(self, chat_id: int, kind: str, view: str = "root") -> str:
        start, end = self._month_dates()
        income, expense = self.commands.store.totals(chat_id, start, end)
        title = "Доходы" if kind == "income" else "Расходы"
        if view == "root":
            if kind == "income":
                clients = len(self.commands.store.breakdown(chat_id, "income", start, end))
                return f"{title} · Этот месяц\n\nВсего: {format_money(income)}\nКлиентов: {clients}"
            categories = self.commands.store.expense_category_totals(chat_id, start, end)
            largest_category, largest_amount = max(categories, key=lambda item: item[1])
            largest = largest_category if largest_amount else "нет расходов"
            return f"{title} · Этот месяц\n\nВсего: {format_money(expense)}\nКрупнее всего: {largest}"
        if view == "latest":
            rows = self.commands.store.latest(chat_id, kind)
            lines = []
            for row in rows:
                date = str(row["occurred_at"])[:10]
                extra = str(row["details"] if kind == "income" else row["category"]).strip()
                suffix = f" · {extra}" if extra else ""
                lines.append(f"{date} · {format_money(int(row['amount_cents']))} · {row['label']}{suffix}")
            return f"{title} · Последние 5\n\n" + ("\n".join(lines) if lines else "Операций пока нет.")
        if view == "labels":
            values = self.commands.store.breakdown(chat_id, kind)
            heading = "По клиентам" if kind == "income" else "По получателям"
        elif view == "details" and kind == "income":
            values = self.commands.store.details_breakdown(chat_id, "income")
            heading = "По способу оплаты"
        elif view == "categories" and kind == "expense":
            values = self.commands.store.expense_category_totals(chat_id)
            heading = "По категориям"
        else:
            raise ValueError("unknown section view")
        lines = [f"{label} — {format_money(amount)}" for label, amount in values]
        return f"{title} · {heading}\n\n" + ("\n".join(lines) if lines else "Операций пока нет.")

    def _show_section(self, chat_id: int, kind: str) -> tuple[str, dict[str, object]]:
        return self._render_section(chat_id, kind), self.section_keyboard(kind)

    def _return_section_to_menu(self, chat_id: int, message_id: int) -> None:
        self._section_states.pop(chat_id, None)
        self._flows.pop(chat_id, None)
        self._report_states.pop(chat_id, None)
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
            {"chat_id": chat_id, "text": "Главное меню.", "reply_markup": self.reply_keyboard()},
        )

    def _handle_section_callback(self, chat_id: int, message_id: int, data: str) -> bool:
        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "section" or parts[1] not in {"income", "expense"}:
            return False
        kind, action = parts[1], parts[2]
        allowed = {"root", "add", "latest", "labels", "details", "categories", "back"}
        if action not in allowed:
            return True
        if (kind == "income" and action == "categories") or (kind == "expense" and action == "details"):
            return True
        state = self._section_states.get(chat_id)
        recovered = state is None or state.get("message_id") != message_id or state.get("kind") != kind
        if recovered:
            state = {"message_id": message_id, "kind": kind, "view": "root"}
            self._section_states[chat_id] = state
        if action == "back":
            self._return_section_to_menu(chat_id, message_id)
            return True
        if action == "add":
            first_step = "label" if kind == "income" else "category"
            self._flows[chat_id] = {
                "kind": kind,
                "step": first_step,
                "origin_kind": kind,
                "origin_message_id": message_id,
            }
            prompt = "Введите ник клиента." if kind == "income" else "Выберите категорию расхода."
            keyboard = self.wizard_keyboard() if kind == "income" else self.expense_category_keyboard()
            self.transport.call(
                "sendMessage",
                {"chat_id": chat_id, "text": prompt, "reply_markup": keyboard},
            )
            return True
        view = action
        if state.get("view") == view and not (recovered and view == "root"):
            return True
        state["view"] = view
        self.transport.call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": self._render_section(chat_id, kind, view),
                "reply_markup": self.section_keyboard(kind, child=view != "root"),
            },
        )
        return True

    def _calendar_prompt(self, target: str, *, invalid_end: bool = False) -> str:
        if target == "f":
            return "Выберите дату операции."
        if target == "rs":
            return "Выберите начало периода."
        if invalid_end:
            return "Конечная дата не может быть раньше начальной. Выберите другую дату."
        return "Выберите конец периода."

    def _edit_calendar(self, chat_id: int, message_id: int, target: str, shown: date) -> None:
        self.transport.call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": self._calendar_prompt(target),
                "reply_markup": self.calendar_keyboard(target, shown),
            },
        )

    def _refresh_section_after_save(self, chat_id: int, completed: dict[str, object]) -> None:
        kind = str(completed["kind"])
        origin_message_id = completed.get("origin_message_id")
        if isinstance(origin_message_id, int):
            try:
                self.transport.call(
                    "editMessageText",
                    {
                        "chat_id": chat_id,
                        "message_id": origin_message_id,
                        "text": self._render_section(chat_id, kind),
                        "reply_markup": self.section_keyboard(kind),
                    },
                )
                self._section_states[chat_id] = {
                    "message_id": origin_message_id,
                    "kind": kind,
                    "view": "root",
                }
                return
            except Exception:
                # The original section message can be too old or already changed.  Confirmation
                # has already been delivered, so fall back to a fresh internal section menu.
                pass
        result = self.transport.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": self._render_section(chat_id, kind),
                "reply_markup": self.section_keyboard(kind),
            },
        )
        sent = result.get("result")
        if isinstance(sent, dict) and isinstance(sent.get("message_id"), int):
            self._section_states[chat_id] = {
                "message_id": sent["message_id"],
                "kind": kind,
                "view": "root",
            }

    def _send_saved_confirmation(self, chat_id: int, text: str, completed: dict[str, object]) -> None:
        payload = {"chat_id": chat_id, "text": text, "reply_markup": self.reply_keyboard()}
        try:
            self.transport.call("sendMessage", payload)
        except Exception:
            # A retry cannot duplicate the transaction: the form is removed before any API call.
            self.transport.call("sendMessage", payload)
        self._refresh_section_after_save(chat_id, completed)

    def _handle_payment_callback(self, chat_id: int, message_id: int, data: str) -> bool:
        action = data.removeprefix("pay:")
        flow = self._flows.get(chat_id)
        if flow is None or flow.get("kind") != "income" or flow.get("step") != "details":
            return True
        if action == "back":
            flow["step"] = "date"
            self._edit_calendar(chat_id, message_id, "f", date.fromisoformat(str(flow["date"])).replace(day=1))
            return True
        method = PAYMENT_METHOD_SLUGS.get(action)
        if method is None:
            return True
        flow["details"] = method
        confirmation, completed = self._save_flow(chat_id, flow)
        self._send_saved_confirmation(chat_id, confirmation, completed)
        try:
            self.transport.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"Способ пополнения: {method}.",
                    "reply_markup": {"inline_keyboard": []},
                },
            )
        except Exception:
            pass
        return True

    def _handle_calendar_callback(self, chat_id: int, message_id: int, data: str) -> bool:
        parts = data.split(":")
        if len(parts) < 3 or parts[0] != "cal" or parts[1] not in {"f", "rs", "re"}:
            return True
        target, action = parts[1], parts[2]
        if action == "noop":
            return True
        if action == "n" and len(parts) == 4:
            try:
                shown = datetime.strptime(parts[3], "%Y-%m").date()
            except ValueError:
                return True
            self._edit_calendar(chat_id, message_id, target, shown)
            return True
        if action == "back":
            if target == "f":
                flow = self._flows.get(chat_id)
                if flow is None or flow.get("step") != "date":
                    return True
                flow["step"] = "amount"
                self.transport.call(
                    "editMessageText",
                    {"chat_id": chat_id, "message_id": message_id, "text": "Вернулись к сумме.", "reply_markup": {"inline_keyboard": []}},
                )
                self.transport.call(
                    "sendMessage",
                    {"chat_id": chat_id, "text": "Введите сумму.", "reply_markup": self.wizard_keyboard()},
                )
                return True
            state = self._report_states.get(chat_id)
            if state is None or not state.get("awaiting_custom"):
                return True
            if target == "re":
                state.pop("custom_start", None)
                state["custom_stage"] = "start"
                self._edit_calendar(chat_id, message_id, "rs", self._now().astimezone(UTC).date().replace(day=1))
            else:
                state.update({"awaiting_custom": False})
                state.pop("custom_stage", None)
                state.pop("custom_start", None)
                self.transport.call(
                    "editMessageText",
                    {"chat_id": chat_id, "message_id": message_id, "text": "Выбор периода отменён.", "reply_markup": {"inline_keyboard": []}},
                )
            return True
        if action == "today":
            selected = self._now().astimezone(UTC).date()
        elif action == "d" and len(parts) == 4:
            try:
                selected = date.fromisoformat(parts[3])
            except ValueError:
                return True
        else:
            return True
        selected_text = selected.isoformat()
        if target == "f":
            flow = self._flows.get(chat_id)
            if flow is None or flow.get("step") != "date":
                return True
            flow["date"] = selected_text
            self.transport.call(
                "editMessageText",
                {"chat_id": chat_id, "message_id": message_id, "text": f"Дата: {selected_text}.", "reply_markup": {"inline_keyboard": []}},
            )
            if flow["kind"] == "income":
                flow["step"] = "details"
                self.transport.call(
                    "sendMessage",
                    {"chat_id": chat_id, "text": "Выберите способ пополнения.", "reply_markup": self.payment_method_keyboard()},
                )
            else:
                confirmation, completed = self._save_flow(chat_id, flow)
                self._send_saved_confirmation(chat_id, confirmation, completed)
            return True
        state = self._report_states.get(chat_id)
        if state is None or not state.get("awaiting_custom"):
            return True
        if target == "rs":
            state["custom_start"] = selected_text
            state["custom_stage"] = "end"
            self.transport.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"Начало: {selected_text}. Теперь выберите конец периода.",
                    "reply_markup": self.calendar_keyboard("re", selected.replace(day=1)),
                },
            )
            return True
        start = state.get("custom_start")
        if not isinstance(start, str):
            return True
        if selected_text < start:
            self.transport.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": self._calendar_prompt("re", invalid_end=True),
                    "reply_markup": self.calendar_keyboard("re", selected.replace(day=1)),
                },
            )
            return True
        state.update({"start": start, "end": selected_text, "period": f"{start} — {selected_text}", "awaiting_custom": False})
        state.pop("custom_stage", None)
        state.pop("custom_start", None)
        self.transport.call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": state["message_id"], "text": self._render_dashboard(chat_id, state), "reply_markup": self.report_keyboard()},
        )
        self.transport.call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": f"Период выбран: {start} — {selected_text}.", "reply_markup": {"inline_keyboard": []}},
        )
        return True

    def _handle_callback(self, callback: dict[str, object]) -> bool:
        callback_id = callback.get("id")
        if not isinstance(callback_id, str):
            return False
        message = callback.get("message")
        data = callback.get("data")
        if not isinstance(message, dict) or not isinstance(data, str):
            self.transport.call("answerCallbackQuery", {"callback_query_id": callback_id})
            return True
        chat = message.get("chat")
        sender = callback.get("from")
        message_id = message.get("message_id")
        if not isinstance(chat, dict) or not isinstance(chat.get("id"), int) or not isinstance(message_id, int):
            self.transport.call("answerCallbackQuery", {"callback_query_id": callback_id})
            return True
        chat_id = chat["id"]
        if not self._is_allowed_private_user(chat, sender):
            self.transport.call(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": ACCESS_DENIED_MESSAGE, "show_alert": True},
            )
            return True
        self.transport.call("answerCallbackQuery", {"callback_query_id": callback_id})
        if data.startswith("section:"):
            return self._handle_section_callback(chat_id, message_id, data)
        if data.startswith("cal:"):
            return self._handle_calendar_callback(chat_id, message_id, data)
        if data.startswith("pay:"):
            return self._handle_payment_callback(chat_id, message_id, data)
        action = data.removeprefix("report:") if data.startswith("report:") else ""
        if action not in {"summary", "income", "expense", "today", "week", "month", "custom", "back"}:
            return True
        state = self._report_states.get(chat_id)
        if state is None or state.get("message_id") != message_id:
            state = self._new_report_state(message_id)
            self._report_states[chat_id] = state
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
        previous_view = (state.get("tab"), state.get("start"), state.get("end"), state.get("period"))
        if action in {"summary", "income", "expense"}:
            state["awaiting_custom"] = False
            state["tab"] = action
        elif action in {"today", "week", "month"}:
            state["awaiting_custom"] = False
            state["start"], state["end"], state["period"] = self._report_period(action)
        elif action == "custom":
            state["awaiting_custom"] = True
            state["custom_stage"] = "start"
            self.transport.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": "Выберите начало периода.",
                    "reply_markup": self.calendar_keyboard("rs"),
                },
            )
            return True
        else:
            return True
        current_view = (state.get("tab"), state.get("start"), state.get("end"), state.get("period"))
        if current_view == previous_view:
            return True
        self.transport.call(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": self._render_dashboard(chat_id, state), "reply_markup": self.report_keyboard()},
        )
        return True

    def _is_allowed_private_user(
        self,
        chat: dict[str, object],
        sender: object,
        *,
        allow_collaborator_binding: bool = False,
    ) -> bool:
        if not self.commands.store.shared_ledger_enabled():
            return True
        if chat.get("type") != "private" or not isinstance(sender, dict):
            return False
        chat_id = chat.get("id")
        user_id = sender.get("id")
        username = sender.get("username")
        if not isinstance(chat_id, int) or not isinstance(user_id, int):
            return False
        return self.commands.store.authorize_private_user(
            chat_id,
            user_id,
            username if isinstance(username, str) else None,
            allow_collaborator_binding=allow_collaborator_binding,
        )

    def _handle_custom_period(self, chat_id: int, text: str) -> bool:
        state = self._report_states.get(chat_id)
        if state is None or not state.get("awaiting_custom"):
            return False
        self.transport.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": "Выберите дату кнопкой календаря.",
                "reply_markup": self.calendar_keyboard("re" if state.get("custom_stage") == "end" else "rs"),
            },
        )
        return True

    def _handle_message(self, chat_id: int, text: str) -> tuple[str, dict[str, object]]:
        if text == "Доход":
            self._flows.pop(chat_id, None)
            return self._show_section(chat_id, "income")
        if text == "Расход":
            self._flows.pop(chat_id, None)
            return self._show_section(chat_id, "expense")
        if text == "Отчёты":
            return self._show_dashboard(chat_id)
        if text.startswith("/"):
            self._flows.pop(chat_id, None)
            return self.commands.handle(chat_id, text), self.reply_keyboard()
        flow = self._flows.get(chat_id)
        if flow is None:
            return self.commands.handle(chat_id, text), self.reply_keyboard()
        reply = self._wizard_back(chat_id, flow) if text == "Назад" else self._continue_flow(chat_id, text, flow)
        keyboard = (
            self.calendar_keyboard("f")
            if self._flows.get(chat_id) is flow and flow.get("step") == "date"
            else self.expense_category_keyboard()
            if self._flows.get(chat_id) is flow and flow.get("step") == "category"
            else self.payment_method_keyboard()
            if self._flows.get(chat_id) is flow and flow.get("step") == "details"
            else self.wizard_keyboard()
            if self._flows.get(chat_id) is flow
            else self.reply_keyboard()
        )
        return reply, keyboard

    def _return_to_main_menu(self, chat_id: int) -> None:
        """Cancel an unfinished form or custom report period for one chat."""
        self._flows.pop(chat_id, None)
        self._report_states.pop(chat_id, None)
        self._section_states.pop(chat_id, None)
        self.transport.call(
            "sendMessage",
            {"chat_id": chat_id, "text": "Главное меню.", "reply_markup": self.reply_keyboard()},
        )

    def _wizard_back(self, chat_id: int, flow: dict[str, object]) -> str:
        kind = str(flow["kind"])
        step = str(flow["step"])
        first = "label" if kind == "income" else "category"
        if step == first:
            self._flows.pop(chat_id, None)
            return "Вы вернулись в раздел доходов." if kind == "income" else "Вы вернулись в раздел расходов."
        previous = {
            "label": "category",
            "amount": "label",
            "date": "amount",
            "details": "date",
        }[step]
        flow["step"] = previous
        prompts = {
            "category": "Выберите категорию расхода.",
            "label": "Введите ник клиента." if kind == "income" else "Введите, куда ушли деньги.",
            "amount": "Введите сумму.",
            "date": "Выберите дату.",
        }
        return prompts[previous]

    def _continue_flow(self, chat_id: int, text: str, flow: dict[str, object]) -> str:
        value = text.strip()
        kind = str(flow["kind"])
        step = str(flow["step"])
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
            return "Выберите дату кнопкой календаря."
        if step == "details":
            return "Выберите способ пополнения кнопкой."
        raise RuntimeError("unknown accountant flow step")

    def _save_flow(self, chat_id: int, flow: dict[str, object]) -> tuple[str, dict[str, object]]:
        item = self.commands.store.add(
            chat_id,
            str(flow["kind"]),
            str(flow["amount"]),
            str(flow["label"]),
            occurred_date=str(flow["date"]),
            details=str(flow.get("details", "")),
            category=str(flow.get("category", "")),
        )
        completed = {
            "kind": str(flow["kind"]),
            "origin_message_id": flow.get("origin_message_id"),
        }
        self._flows.pop(chat_id, None)
        if item.kind == "income":
            return (
                "Запись внесена.\n"
                f"Доход: {format_money(item.amount_cents)}\n"
                f"Клиент: {item.label}\n"
                f"Дата: {flow['date']}\n"
                f"Способ пополнения: {item.details}",
                completed,
            )
        return (
            "Запись внесена.\n"
            f"Расход: {format_money(item.amount_cents)}\n"
            f"Куда: {item.label}\n"
            f"Категория: {flow.get('category', '')}\n"
            f"Дата: {flow['date']}",
            completed,
        )

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
            sender = message.get("from")
            command = text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower()
            if not self._is_allowed_private_user(
                chat,
                sender,
                allow_collaborator_binding=command == "/start",
            ):
                self.transport.call(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": ACCESS_DENIED_MESSAGE,
                        "reply_markup": {"remove_keyboard": True},
                    },
                )
                handled += 1
                continue
            if text in {"Назад в меню", "Отменить и в меню"}:
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
            elif text in {"Доход", "Расход"}:
                sent = result.get("result")
                if isinstance(sent, dict) and isinstance(sent.get("message_id"), int):
                    kind = "income" if text == "Доход" else "expense"
                    self._section_states[chat_id] = {
                        "message_id": sent["message_id"],
                        "kind": kind,
                        "view": "root",
                    }
            handled += 1
        return handled

    def run_forever(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception:
                self._sleep(self._retry_delay)
                continue
            self._sleep(0.2)
