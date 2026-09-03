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
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return {"ok": True, "result": updates}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 100 + sum(call[0] == "sendMessage" for call in self.calls)}}
        return {"ok": True, "result": True}


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
    assert transport.calls[-1][1]["text"] == (
        "Финансы · За всё время\n\nБаланс  1 250.50 ₽\nДоходы  1 250.50 ₽\n"
        "Расходы  0.00 ₽\n\nКрупнее всего: нет расходов"
    )
    assert transport.calls[-1][1]["reply_markup"] == TelegramAccountantBot.report_keyboard()
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


def test_report_dashboard_uses_inline_keyboard_and_edits_the_same_message(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(9, "income", "1000", "@client", "2026-09-02")
    accounting_store.add(9, "expense", "200", "Реклама", "2026-09-02", category="Продвижение")
    transport = FakeTransport([{"update_id": 1, "message": {"chat": {"id": 9}, "text": "Отчёты"}}])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 1
    dashboard = transport.calls[-1][1]
    assert dashboard["reply_markup"] == TelegramAccountantBot.report_keyboard()
    dashboard_id = bot._report_states[9]["message_id"]

    transport.updates = [
        {"update_id": 2, "callback_query": {"id": "q-income", "data": "report:income", "message": {"message_id": dashboard_id, "chat": {"id": 9}}}},
        {"update_id": 3, "callback_query": {"id": "q-month", "data": "report:month", "message": {"message_id": dashboard_id, "chat": {"id": 9}}}},
    ]
    assert bot.poll_once(timeout=1) == 2
    assert [call[0] for call in transport.calls[-4:]] == [
        "answerCallbackQuery", "editMessageText", "answerCallbackQuery", "editMessageText"
    ]
    edited = transport.calls[-1][1]
    assert edited["message_id"] == dashboard_id
    assert edited["reply_markup"] == TelegramAccountantBot.report_keyboard()
    assert "Доходы · Этот месяц" in edited["text"]


def test_expense_dashboard_includes_all_categories_and_custom_period_replaces_dashboard(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(5, "expense", "20", "Обед", "2026-08-30", category="Бытовые")
    accounting_store.add(5, "expense", "30", "Реклама", "2026-09-02", category="Продвижение")
    transport = FakeTransport([{"update_id": 1, "message": {"chat": {"id": 5}, "text": "Отчёты"}}])
    bot = TelegramAccountantBot(accounting_store, transport=transport, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC))
    bot.poll_once(timeout=1)
    dashboard_id = bot._report_states[5]["message_id"]
    transport.updates = [
        {"update_id": 2, "callback_query": {"id": "q-expense", "data": "report:expense", "message": {"message_id": dashboard_id, "chat": {"id": 5}}}},
        {"update_id": 3, "callback_query": {"id": "q-custom", "data": "report:custom", "message": {"message_id": dashboard_id, "chat": {"id": 5}}}},
    ]
    bot.poll_once(timeout=1)
    expense_edit = next(call[1] for call in transport.calls if call[0] == "editMessageText")
    assert expense_edit["text"] == (
        "Расходы · За всё время\n\nБытовые — 20.00 ₽\nСервисы — 0.00 ₽\n"
        "Продвижение — 30.00 ₽\nВыплаты — 0.00 ₽"
    )
    assert transport.calls[-1] == (
        "sendMessage",
        {
            "chat_id": 5,
            "text": "Введите две даты: YYYY-MM-DD YYYY-MM-DD.",
            "reply_markup": TelegramAccountantBot.custom_period_keyboard(),
        },
    )
    transport.updates = [{"update_id": 4, "message": {"chat": {"id": 5}, "text": "2026-09-01 2026-09-02"}}]
    assert bot.poll_once(timeout=1) == 1
    custom_edit = transport.calls[-1][1]
    assert transport.calls[-1][0] == "editMessageText"
    assert custom_edit["message_id"] == dashboard_id
    assert "Расходы · 2026-09-01 — 2026-09-02" in custom_edit["text"]
    assert "Продвижение — 30.00 ₽" in custom_edit["text"]
    assert "Бытовые — 0.00 ₽" in custom_edit["text"]


def test_malformed_or_unknown_callbacks_are_acknowledged_without_editing(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "callback_query": {"id": "q-unknown", "data": "wrong", "message": {"message_id": 1, "chat": {"id": 5}}}},
        {"update_id": 2, "callback_query": {"id": "q-malformed", "data": "report:summary"}},
    ])
    bot = TelegramAccountantBot(store(tmp_path), transport=transport)
    assert bot.poll_once(timeout=1) == 2
    assert [call[0] for call in transport.calls] == ["getUpdates", "answerCallbackQuery", "answerCallbackQuery"]


def test_unknown_report_callback_keeps_custom_period_state(tmp_path):
    transport = FakeTransport([])
    bot = TelegramAccountantBot(store(tmp_path), transport=transport)
    bot._report_states[5] = {"message_id": 10, "awaiting_custom": True}
    transport.updates = [
        {
            "update_id": 1,
            "callback_query": {
                "id": "q-unknown-report",
                "data": "report:unknown",
                "message": {"message_id": 10, "chat": {"id": 5}},
            },
        }
    ]
    assert bot.poll_once(timeout=1) == 1
    assert bot._report_states[5]["awaiting_custom"] is True
    assert [method for method, _ in transport.calls] == ["getUpdates", "answerCallbackQuery"]


