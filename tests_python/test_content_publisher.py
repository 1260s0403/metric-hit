from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from metrichit_os.content_publisher import (
    ACCESS_DENIED,
    ChannelCandidate,
    ContentPublisherBot,
    ContentPublisherStore,
    TEST_INTERVAL_SECONDS,
    TEST_TOTAL_POSTS,
    TEST_POSTS,
    channel_message_payload,
)
from metrichit_os.local_author import sanitize_plain_text


class FakeTransport:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.calls = []

    def call(self, method, payload):
        self.calls.append((method, payload))
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return {"ok": True, "result": updates}
        return {"ok": True, "result": True}


class PublishingTransport(FakeTransport):
    def __init__(self, updates=()):
        super().__init__(updates)
        self.message_id = 76

    def call(self, method, payload):
        self.calls.append((method, payload))
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return {"ok": True, "result": updates}
        if method == "sendMessage" and payload.get("chat_id") == -100123:
            self.message_id += 1
            return {"ok": True, "result": {"message_id": self.message_id}}
        return {"ok": True, "result": True}


class MemberTransport(PublishingTransport):
    def __init__(self, updates=(), *, status="administrator"):
        super().__init__(updates)
        self.status = status

    def call(self, method, payload):
        if method == "getChatMember":
            self.calls.append((method, payload))
            return {"ok": True, "result": {"status": self.status}}
        return super().call(method, payload)


class VerificationResponseTransport(PublishingTransport):
    def __init__(self, updates, response):
        super().__init__(updates)
        self.response = response

    def call(self, method, payload):
        if method == "getChatMember":
            self.calls.append((method, payload))
            return self.response
        return super().call(method, payload)


class AmbiguousFailureTransport(PublishingTransport):
    def call(self, method, payload):
        if method == "sendMessage" and payload.get("chat_id") == -100123:
            self.calls.append((method, payload))
            raise TimeoutError("delivery outcome unknown")
        return super().call(method, payload)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 13, 10, tzinfo=UTC)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def store(tmp_path):
    return ContentPublisherStore(
        tmp_path / "publisher.sqlite",
        now=lambda: datetime(2026, 9, 13, 10, tzinfo=UTC),
    )


def message(update_id, user_id, text, *, chat_type="private", chat_id=None):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": user_id if chat_id is None else chat_id, "type": chat_type},
            "from": {"id": user_id},
            "text": text,
        },
    }


def callback(update_id, callback_id, user_id, data, *, chat_type="private", chat_id=None):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": callback_id,
            "from": {"id": user_id},
            "data": data,
            "message": {
                "message_id": 10,
                "chat": {"id": user_id if chat_id is None else chat_id, "type": chat_type},
            },
        },
    }


def test_store_persists_text_only_draft_and_decision(tmp_path):
    database = tmp_path / "publisher.sqlite"
    first = ContentPublisherStore(database)
    draft = first.create_job(101, "Как проверить позиции перед тестом")
    assert draft.status == "in_review"
    assert "Картинка" not in ContentPublisherBot.preview(draft)
    assert len(draft.content_hash) == 64

    decision = first.approve(draft.job_id, 1, 101)
    assert decision.accepted and decision.status == "ready_to_publish"
    restarted = ContentPublisherStore(database)
    assert restarted.get(draft.job_id).status == "ready_to_publish"
    with restarted._connect() as connection:
        event = connection.execute("SELECT action, outcome FROM content_decisions").fetchone()
    assert tuple(event) == ("approve", "ready_to_publish")


def test_generator_is_deterministic_and_local(tmp_path):
    repository = store(tmp_path)
    first = repository.create_job(101, "  Проверка   сайта ")
    second = repository.create_job(101, "Проверка сайта")
    assert first.content == second.content
    assert first.content_hash == second.content_hash


