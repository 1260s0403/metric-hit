from datetime import UTC, datetime

import pytest

from metrichit_os.telegram_accountant import (
    AccountantCommands,
    AccountantStore,
    TelegramAccountantBot,
    format_money,
    parse_amount,
)


def store(tmp_path):
    return AccountantStore(tmp_path / "accountant.sqlite", now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC))


def test_amounts_are_precise_and_positive():
    assert parse_amount("12.345") == 1235
    assert parse_amount("1,20") == 120
    with pytest.raises(ValueError):
        parse_amount("0")
    with pytest.raises(ValueError):
        parse_amount("money")


def test_income_expense_and_balance_are_isolated_by_chat(tmp_path):
    commands = AccountantCommands(store(tmp_path))
    assert "Доход добавлен: 1 200.00 ₽ — Клиент A." == commands.handle(10, "/income 1200 Клиент A")
    commands.handle(10, "/expense 199.99 Реклама")
    commands.handle(20, "/income 50 Другое")
    assert commands.handle(10, "/balance") == "Остаток: 1 000.01 ₽."
    assert commands.handle(20, "/balance") == "Остаток: 50.00 ₽."


def test_summary_and_breakdowns_support_period(tmp_path):
    commands = AccountantCommands(store(tmp_path))
    commands.handle(10, "/income 1000 Продажи")
    commands.handle(10, "/income 200 Продажи")
    commands.handle(10, "/income 50 Партнёр")
    commands.handle(10, "/expense 300 Реклама")
    commands.handle(10, "/expense 20 Сервисы")
    assert commands.handle(10, "/report 2026-09-02 2026-09-02") == (
        "Отчёт за 2026-09-02 — 2026-09-02:\nДоходы: 1 250.00 ₽\nРасходы: 320.00 ₽\n"
        "Расходы по категориям:\nБытовые: 0.00 ₽\nСервисы: 0.00 ₽\nПродвижение: 0.00 ₽\nВыплаты: 0.00 ₽\nИтог: 930.00 ₽"
    )
    assert commands.handle(10, "/sources") == "Источники доходов за всё время:\nПродажи: 1 200.00 ₽\nПартнёр: 50.00 ₽"
    assert commands.handle(10, "/destinations") == "Направления расходов за всё время:\nРеклама: 300.00 ₽\nСервисы: 20.00 ₽"


def test_invalid_commands_are_explained(tmp_path):
    commands = AccountantCommands(store(tmp_path))
    assert "Укажите сумму" in commands.handle(1, "/income 10")
    assert commands.handle(1, "/report 2026-09-03 2026-09-02") == "Ошибка: первая дата должна быть не позже второй."
    assert "Команды:" in commands.handle(1, "/unknown")


def test_no_operations_breakdown_and_money_format(tmp_path):
    commands = AccountantCommands(store(tmp_path))
    assert commands.handle(1, "/sources") == "Источники доходов за всё время:\nНет операций."
    assert format_money(-5) == "-0.05 ₽"


class FakeTransport:
    def __init__(self, updates):
        self.updates = updates
        self.calls = []

    def call(self, method, payload):
        self.calls.append((method, payload))
        return {"ok": True, "result": self.updates if method == "getUpdates" else True}


def test_polling_handles_text_and_skips_non_text_updates(tmp_path):
    transport = FakeTransport([
        {"update_id": 4, "message": {"chat": {"id": 9}, "text": "/income 7 Test"}},
        {"update_id": 5, "message": {"chat": {"id": 9}, "photo": []}},
    ])
    bot = TelegramAccountantBot(store(tmp_path), transport=transport)
    assert bot.poll_once(timeout=1) == 1
    assert transport.calls[0] == ("getUpdates", {"timeout": 1})
    assert transport.calls[1] == (
        "sendMessage",
        {
            "chat_id": 9,
            "text": "Доход добавлен: 7.00 ₽ — Test.",
            "reply_markup": TelegramAccountantBot.reply_keyboard(),
        },
    )
    assert bot.offset == 6


