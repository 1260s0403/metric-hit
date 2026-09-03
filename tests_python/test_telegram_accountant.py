from datetime import UTC, datetime

import pytest

from metrichit_os.telegram_accountant import (
    AccountantCommands,
    AccountantStore,
    PAYMENT_METHODS,
    TelegramAccountantBot,
    format_money,
    parse_amount,
)


def store(tmp_path):
    return AccountantStore(tmp_path / "accountant.sqlite", now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC))


def shared_store(tmp_path):
    """Create the live migration shape: ten legacy rows owned by one chat."""
    database_path = tmp_path / "shared-accountant.sqlite"
    legacy = AccountantStore(database_path, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC))
    for index in range(10):
        legacy.add(101, "income", "100", f"Клиент {index + 1}")
    return AccountantStore(database_path, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC))


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


def private_message(update_id, user_id, text, username=None):
    sender = {"id": user_id}
    if username is not None:
        sender["username"] = username
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": user_id, "type": "private"},
            "from": sender,
            "text": text,
        },
    }


def test_shared_ledger_migrates_legacy_owner_and_persists_two_user_access(tmp_path):
    accounting_store = shared_store(tmp_path)
    assert accounting_store.shared_ledger_enabled()
    assert accounting_store.totals(101) == (100000, 0)

    transport = FakeTransport([
        private_message(1, 202, "/balance", "Ametric_hit"),
        private_message(2, 202, "/start", "Ametric_hit"),
        private_message(3, 202, "/income 25 Новый клиент", "Ametric_hit"),
        private_message(4, 101, "/balance", "renamed_owner"),
    ])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 4
    sent = [payload for method, payload in transport.calls if method == "sendMessage"]
    assert sent[0]["text"] == "Доступ к бухгалтерии закрыт."
    assert "Команды:" in sent[1]["text"]
    assert sent[2]["text"] == "Доход добавлен: 25.00 ₽ — Новый клиент."
    assert sent[3]["text"] == "Остаток: 1 025.00 ₽."
    assert accounting_store.totals(101) == accounting_store.totals(202) == (102500, 0)

    restarted = AccountantStore(accounting_store.database_path)
    assert restarted.authorize_private_user(202, 202, "changed_username")
    assert restarted.totals(202) == (102500, 0)


def test_shared_ledger_rejects_outsiders_and_prevents_role_rebinding(tmp_path):
    accounting_store = shared_store(tmp_path)
    assert accounting_store.authorize_private_user(
        202, 202, "Ametric_hit", allow_collaborator_binding=True
    )
    assert not accounting_store.authorize_private_user(
        303, 303, "Ametric_hit", allow_collaborator_binding=True
    )
    assert not accounting_store.authorize_private_user(
        404, 404, "outsider", allow_collaborator_binding=True
    )
    with pytest.raises(PermissionError):
        accounting_store.balance_cents(303)
    with pytest.raises(PermissionError):
        accounting_store.add(303, "expense", "10", "Чужой расход")

    transport = FakeTransport([
        private_message(1, 303, "/start", "Ametric_hit"),
        {
            "update_id": 2,
            "callback_query": {
                "id": "forbidden-callback",
                "from": {"id": 404, "username": "outsider"},
                "data": "report:summary",
                "message": {"message_id": 9, "chat": {"id": 404, "type": "private"}},
            },
        },
    ])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 2
    assert transport.calls[1][1]["text"] == "Доступ к бухгалтерии закрыт."
    assert transport.calls[-1] == (
        "answerCallbackQuery",
        {
            "callback_query_id": "forbidden-callback",
            "text": "Доступ к бухгалтерии закрыт.",
            "show_alert": True,
        },
    )


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