def test_report_tabs_and_periods_edit_the_original_dashboard(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(9, "income", "100", "Сегодня", "2026-09-02")
    accounting_store.add(9, "income", "50", "Ранее", "2026-08-30")
    accounting_store.add(9, "expense", "20", "Реклама", "2026-09-02", category="Продвижение")
    transport = FakeTransport([{"update_id": 1, "message": {"chat": {"id": 9}, "text": "Отчёты"}}])
    bot = TelegramAccountantBot(
        accounting_store, transport=transport, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )
    bot.poll_once(timeout=1)
    dashboard_id = bot._report_states[9]["message_id"]
    actions = ["summary", "income", "expense", "today", "week", "month"]
    transport.updates = [
        {
            "update_id": index + 2,
            "callback_query": {
                "id": f"q-{action}",
                "data": f"report:{action}",
                "message": {"message_id": dashboard_id, "chat": {"id": 9}},
            },
        }
        for index, action in enumerate(actions)
    ]
    assert bot.poll_once(timeout=1) == len(actions)
    edits = [payload for method, payload in transport.calls if method == "editMessageText"]
    assert len(edits) == len(actions)
    assert all(edit["chat_id"] == 9 and edit["message_id"] == dashboard_id for edit in edits)
    assert "Финансы · За всё время" in edits[0]["text"]
    assert "Доходы · За всё время" in edits[1]["text"]
    assert "Расходы · За всё время" in edits[2]["text"]
    assert "Расходы · Сегодня" in edits[3]["text"]
    assert "Расходы · Эта неделя" in edits[4]["text"]
    assert "Расходы · Этот месяц" in edits[5]["text"]
    assert [method for method, _ in transport.calls[-12:]][::2] == ["answerCallbackQuery"] * len(actions)


def test_report_back_removes_inline_dashboard_and_restores_main_keyboard(tmp_path):
    transport = FakeTransport([{"update_id": 1, "message": {"chat": {"id": 7}, "text": "Отчёты"}}])
    bot = TelegramAccountantBot(store(tmp_path), transport=transport)
    bot.poll_once(timeout=1)
    dashboard_id = bot._report_states[7]["message_id"]
    bot._flows[7] = {"kind": "income", "step": "amount"}
    transport.updates = [
        {
            "update_id": 2,
            "callback_query": {
                "id": "q-back",
                "data": "report:back",
                "message": {"message_id": dashboard_id, "chat": {"id": 7}},
            },
        }
    ]
    assert bot.poll_once(timeout=1) == 1
    assert 7 not in bot._report_states and 7 not in bot._flows
    assert transport.calls[-3:] == [
        ("answerCallbackQuery", {"callback_query_id": "q-back"}),
        (
            "editMessageText",
            {
                "chat_id": 7,
                "message_id": dashboard_id,
                "text": "Возвращаю в главное меню.",
                "reply_markup": {"inline_keyboard": []},
            },
        ),
        ("sendMessage", {"chat_id": 7, "text": "Главное меню.", "reply_markup": TelegramAccountantBot.reply_keyboard()}),
    ]


def test_back_to_menu_cancels_every_wizard_and_custom_period(tmp_path):
    steps = ("category", "label", "amount", "date", "manual_date", "details")
    transport = FakeTransport(
        [
            {"update_id": index + 1, "message": {"chat": {"id": index}, "text": "Назад в меню"}}
            for index in range(1, len(steps) + 2)
        ]
    )
    bot = TelegramAccountantBot(store(tmp_path), transport=transport)
    for chat_id, step in enumerate(steps, start=1):
        bot._flows[chat_id] = {"kind": "income", "step": step}
    bot._report_states[len(steps) + 1] = {"message_id": 999, "awaiting_custom": True}
    assert bot.poll_once(timeout=1) == len(steps) + 1
    assert not bot._flows
    assert not bot._report_states
    replies = [payload for method, payload in transport.calls if method == "sendMessage"]
    assert len(replies) == len(steps) + 1
    assert all(reply["text"] == "Главное меню." for reply in replies)
    assert all(reply["reply_markup"] == TelegramAccountantBot.reply_keyboard() for reply in replies)


def test_all_wizard_keyboards_include_back_to_menu():
    keyboards = (
        TelegramAccountantBot.reply_keyboard(),
        TelegramAccountantBot.date_keyboard(),
        TelegramAccountantBot.expense_category_keyboard(),
        TelegramAccountantBot.custom_period_keyboard(),
    )
    assert all(
        any(button["text"] == "Назад в меню" for row in keyboard["keyboard"] for button in row)
        for keyboard in keyboards
    )
    assert any(
        button["text"] == "Назад в меню"
        for row in TelegramAccountantBot.report_keyboard()["inline_keyboard"]
        for button in row
    )