def test_bot_requires_token_without_injected_transport(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_ACCOUNTANT_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM_ACCOUNTANT_BOT_TOKEN"):
        TelegramAccountantBot(store(tmp_path))


def test_income_button_flow_saves_client_date_and_top_up_type(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 9}, "text": "Доход"}},
        {"update_id": 2, "message": {"chat": {"id": 9}, "text": "@client"}},
        {"update_id": 3, "message": {"chat": {"id": 9}, "text": "1250.50"}},
        {"update_id": 4, "message": {"chat": {"id": 9}, "text": "Другая дата"}},
        {"update_id": 5, "message": {"chat": {"id": 9}, "text": "2026-08-31"}},
        {"update_id": 6, "message": {"chat": {"id": 9}, "text": "Перевод"}},
        {"update_id": 7, "message": {"chat": {"id": 9}, "text": "Отчёты"}},
    ])
    accounting_store = store(tmp_path)
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 7
    assert transport.calls[-2][1]["text"] == "Доход добавлен: 1 250.50 ₽ — @client (Перевод), дата 2026-08-31."
    assert transport.calls[-1][1] == {
        "chat_id": 9,
        "text": "Отчёт за всё время:\nДоходы: 1 250.50 ₽\nРасходы: 0.00 ₽\nРасходы по категориям:\nБытовые: 0.00 ₽\nСервисы: 0.00 ₽\nПродвижение: 0.00 ₽\nВыплаты: 0.00 ₽\nИтог: 1 250.50 ₽",
        "reply_markup": TelegramAccountantBot.reply_keyboard(),
    }
    assert accounting_store.breakdown(9, "income", "2026-08-31", "2026-08-31") == [("@client", 125050)]
    with accounting_store._connect() as connection:
        assert connection.execute("SELECT details FROM accountant_transactions").fetchone()["details"] == "Перевод"


def test_expense_flow_is_isolated_between_chats(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 1}, "text": "Расход"}},
        {"update_id": 2, "message": {"chat": {"id": 2}, "text": "Расход"}},
        {"update_id": 3, "message": {"chat": {"id": 1}, "text": "Продвижение"}},
        {"update_id": 4, "message": {"chat": {"id": 2}, "text": "Сервисы"}},
        {"update_id": 5, "message": {"chat": {"id": 1}, "text": "Реклама"}},
        {"update_id": 6, "message": {"chat": {"id": 2}, "text": "Хостинг"}},
        {"update_id": 7, "message": {"chat": {"id": 1}, "text": "300"}},
        {"update_id": 8, "message": {"chat": {"id": 2}, "text": "50"}},
        {"update_id": 9, "message": {"chat": {"id": 1}, "text": "Сегодня"}},
        {"update_id": 10, "message": {"chat": {"id": 2}, "text": "Вчера"}},
    ])
    accounting_store = store(tmp_path)
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 10
    assert accounting_store.breakdown(1, "expense") == [("Реклама", 30000)]
    assert accounting_store.breakdown(2, "expense") == [("Хостинг", 5000)]
    assert accounting_store.expense_category_totals(1) == [("Бытовые", 0), ("Сервисы", 0), ("Продвижение", 30000), ("Выплаты", 0)]


def test_date_buttons_save_current_or_previous_date_and_restore_main_keyboard(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 1}, "text": "Доход"}},
        {"update_id": 2, "message": {"chat": {"id": 1}, "text": "@client"}},
        {"update_id": 3, "message": {"chat": {"id": 1}, "text": "100"}},
        {"update_id": 4, "message": {"chat": {"id": 1}, "text": "Сегодня"}},
        {"update_id": 5, "message": {"chat": {"id": 1}, "text": "Перевод"}},
        {"update_id": 6, "message": {"chat": {"id": 2}, "text": "Расход"}},
        {"update_id": 7, "message": {"chat": {"id": 2}, "text": "Продвижение"}},
        {"update_id": 8, "message": {"chat": {"id": 2}, "text": "Реклама"}},
        {"update_id": 9, "message": {"chat": {"id": 2}, "text": "25"}},
        {"update_id": 10, "message": {"chat": {"id": 2}, "text": "Вчера"}},
    ])
    accounting_store = store(tmp_path)
    bot = TelegramAccountantBot(
        accounting_store,
        transport=transport,
        now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC),
    )
    assert bot.poll_once(timeout=1) == 10
    assert transport.calls[3][1]["reply_markup"] == TelegramAccountantBot.date_keyboard()
    assert transport.calls[4][1]["reply_markup"] == TelegramAccountantBot.reply_keyboard()
    assert transport.calls[-1][1]["reply_markup"] == TelegramAccountantBot.reply_keyboard()
    assert accounting_store.breakdown(1, "income", "2026-09-02", "2026-09-02") == [("@client", 10000)]
    assert accounting_store.breakdown(2, "expense", "2026-09-01", "2026-09-01") == [("Реклама", 2500)]