def test_income_button_flow_confirms_record_and_uses_selected_payment_method(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 9}, "text": "Доход"}},
        {"update_id": 2, "callback_query": {"id": "add", "data": "section:income:add", "message": {"message_id": 101, "chat": {"id": 9}}}},
        {"update_id": 3, "message": {"chat": {"id": 9}, "text": "@client"}},
        {"update_id": 4, "message": {"chat": {"id": 9}, "text": "1250.50"}},
        {"update_id": 5, "callback_query": {"id": "date", "data": "cal:f:d:2026-08-31", "message": {"message_id": 105, "chat": {"id": 9}}}},
        {"update_id": 6, "callback_query": {"id": "pay", "data": "pay:sbp", "message": {"message_id": 106, "chat": {"id": 9}}}},
    ])
    accounting_store = store(tmp_path)
    bot = TelegramAccountantBot(
        accounting_store, transport=transport, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )
    assert bot.poll_once(timeout=1) == 6
    confirmations = [
        payload for method, payload in transport.calls
        if method == "sendMessage" and payload["text"].startswith("Запись внесена.")
    ]
    assert confirmations == [{
        "chat_id": 9,
        "text": "Запись внесена.\nДоход: 1 250.50 ₽\nКлиент: @client\nДата: 2026-08-31\nСпособ пополнения: СБП",
        "reply_markup": TelegramAccountantBot.reply_keyboard(),
    }]
    assert accounting_store.breakdown(9, "income", "2026-08-31", "2026-08-31") == [("@client", 125050)]
    with accounting_store._connect() as connection:
        assert connection.execute("SELECT details FROM accountant_transactions").fetchone()["details"] == "СБП"


def test_expense_flow_is_isolated_between_chats(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 1}, "text": "Расход"}},
        {"update_id": 2, "message": {"chat": {"id": 2}, "text": "Расход"}},
        {"update_id": 3, "callback_query": {"id": "add-1", "data": "section:expense:add", "message": {"message_id": 101, "chat": {"id": 1}}}},
        {"update_id": 4, "callback_query": {"id": "add-2", "data": "section:expense:add", "message": {"message_id": 102, "chat": {"id": 2}}}},
        {"update_id": 5, "message": {"chat": {"id": 1}, "text": "Продвижение"}},
        {"update_id": 6, "message": {"chat": {"id": 2}, "text": "Сервисы"}},
        {"update_id": 7, "message": {"chat": {"id": 1}, "text": "Реклама"}},
        {"update_id": 8, "message": {"chat": {"id": 2}, "text": "Хостинг"}},
        {"update_id": 9, "message": {"chat": {"id": 1}, "text": "300"}},
        {"update_id": 10, "message": {"chat": {"id": 2}, "text": "50"}},
        {"update_id": 11, "callback_query": {"id": "today-1", "data": "cal:f:today", "message": {"message_id": 111, "chat": {"id": 1}}}},
        {"update_id": 12, "callback_query": {"id": "day-2", "data": "cal:f:d:2026-09-01", "message": {"message_id": 112, "chat": {"id": 2}}}},
    ])
    accounting_store = store(tmp_path)
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 12
    assert accounting_store.breakdown(1, "expense") == [("Реклама", 30000)]
    assert accounting_store.breakdown(2, "expense") == [("Хостинг", 5000)]
    assert accounting_store.expense_category_totals(1) == [("Бытовые", 0), ("Сервисы", 0), ("Продвижение", 30000), ("Выплаты", 0)]


def test_calendar_dates_save_income_and_expense_and_restore_main_keyboard(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 1}, "text": "Доход"}},
        {"update_id": 2, "callback_query": {"id": "add-income", "data": "section:income:add", "message": {"message_id": 101, "chat": {"id": 1}}}},
        {"update_id": 3, "message": {"chat": {"id": 1}, "text": "@client"}},
        {"update_id": 4, "message": {"chat": {"id": 1}, "text": "100"}},
        {"update_id": 5, "callback_query": {"id": "today-income", "data": "cal:f:today", "message": {"message_id": 105, "chat": {"id": 1}}}},
        {"update_id": 6, "callback_query": {"id": "invoice", "data": "pay:invoice", "message": {"message_id": 106, "chat": {"id": 1}}}},
        {"update_id": 7, "message": {"chat": {"id": 2}, "text": "Расход"}},
        {"update_id": 8, "callback_query": {"id": "add-expense", "data": "section:expense:add", "message": {"message_id": 108, "chat": {"id": 2}}}},
        {"update_id": 9, "message": {"chat": {"id": 2}, "text": "Продвижение"}},
        {"update_id": 10, "message": {"chat": {"id": 2}, "text": "Реклама"}},
        {"update_id": 11, "message": {"chat": {"id": 2}, "text": "25"}},
        {"update_id": 12, "callback_query": {"id": "yesterday-expense", "data": "cal:f:d:2026-09-01", "message": {"message_id": 112, "chat": {"id": 2}}}},
    ])
    accounting_store = store(tmp_path)
    bot = TelegramAccountantBot(
        accounting_store,
        transport=transport,
        now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC),
    )
    assert bot.poll_once(timeout=1) == 12
    sent = [payload for method, payload in transport.calls if method == "sendMessage"]
    assert any(payload["reply_markup"] == bot.calendar_keyboard("f") for payload in sent)
    assert any(payload["reply_markup"] == TelegramAccountantBot.payment_method_keyboard() for payload in sent)
    assert any(payload["reply_markup"] == TelegramAccountantBot.reply_keyboard() for payload in sent)
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