def test_owner_creates_preview_and_approve_only_marks_ready(tmp_path):
    transport = FakeTransport([message(1, 101, "/draft Что проверить до запуска")])
    bot = ContentPublisherBot(store(tmp_path), {101}, transport)
    assert bot.poll_once(timeout=1) == 1
    assert transport.calls[0] == ("getUpdates", {"timeout": 1})
    method, preview = transport.calls[1]
    assert method == "sendMessage"
    assert [button["text"] for button in preview["reply_markup"]["inline_keyboard"][0]] == [
        "✅ Одобрить", "✏️ Доработать", "❌ Отклонить"
    ]
    approve_data = preview["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    job_id = approve_data.split(":")[2]
    transport.updates = [callback(2, "approve", 101, approve_data)]
    assert bot.poll_once() == 1
    assert bot.store.get(job_id).status == "ready_to_publish"
    assert {method for method, _ in transport.calls} <= {
        "getUpdates", "sendMessage", "answerCallbackQuery"
    }
    assert not any("channel" in method.casefold() or method == "sendPhoto" for method, _ in transport.calls)


def test_outsider_group_and_spoofed_callback_are_rejected(tmp_path):
    repository = store(tmp_path)
    draft = repository.create_job(101, "Безопасность")
    data = f"cp:a:{draft.job_id}:1"
    transport = FakeTransport([
        message(1, 202, "/list"),
        message(2, 101, "/list", chat_type="group", chat_id=-50),
        callback(3, "spoof", 101, data, chat_id=999),
    ])
    bot = ContentPublisherBot(repository, {101}, transport)
    assert bot.poll_once() == 3
    assert repository.get(draft.job_id).status == "in_review"
    sent_texts = [payload["text"] for method, payload in transport.calls if method == "sendMessage"]
    assert sent_texts == [ACCESS_DENIED, ACCESS_DENIED]
    assert transport.calls[-1] == (
        "answerCallbackQuery",
        {"callback_query_id": "spoof", "text": ACCESS_DENIED, "show_alert": True},
    )


def test_revision_flow_creates_new_immutable_version_and_stale_buttons_fail(tmp_path):
    repository = store(tmp_path)
    draft = repository.create_job(101, "Тестовая тема")
    assert repository.request_revision(draft.job_id, 1, 101).accepted
    revised = repository.revise(draft.job_id, 101, "добавить чек-лист")
    assert revised.version == 2 and revised.status == "in_review"
    assert "добавить чек-лист" in revised.content
    stale = repository.approve(draft.job_id, 1, 101)
    assert not stale.accepted and "устаревшей" in stale.reason
    assert repository.approve(draft.job_id, 2, 101).accepted
    replay = repository.reject(draft.job_id, 2, 101)
    assert not replay.accepted and replay.status == "ready_to_publish"
    with repository._connect() as connection:
        versions = connection.execute(
            "SELECT version, revision_note FROM content_drafts WHERE job_id = ? ORDER BY version",
            (draft.job_id,),
        ).fetchall()
    assert [tuple(row) for row in versions] == [(1, ""), (2, "добавить чек-лист")]


def test_callback_revision_and_reject_actions_are_explicit(tmp_path):
    repository = store(tmp_path)
    revise_draft = repository.create_job(101, "На доработку")
    reject_draft = repository.create_job(101, "На отклонение")
    transport = FakeTransport([
        callback(1, "revise", 101, f"cp:v:{revise_draft.job_id}:1"),
        callback(2, "reject", 101, f"cp:r:{reject_draft.job_id}:1"),
    ])
    bot = ContentPublisherBot(repository, {101}, transport)
    assert bot.poll_once() == 2
    assert repository.get(revise_draft.job_id).status == "revision_requested"
    assert repository.get(reject_draft.job_id).status == "rejected"
    answers = [payload["text"] for method, payload in transport.calls if method == "answerCallbackQuery"]
    assert answers[0].startswith("Решение сохранено. Отправьте /revise")
    assert answers[1] == "Черновик отклонён."


def test_forwarded_channel_requires_explicit_bind_then_publish_after_approval(tmp_path):
    forwarded = {
        "update_id": 1,
        "message": {
            "chat": {"id": 101, "type": "private"}, "from": {"id": 101},
            "forward_origin": {"type": "channel", "chat": {"id": -100123, "title": "Тестовый канал"}},
        },
    }
    transport = PublishingTransport([forwarded, message(2, 101, "/bind")])
    bot = ContentPublisherBot(store(tmp_path), {101}, transport)
    assert bot.poll_once() == 2
    assert bot.store.channel_binding().channel_id == -100123

    draft = bot.store.create_job(101, "Проверка перед публикацией")
    transport.updates = [message(3, 101, f"/publish {draft.job_id}")]
    assert bot.poll_once() == 1
    assert not any(payload.get("chat_id") == -100123 for method, payload in transport.calls if method == "sendMessage")

    assert bot.store.approve(draft.job_id, draft.version, 101).accepted
    transport.updates = [message(4, 101, f"/publish {draft.job_id}")]
    assert bot.poll_once() == 1
    channel_messages = [payload for method, payload in transport.calls if method == "sendMessage" and payload.get("chat_id") == -100123]
    assert channel_messages == [channel_message_payload(-100123, draft.content)]
    with bot.store._connect() as connection:
        publication = connection.execute("SELECT channel_id, telegram_message_id FROM content_publications").fetchone()
    assert tuple(publication) == (-100123, 77)
    transport.updates = [message(5, 101, f"/publish {draft.job_id}")]
    assert bot.poll_once() == 1
    assert len([payload for method, payload in transport.calls if method == "sendMessage" and payload.get("chat_id") == -100123]) == 1


def test_live_transport_uses_only_process_environment_and_never_contacts_on_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("METRICHIT_PUBLISHER_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="METRICHIT_PUBLISHER_BOT_TOKEN"):
        ContentPublisherBot.from_environment(store(tmp_path), {101})

    monkeypatch.setenv("METRICHIT_PUBLISHER_BOT_TOKEN", "secret-only-in-process")
    bot = ContentPublisherBot.from_environment(store(tmp_path), {101})
    assert bot.offset is None


def test_missing_environment_owner_id_allows_safe_pending_forward_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv("METRICHIT_PUBLISHER_BOT_TOKEN", "secret-only-in-process")
    monkeypatch.delenv("METRICHIT_PUBLISHER_OWNER_IDS", raising=False)
    bot = ContentPublisherBot.from_environment(store(tmp_path))
    assert bot.owner_user_ids == frozenset()
    assert bot.offset is None


def test_pending_forward_discovers_and_persists_verified_channel_admin(tmp_path):
    database = tmp_path / "publisher.sqlite"
    repository = ContentPublisherStore(database)
    forwarded = {
        "update_id": 1,
        "message": {
            "chat": {"id": 101, "type": "private"}, "from": {"id": 101},
            "forward_origin": {"type": "channel", "chat": {"id": -100123, "title": "Тестовый канал"}},
        },
    }
    transport = MemberTransport([forwarded])
    bot = ContentPublisherBot(repository, set(), transport)

    assert bot.poll_once() == 1
    assert ("getChatMember", {"chat_id": -100123, "user_id": 101}) in transport.calls
    assert repository.channel_binding().channel_id == -100123
    assert repository.verified_owner_user_ids() == frozenset({101})

    restarted = ContentPublisherBot(ContentPublisherStore(database), set(), transport)
    transport.updates = [message(2, 101, "/status")]
    assert restarted.poll_once() == 1
    assert transport.calls[-1][0] == "sendMessage"
    assert transport.calls[-1][1]["chat_id"] == 101


@pytest.mark.parametrize("status", ["member", "restricted", "left", "kicked"])
def test_non_admin_forward_sender_cannot_claim_first_owner(tmp_path, status):
    repository = store(tmp_path)
    forwarded = {
        "update_id": 1,
        "message": {
            "chat": {"id": 202, "type": "private"}, "from": {"id": 202},
            "forward_origin": {"type": "channel", "chat": {"id": -100123, "title": "Тестовый канал"}},
        },
    }
    transport = MemberTransport([forwarded], status=status)
    bot = ContentPublisherBot(repository, set(), transport)

    assert bot.poll_once() == 1
    assert repository.verified_owner_user_ids() == frozenset()
    with pytest.raises(ValueError, match="ещё не привязан"):
        repository.channel_binding()
    assert transport.calls[-1] == ("sendMessage", {"chat_id": 202, "text": ACCESS_DENIED})


def test_plain_or_ambiguous_first_update_never_claims_ownership(tmp_path):
    malformed_forward = {
        "update_id": 2,
        "message": {
            "chat": {"id": 202, "type": "private"}, "from": {"id": 202},
            "forward_origin": {"type": "channel", "chat": {"title": "Без ID"}},
        },
    }
    transport = MemberTransport([message(1, 202, "/start_test"), malformed_forward])
    repository = store(tmp_path)
    bot = ContentPublisherBot(repository, set(), transport)

    assert bot.poll_once() == 2
    assert repository.verified_owner_user_ids() == frozenset()
    assert not any(method == "getChatMember" for method, _ in transport.calls)


@pytest.mark.parametrize("response", [{}, {"ok": False}, {"ok": True, "result": True}])
def test_ambiguous_membership_response_fails_closed(tmp_path, response):
    forwarded = {
        "update_id": 1,
        "message": {
            "chat": {"id": 202, "type": "private"}, "from": {"id": 202},
            "forward_origin": {"type": "channel", "chat": {"id": -100123, "title": "Тестовый канал"}},
        },
    }
    repository = store(tmp_path)
    transport = VerificationResponseTransport([forwarded], response)
    bot = ContentPublisherBot(repository, set(), transport)

    assert bot.poll_once() == 1
    assert repository.verified_owner_user_ids() == frozenset()
    assert transport.calls[-1] == ("sendMessage", {"chat_id": 202, "text": ACCESS_DENIED})


def test_explicit_owner_ids_override_discovery_and_keep_previous_behavior(tmp_path):
    forwarded = {
        "update_id": 1,
        "message": {
            "chat": {"id": 101, "type": "private"}, "from": {"id": 101},
            "forward_origin": {"type": "channel", "chat": {"id": -100123, "title": "Тестовый канал"}},
        },
    }
    transport = MemberTransport([forwarded], status="member")
    repository = store(tmp_path)
    bot = ContentPublisherBot(repository, {101}, transport)

    assert bot.poll_once() == 1
    assert repository.channel_binding().channel_id == -100123
    assert not any(method == "getChatMember" for method, _ in transport.calls)


def test_forwarded_channel_auto_binds_and_owner_starts_then_stops_schedule(tmp_path):
    clock = Clock()
    repository = ContentPublisherStore(tmp_path / "publisher.sqlite", now=clock)
    forwarded = {
        "update_id": 1,
        "message": {
            "chat": {"id": 101, "type": "private"}, "from": {"id": 101},
            "forward_origin": {"type": "channel", "chat": {"id": -100123, "title": "Тестовый канал"}},
        },
    }
    transport = PublishingTransport([forwarded, message(2, 101, "/start_test")])
    bot = ContentPublisherBot(repository, {101}, transport)

    assert bot.poll_once() == 2
    assert repository.channel_binding().channel_id == -100123
    assert repository.test_schedule().published_slots == 1
    assert [payload["chat_id"] for method, payload in transport.calls if method == "sendMessage"].count(-100123) == 1

    transport.updates = [message(3, 101, "/stop")]
    assert bot.poll_once() == 1
    clock.advance(TEST_INTERVAL_SECONDS * 3)
    assert not bot.publish_due_test_post()
    assert repository.test_schedule().status == "stopped"
    assert [payload["chat_id"] for method, payload in transport.calls if method == "sendMessage"].count(-100123) == 1


def test_stopped_schedule_can_start_fresh_without_losing_history_or_allowing_concurrency(tmp_path):
    clock = Clock()
    repository = ContentPublisherStore(tmp_path / "publisher.sqlite", now=clock)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    first = repository.start_test_schedule(101)
    transport = PublishingTransport()
    bot = ContentPublisherBot(repository, {101}, transport)

    assert bot.publish_due_test_post()
    stopped = repository.stop_test_schedule(101)
    assert stopped.schedule_id == first.schedule_id
    assert stopped.status == "stopped"

    second = repository.start_test_schedule(101)
    assert second.schedule_id != first.schedule_id
    assert second.status == "active"
    assert second.published_slots == 0
    with pytest.raises(ValueError, match="уже активно"):
        repository.start_test_schedule(101)

    with repository._connect() as connection:
        schedules = connection.execute(
            "SELECT schedule_id, status FROM content_test_schedule ORDER BY rowid"
        ).fetchall()
        slot_counts = connection.execute(
            """SELECT schedule_id, COUNT(*) AS count
               FROM content_test_schedule_slots GROUP BY schedule_id"""
        ).fetchall()
        old_slot_statuses = connection.execute(
            "SELECT status FROM content_test_schedule_slots WHERE schedule_id=?",
            (first.schedule_id,),
        ).fetchall()

    assert [(row["schedule_id"], row["status"]) for row in schedules] == [
        (first.schedule_id, "stopped"),
        (second.schedule_id, "active"),
    ]
    assert {row["schedule_id"]: row["count"] for row in slot_counts} == {
        first.schedule_id: TEST_TOTAL_POSTS,
        second.schedule_id: TEST_TOTAL_POSTS,
    }
    assert [row["status"] for row in old_slot_statuses].count("published") == 1
    assert [row["status"] for row in old_slot_statuses].count("skipped") == TEST_TOTAL_POSTS - 1


def test_singleton_schedule_schema_migrates_without_losing_existing_run(tmp_path):
    database = tmp_path / "publisher.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE content_test_schedule (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                schedule_id TEXT NOT NULL UNIQUE,
                owner_user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'completed', 'failed')),
                started_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                stopped_at TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT INTO content_test_schedule VALUES
                (1, 'legacy-run', 101, -100123, 'stopped',
                 '2026-09-13T10:00:00+00:00', '2026-09-13T11:00:00+00:00',
                 '2026-09-13T10:03:00+00:00', '2026-09-13T10:03:00+00:00');
            """
        )

    repository = ContentPublisherStore(database)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    assert repository.test_schedule().schedule_id == "legacy-run"
    fresh = repository.start_test_schedule(101)
    assert fresh.schedule_id != "legacy-run"

    with repository._connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(content_test_schedule)")}
        schedules = connection.execute(
            "SELECT schedule_id, status FROM content_test_schedule ORDER BY rowid"
        ).fetchall()
    assert "singleton" not in columns
    assert [(row["schedule_id"], row["status"]) for row in schedules] == [
        ("legacy-run", "stopped"),
        (fresh.schedule_id, "active"),
    ]

def test_channel_binding_is_one_time_and_cannot_be_silently_replaced(tmp_path):
    repository = store(tmp_path)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    assert repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None)).channel_id == -100123
    with pytest.raises(ValueError, match="смена канала заблокирована"):
        repository.bind_channel(101, ChannelCandidate(-100999, "Другой канал", None))
    assert repository.channel_binding().channel_id == -100123


def test_schedule_publishes_exactly_twenty_slots_and_survives_restart_without_duplicates(tmp_path):
    clock = Clock()
    database = tmp_path / "publisher.sqlite"
    repository = ContentPublisherStore(database, now=clock)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    repository.start_test_schedule(101)
    transport = PublishingTransport()
    bot = ContentPublisherBot(repository, {101}, transport)

    assert bot.publish_due_test_post()
    restarted = ContentPublisherBot(ContentPublisherStore(database, now=clock), {101}, transport)
    assert not restarted.publish_due_test_post()
    for _ in range(1, TEST_TOTAL_POSTS):
        clock.advance(TEST_INTERVAL_SECONDS)
        assert restarted.publish_due_test_post()

    schedule = restarted.store.test_schedule()
    assert schedule.status == "completed"
    assert schedule.published_slots == TEST_TOTAL_POSTS
    channel_calls = [payload for method, payload in transport.calls if method == "sendMessage" and payload.get("chat_id") == -100123]
    assert len(channel_calls) == TEST_TOTAL_POSTS
    with restarted.store._connect() as connection:
        rows = connection.execute(
            "SELECT slot_index, status, telegram_message_id FROM content_test_schedule_slots ORDER BY slot_index"
        ).fetchall()
    assert [row["slot_index"] for row in rows] == list(range(TEST_TOTAL_POSTS))
    assert {row["status"] for row in rows} == {"published"}
    assert len({row["telegram_message_id"] for row in rows}) == TEST_TOTAL_POSTS


def test_schedule_slots_are_distinct_plain_text_posts_with_varied_formats_and_directions(tmp_path):
    repository = store(tmp_path)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    repository.start_test_schedule(101)
    with repository._connect() as connection:
        rows = connection.execute(
            "SELECT content FROM content_test_schedule_slots ORDER BY slot_index"
        ).fetchall()

    contents = [str(row["content"]) for row in rows]
    assert len(contents) == TEST_TOTAL_POSTS
    assert len(set(contents)) == TEST_TOTAL_POSTS
    for content in contents:
        assert 900 <= len(content) <= 1400
        assert content == sanitize_plain_text(content)
        assert "http" not in content.casefold()
        assert "**" not in content
    directions = {direction for _, direction, _, _ in TEST_POSTS}
    assert len(directions) == 7
    assert any("Сначала" in content for content in contents)
    assert any("Сначала" not in content for content in contents)


def test_channel_payload_is_plain_text_and_disables_link_previews_for_legacy_schedule_slots(tmp_path):
    clock = Clock()
    repository = ContentPublisherStore(tmp_path / "publisher.sqlite", now=clock)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    repository.start_test_schedule(101)
    with repository._connect() as connection:
        connection.execute(
            "UPDATE content_test_schedule_slots SET content=? WHERE slot_index=0",
            ("**Заголовок** • https://example.test/\u200b ➡️ Готово",),
        )

    transport = PublishingTransport()
    assert ContentPublisherBot(repository, {101}, transport).publish_due_test_post()
    payload = [payload for method, payload in transport.calls if method == "sendMessage" and payload["chat_id"] == -100123][0]

    assert payload == {
        "chat_id": -100123,
        "text": "Заголовок Готово",
        "link_preview_options": {"is_disabled": True},
    }
    assert "parse_mode" not in payload
    assert "entities" not in payload


def test_hour_cutoff_completes_without_backlog_burst(tmp_path):
    clock = Clock()
    repository = ContentPublisherStore(tmp_path / "publisher.sqlite", now=clock)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    repository.start_test_schedule(101)
    transport = PublishingTransport()
    bot = ContentPublisherBot(repository, {101}, transport)

    clock.advance(3600)
    assert not bot.publish_due_test_post()
    assert repository.test_schedule().status == "completed"
    assert not [payload for method, payload in transport.calls if method == "sendMessage" and payload.get("chat_id") == -100123]


def test_ambiguous_send_failure_is_not_retried_after_restart(tmp_path):
    clock = Clock()
    database = tmp_path / "publisher.sqlite"
    repository = ContentPublisherStore(database, now=clock)
    repository.bind_channel(101, ChannelCandidate(-100123, "Тестовый канал", None))
    repository.start_test_schedule(101)
    transport = AmbiguousFailureTransport()
    with pytest.raises(TimeoutError, match="outcome unknown"):
        ContentPublisherBot(repository, {101}, transport).publish_due_test_post()

    restarted = ContentPublisherBot(ContentPublisherStore(database, now=clock), {101}, transport)
    assert restarted.store.test_schedule().status == "failed"
    assert not restarted.publish_due_test_post()
    with pytest.raises(ValueError, match="завершилась неопределённо"):
        restarted.store.start_test_schedule(101)
    assert len([payload for method, payload in transport.calls if method == "sendMessage" and payload.get("chat_id") == -100123]) == 1


def test_environment_parses_owner_ids_without_persisting_them(tmp_path, monkeypatch):
    monkeypatch.setenv("METRICHIT_PUBLISHER_BOT_TOKEN", "secret-only-in-process")
    monkeypatch.setenv("METRICHIT_PUBLISHER_OWNER_IDS", "101, 202")
    bot = ContentPublisherBot.from_environment(store(tmp_path))
    assert bot.owner_user_ids == frozenset({101, 202})
    assert "secret-only-in-process" not in (tmp_path / "publisher.sqlite").read_bytes().decode("utf-8", errors="ignore")