def test_custom_period_uses_calendar_validates_range_and_replaces_dashboard(tmp_path):
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
            "text": "Выберите начало периода.",
            "reply_markup": bot.calendar_keyboard("rs"),
        },
    )
    transport.updates = [
        {"update_id": 4, "callback_query": {"id": "start", "data": "cal:rs:d:2026-09-01", "message": {"message_id": 222, "chat": {"id": 5}}}},
        {"update_id": 5, "callback_query": {"id": "bad-end", "data": "cal:re:d:2026-08-31", "message": {"message_id": 222, "chat": {"id": 5}}}},
        {"update_id": 6, "callback_query": {"id": "end", "data": "cal:re:d:2026-09-02", "message": {"message_id": 222, "chat": {"id": 5}}}},
    ]
    assert bot.poll_once(timeout=1) == 3
    edits = [payload for method, payload in transport.calls if method == "editMessageText"]
    assert any("Конечная дата не может быть раньше" in edit["text"] for edit in edits)
    custom_edit = next(edit for edit in edits if edit["message_id"] == dashboard_id and "2026-09-01 — 2026-09-02" in edit["text"])
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
    assert len(edits) == len(actions) - 1
    assert all(edit["chat_id"] == 9 and edit["message_id"] == dashboard_id for edit in edits)
    assert "Доходы · За всё время" in edits[0]["text"]
    assert "Расходы · За всё время" in edits[1]["text"]
    assert "Расходы · Сегодня" in edits[2]["text"]
    assert "Расходы · Эта неделя" in edits[3]["text"]
    assert "Расходы · Этот месяц" in edits[4]["text"]
    assert len([method for method, _ in transport.calls if method == "answerCallbackQuery"]) == len(actions)


def test_report_callback_recovers_dashboard_after_bot_restart(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(9, "income", "100", "Клиент", "2026-09-02")
    dashboard_id = 404
    transport = FakeTransport(
        [
            {
                "update_id": 1,
                "callback_query": {
                    "id": "q-income",
                    "data": "report:income",
                    "message": {"message_id": dashboard_id, "chat": {"id": 9}},
                },
            },
            {
                "update_id": 2,
                "callback_query": {
                    "id": "q-month",
                    "data": "report:month",
                    "message": {"message_id": dashboard_id, "chat": {"id": 9}},
                },
            },
            {
                "update_id": 3,
                "callback_query": {
                    "id": "q-custom",
                    "data": "report:custom",
                    "message": {"message_id": dashboard_id, "chat": {"id": 9}},
                },
            },
            {
                "update_id": 4,
                "callback_query": {
                    "id": "q-summary-new-message",
                    "data": "report:summary",
                    "message": {"message_id": dashboard_id + 1, "chat": {"id": 9}},
                },
            },
        ]
    )
    bot = TelegramAccountantBot(
        accounting_store, transport=transport, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )

    assert bot.poll_once(timeout=1) == 4
    assert [method for method, _ in transport.calls] == [
        "getUpdates",
        "answerCallbackQuery",
        "editMessageText",
        "answerCallbackQuery",
        "editMessageText",
        "answerCallbackQuery",
        "sendMessage",
        "answerCallbackQuery",
    ]
    edits = [payload for method, payload in transport.calls if method == "editMessageText"]
    assert [edit["message_id"] for edit in edits] == [dashboard_id, dashboard_id]
    assert "Доходы · За всё время" in edits[0]["text"]
    assert "Доходы · Этот месяц" in edits[1]["text"]
    assert bot._report_states[9]["message_id"] == dashboard_id + 1
    assert bot._report_states[9].get("awaiting_custom") is not True


def test_active_report_buttons_are_acknowledged_without_identical_edit(tmp_path):
    transport = FakeTransport([])
    bot = TelegramAccountantBot(
        store(tmp_path), transport=transport, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )
    dashboard_id = 404
    bot._report_states[9] = bot._new_report_state(dashboard_id)

    for update_id, action in enumerate(("summary", "month", "month", "income"), start=1):
        transport.updates = [
            {
                "update_id": update_id,
                "callback_query": {
                    "id": f"q-{update_id}",
                    "data": f"report:{action}",
                    "message": {"message_id": dashboard_id, "chat": {"id": 9}},
                },
            }
        ]
        assert bot.poll_once(timeout=1) == 1

    assert len([method for method, _ in transport.calls if method == "answerCallbackQuery"]) == 4
    edits = [payload for method, payload in transport.calls if method == "editMessageText"]
    assert len(edits) == 2
    assert "Финансы · Этот месяц" in edits[0]["text"]
    assert "Доходы · Этот месяц" in edits[1]["text"]


def test_run_forever_recovers_after_polling_exception(tmp_path):
    class RecoveringTransport(FakeTransport):
        def __init__(self):
            super().__init__([{"update_id": 1, "message": {"chat": {"id": 9}, "text": "/balance"}}])
            self.failed = False

        def call(self, method, payload):
            if method == "getUpdates" and not self.failed:
                self.failed = True
                self.calls.append((method, payload))
                raise RuntimeError("temporary Telegram failure")
            return super().call(method, payload)

    delays = []

    def stop_after_recovery(delay):
        delays.append(delay)
        if len(delays) == 2:
            raise SystemExit

    transport = RecoveringTransport()
    bot = TelegramAccountantBot(
        store(tmp_path), transport=transport, sleep=stop_after_recovery, retry_delay=2.5
    )

    with pytest.raises(SystemExit):
        bot.run_forever()

    assert [method for method, _ in transport.calls].count("getUpdates") == 2
    assert any(method == "sendMessage" for method, _ in transport.calls)
    assert delays == [2.5, 0.2]


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
    steps = ("category", "label", "amount", "date", "details")
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
    bot = TelegramAccountantBot.__new__(TelegramAccountantBot)
    bot._now = lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    keyboards = (
        TelegramAccountantBot.expense_category_keyboard(),
        TelegramAccountantBot.wizard_keyboard(),
    )
    assert all(
        {"Назад", "Отменить и в меню"}.issubset(
            {button["text"] for row in keyboard["keyboard"] for button in row}
        )
        for keyboard in keyboards
    )
    assert any(
        button["text"] == "Назад"
        for row in bot.calendar_keyboard("f")["inline_keyboard"]
        for button in row
    )
    assert any(
        button["text"] == "Назад в меню"
        for row in TelegramAccountantBot.report_keyboard()["inline_keyboard"]
        for button in row
    )


def test_main_menu_has_no_back_button_and_internal_menus_keep_back_navigation(tmp_path):
    assert TelegramAccountantBot.reply_keyboard()["keyboard"] == [
        [{"text": "Доход"}, {"text": "Расход"}, {"text": "Отчёты"}]
    ]
    bot = TelegramAccountantBot(
        store(tmp_path), transport=FakeTransport([]), now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )
    internal = [
        TelegramAccountantBot.section_keyboard("income"),
        TelegramAccountantBot.section_keyboard("expense"),
        TelegramAccountantBot.report_keyboard(),
        TelegramAccountantBot.payment_method_keyboard(),
        bot.calendar_keyboard("f"),
    ]
    assert all(
        any(button["text"].startswith("Назад") for row in keyboard["inline_keyboard"] for button in row)
        for keyboard in internal
    )
    method_buttons = [
        button["text"]
        for row in TelegramAccountantBot.payment_method_keyboard()["inline_keyboard"][:-1]
        for button in row
    ]
    assert tuple(method_buttons) == PAYMENT_METHODS


def test_calendar_handles_leap_month_navigation_and_callback_size(tmp_path):
    bot = TelegramAccountantBot(
        store(tmp_path), transport=FakeTransport([]), now=lambda: datetime(2024, 2, 15, 12, tzinfo=UTC)
    )
    keyboard = bot.calendar_keyboard("f")
    buttons = [button for row in keyboard["inline_keyboard"] for button in row]
    callbacks = [button["callback_data"] for button in buttons]
    assert "cal:f:d:2024-02-29" in callbacks
    assert "cal:f:d:2024-02-30" not in callbacks
    assert "cal:f:n:2024-01" in callbacks and "cal:f:n:2024-03" in callbacks
    assert max(len(value.encode("utf-8")) for value in callbacks) <= 64


def test_income_save_confirmation_survives_section_edit_failure_without_duplicate(tmp_path):
    class FailingEditTransport(FakeTransport):
        def call(self, method, payload):
            if method == "editMessageText" and payload.get("message_id") == 300:
                self.calls.append((method, payload))
                raise RuntimeError("old section cannot be edited")
            return super().call(method, payload)

    accounting_store = store(tmp_path)
    transport = FailingEditTransport([
        {"update_id": 1, "callback_query": {"id": "pay-1", "data": "pay:usdt", "message": {"message_id": 400, "chat": {"id": 3}}}},
        {"update_id": 2, "callback_query": {"id": "pay-retry", "data": "pay:usdt", "message": {"message_id": 400, "chat": {"id": 3}}}},
    ])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    bot._section_states[3] = {"message_id": 300, "kind": "income", "view": "root"}
    bot._flows[3] = {
        "kind": "income", "step": "details", "label": "@client", "amount": "100",
        "date": "2026-09-02", "origin_kind": "income", "origin_message_id": 300,
    }
    assert bot.poll_once(timeout=1) == 2
    assert accounting_store.totals(3) == (10000, 0)
    confirmations = [
        payload for method, payload in transport.calls
        if method == "sendMessage" and payload["text"].startswith("Запись внесена.")
    ]
    assert len(confirmations) == 1
    assert "Клиент: @client" in confirmations[0]["text"]
    assert "Способ пополнения: USDT" in confirmations[0]["text"]


def test_income_confirmation_retries_api_once_without_duplicate_transaction(tmp_path):
    class RetryConfirmationTransport(FakeTransport):
        def __init__(self, updates):
            super().__init__(updates)
            self.failed = False

        def call(self, method, payload):
            if method == "sendMessage" and str(payload.get("text", "")).startswith("Запись внесена.") and not self.failed:
                self.failed = True
                self.calls.append((method, payload))
                raise RuntimeError("temporary send failure")
            return super().call(method, payload)

    accounting_store = store(tmp_path)
    transport = RetryConfirmationTransport([
        {"update_id": 1, "callback_query": {"id": "pay", "data": "pay:btc", "message": {"message_id": 400, "chat": {"id": 3}}}},
    ])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    bot._flows[3] = {
        "kind": "income", "step": "details", "label": "Клиент", "amount": "50",
        "date": "2026-09-02", "origin_kind": "income", "origin_message_id": 300,
    }
    assert bot.poll_once(timeout=1) == 1
    assert accounting_store.totals(3) == (5000, 0)
    confirmation_calls = [
        payload for method, payload in transport.calls
        if method == "sendMessage" and str(payload.get("text", "")).startswith("Запись внесена.")
    ]
    assert len(confirmation_calls) == 2


def test_financial_ui_exposes_no_delete_actions(tmp_path):
    bot = TelegramAccountantBot(
        store(tmp_path), transport=FakeTransport([]), now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )
    keyboards = [
        TelegramAccountantBot.reply_keyboard(),
        TelegramAccountantBot.section_keyboard("income"),
        TelegramAccountantBot.section_keyboard("expense"),
        TelegramAccountantBot.report_keyboard(),
        TelegramAccountantBot.payment_method_keyboard(),
        bot.calendar_keyboard("f"),
        bot.calendar_keyboard("rs"),
        bot.calendar_keyboard("re"),
    ]
    serialized = str(keyboards).casefold()
    assert "удал" not in serialized and "delete" not in serialized
    assert "/delete" not in AccountantCommands.HELP.casefold()


def test_income_and_expense_sections_have_exact_root_buttons_and_month_metrics(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(7, "income", "100", "@one", "2026-09-01", details="СБП")
    accounting_store.add(7, "income", "50", "@two", "2026-09-02", details="Карта")
    accounting_store.add(7, "expense", "20", "Реклама", "2026-09-02", category="Продвижение")
    transport = FakeTransport([
        {"update_id": 1, "message": {"chat": {"id": 7}, "text": "Доход"}},
        {"update_id": 2, "message": {"chat": {"id": 7}, "text": "Расход"}},
    ])
    bot = TelegramAccountantBot(
        accounting_store, transport=transport, now=lambda: datetime(2026, 9, 2, 12, tzinfo=UTC)
    )
    assert bot.poll_once(timeout=1) == 2
    sections = [payload for method, payload in transport.calls if method == "sendMessage"]
    assert sections[0]["text"] == "Доходы · Этот месяц\n\nВсего: 150.00 ₽\nКлиентов: 2"
    assert sections[1]["text"] == "Расходы · Этот месяц\n\nВсего: 20.00 ₽\nКрупнее всего: Продвижение"
    assert [row[0]["text"] for row in sections[0]["reply_markup"]["inline_keyboard"]] == [
        "Добавить доход", "Последние поступления", "По клиентам", "По способу оплаты", "Назад в меню"
    ]
    assert [row[0]["text"] for row in sections[1]["reply_markup"]["inline_keyboard"]] == [
        "Добавить расход", "Последние расходы", "По категориям", "По получателям", "Назад в меню"
    ]


def test_every_section_view_edits_same_message_with_real_chat_scoped_data(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(7, "income", "100", "@client", "2026-09-02", details="СБП")
    accounting_store.add(7, "income", "25", "@client", "2026-09-01")
    accounting_store.add(7, "expense", "30", "Яндекс", "2026-09-02", category="Сервисы")
    accounting_store.add(8, "income", "999", "Чужой", "2026-09-02", details="Чужой способ")
    accounting_store.add(8, "expense", "999", "Чужой расход", "2026-09-02", category="Выплаты")
    callbacks = [
        ("income", "latest"), ("income", "labels"), ("income", "details"),
        ("expense", "latest"), ("expense", "categories"), ("expense", "labels"),
    ]
    transport = FakeTransport([
        {
            "update_id": index,
            "callback_query": {
                "id": f"q-{kind}-{view}",
                "data": f"section:{kind}:{view}",
                "message": {"message_id": 500 if kind == "income" else 600, "chat": {"id": 7}},
            },
        }
        for index, (kind, view) in enumerate(callbacks, start=1)
    ])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == len(callbacks)
    edits = [payload for method, payload in transport.calls if method == "editMessageText"]
    assert [edit["message_id"] for edit in edits] == [500, 500, 500, 600, 600, 600]
    combined = "\n".join(str(edit["text"]) for edit in edits)
    assert "2026-09-02 · 100.00 ₽ · @client · СБП" in combined
    assert "@client — 125.00 ₽" in combined
    assert "СБП — 100.00 ₽" in combined and "Не указан — 25.00 ₽" in combined
    assert "2026-09-02 · 30.00 ₽ · Яндекс · Сервисы" in combined
    assert all(category in combined for category in ("Бытовые", "Сервисы", "Продвижение", "Выплаты"))
    assert "Яндекс — 30.00 ₽" in combined
    assert "Чужой" not in combined and "999.00 ₽" not in combined
    assert all(
        [row[0]["text"] for row in edit["reply_markup"]["inline_keyboard"]] == ["Назад", "Назад в меню"]
        for edit in edits
    )
    assert len([method for method, _ in transport.calls if method == "answerCallbackQuery"]) == len(callbacks)


def test_section_callbacks_recover_after_restart_and_active_child_button_is_idempotent(tmp_path):
    accounting_store = store(tmp_path)
    accounting_store.add(4, "income", "10", "Клиент", "2026-09-02", details="СБП")
    transport = FakeTransport([
        {"update_id": 1, "callback_query": {"id": "latest", "data": "section:income:latest", "message": {"message_id": 404, "chat": {"id": 4}}}},
        {"update_id": 2, "callback_query": {"id": "latest-again", "data": "section:income:latest", "message": {"message_id": 404, "chat": {"id": 4}}}},
        {"update_id": 3, "callback_query": {"id": "root", "data": "section:income:root", "message": {"message_id": 404, "chat": {"id": 4}}}},
    ])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    assert bot.poll_once(timeout=1) == 3
    assert len([method for method, _ in transport.calls if method == "answerCallbackQuery"]) == 3
    edits = [payload for method, payload in transport.calls if method == "editMessageText"]
    assert len(edits) == 2
    assert "Последние 5" in edits[0]["text"]
    assert "Доходы · Этот месяц" in edits[1]["text"]


def test_section_back_to_menu_clears_states_and_restores_main_keyboard(tmp_path):
    transport = FakeTransport([
        {"update_id": 1, "callback_query": {"id": "back", "data": "section:expense:back", "message": {"message_id": 55, "chat": {"id": 4}}}},
    ])
    bot = TelegramAccountantBot(store(tmp_path), transport=transport)
    bot._flows[4] = {"kind": "expense", "step": "label"}
    bot._report_states[4] = {"message_id": 12}
    bot._section_states[4] = {"message_id": 55, "kind": "expense", "view": "root"}
    assert bot.poll_once(timeout=1) == 1
    assert 4 not in bot._flows and 4 not in bot._report_states and 4 not in bot._section_states
    assert transport.calls[-2][1]["reply_markup"] == {"inline_keyboard": []}
    assert transport.calls[-1] == (
        "sendMessage",
        {"chat_id": 4, "text": "Главное меню.", "reply_markup": TelegramAccountantBot.reply_keyboard()},
    )


def test_wizard_backtracks_retains_values_and_cancel_never_saves_incomplete_operation(tmp_path):
    accounting_store = store(tmp_path)
    transport = FakeTransport([])
    bot = TelegramAccountantBot(accounting_store, transport=transport)
    bot._section_states[3] = {"message_id": 300, "kind": "income", "view": "root"}
    bot._flows[3] = {
        "kind": "income", "step": "details", "label": "@client", "amount": "100",
        "date": "2026-09-02", "origin_kind": "income", "origin_message_id": 300,
    }
    transport.updates = [
        {"update_id": 1, "message": {"chat": {"id": 3}, "text": "Назад"}},
        {"update_id": 2, "message": {"chat": {"id": 3}, "text": "Назад"}},
        {"update_id": 3, "message": {"chat": {"id": 3}, "text": "Назад"}},
    ]
    assert bot.poll_once(timeout=1) == 3
    assert bot._flows[3]["step"] == "label"
    assert bot._flows[3]["amount"] == "100" and bot._flows[3]["date"] == "2026-09-02"
    transport.updates = [
        {"update_id": 4, "message": {"chat": {"id": 3}, "text": "Назад"}},
    ]
    assert bot.poll_once(timeout=1) == 1
    assert 3 not in bot._flows
    assert accounting_store.totals(3) == (0, 0)
    assert transport.calls[-1][1]["reply_markup"] == TelegramAccountantBot.reply_keyboard()

    bot._flows[3] = {"kind": "expense", "step": "amount", "category": "Сервисы", "label": "Хостинг"}
    bot._report_states[3] = {"message_id": 999, "awaiting_custom": True}
    transport.updates = [
        {"update_id": 5, "message": {"chat": {"id": 3}, "text": "Отменить и в меню"}},
    ]
    assert bot.poll_once(timeout=1) == 1
    assert 3 not in bot._flows and 3 not in bot._section_states and 3 not in bot._report_states
    assert accounting_store.totals(3) == (0, 0)
