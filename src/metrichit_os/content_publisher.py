"""Local authoring and bounded Telegram publishing for MetricHit.

Credentials are deliberately supplied only at process start through
``METRICHIT_PUBLISHER_BOT_TOKEN``.  They are never persisted, logged, or
accepted through a Telegram message.  The automatic mode is deliberately
limited to one owner-started, one-hour test run.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol
from urllib.request import Request, urlopen

from .local_author import (
    AuthorProfile,
    DeterministicLocalAdapter,
    LocalPostAuthor,
    PostKind,
    PostRequest,
    sanitize_plain_text,
)


ACCESS_DENIED = "Доступ к контент-паблишеру закрыт."
TEST_INTERVAL_SECONDS = 180
TEST_TOTAL_POSTS = 20
TEST_DURATION_SECONDS = 3600
TEST_POSTS = (
    ("Что проверить на сайте до запуска SEO-теста", "До старта часто смотрят только на список запросов и пропускают состояние самих страниц."),
    ("Почему важно зафиксировать позиции до начала работ", "Без исходной точки даже полезная динамика превращается в спор о том, что было раньше."),
    ("Как выбрать страницы для первого теста", "Первый запуск разумнее начинать не со всего сайта, а со страниц с понятной задачей."),
    ("Чем тестовый запуск отличается от постоянной работы", "Тест нужен, чтобы проверить гипотезу в ограниченном контуре, а не заменить регулярную работу с сайтом."),
    ("Какие изменения сайта мешают оценить результат", "Одновременная смена текстов, структуры и настроек не даёт понять, что именно изменило картину."),
    ("Почему техническое SEO остаётся обязательным", "Если страница плохо доступна поиску или работает нестабильно, сначала нужно устранить эту причину."),
    ("Как определить период проверки результата", "Слишком короткий период даёт случайный срез, а слишком длинный скрывает момент, когда появились изменения."),
    ("Какие данные сохранить перед стартом", "Скриншот одной позиции не заменяет набор данных, по которому можно вернуться к исходной ситуации."),
    ("Почему не стоит менять несколько факторов одновременно", "Когда в один день меняют несколько условий, вывод о следующем шаге становится предположением."),
    ("Как оценивать динамику позиций без поспешных выводов", "Одна просадка или один рост не описывают состояние группы запросов и страницы целиком."),
    ("Что делать, если у страницы несколько целевых запросов", "Разные запросы могут вести к одной странице с разным намерением пользователя, и это нужно увидеть заранее."),
    ("Как проверить готовность посадочной страницы", "До любого теста стоит убедиться, что страница отвечает на запрос, а не только содержит нужные слова."),
    ("Почему качество контента влияет на интерпретацию теста", "Слабый или неясный контент мешает отделить проблему страницы от остальных факторов."),
    ("Какие страницы не стоит брать в первый запуск", "Для первого шага не подходят страницы с незавершённой структурой, частыми правками или неясной ролью."),
    ("Как вести журнал изменений во время теста", "Память команды быстро смешивает даты и причины, поэтому изменения лучше фиксировать в моменте."),
    ("Почему стабильность сайта важна для чистого эксперимента", "Нестабильная доступность и постоянные релизы создают фон, на котором нельзя уверенно читать результат."),
    ("Как сравнивать результаты до и после запуска", "Сравнение имеет смысл только при одинаковых группах, страницах и понятном периоде наблюдения."),
    ("Какие метрики смотреть вместе с позициями", "Позиции полезны в контексте страниц, групп запросов и изменений на сайте, а не как одиночное число."),
    ("Когда тест стоит остановить досрочно", "Остановить тест стоит не из-за эмоции от одного дня, а когда исходные условия перестали быть сопоставимыми."),
    ("Как подвести итоги тестового периода", "Итог начинается не с громкого вывода, а с сопоставления исходных данных, действий и наблюдений."),
)


class TelegramTransport(Protocol):
    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]: ...


def channel_message_payload(channel_id: int, content: str) -> dict[str, object]:
    """Build an unformatted channel message, including for legacy stored slots."""
    text = sanitize_plain_text(content)
    if not text:
        raise ValueError("Пост не содержит допустимого обычного текста.")
    return {
        "chat_id": channel_id,
        "text": text,
        "link_preview_options": {"is_disabled": True},
    }


class UrllibTelegramTransport:
    """Small Telegram API boundary; construction performs no network I/O."""

    def __init__(self, token: str):
        if not token.strip():
            raise ValueError("METRICHIT_PUBLISHER_BOT_TOKEN is required")
        self._base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            self._base_url + method,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=35) as response:  # noqa: S310 - fixed Telegram API URL
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed")
        return result


@dataclass(frozen=True)
class Draft:
    job_id: str
    version: int
    topic: str
    content: str
    image_brief: str
    image_artifact: str
    content_hash: str
    status: str


@dataclass(frozen=True)
class Decision:
    accepted: bool
    status: str
    reason: str


@dataclass(frozen=True)
class ChannelCandidate:
    channel_id: int
    title: str
    username: str | None


@dataclass(frozen=True)
class ChannelBinding:
    channel_id: int
    title: str
    username: str | None


@dataclass(frozen=True)
class TestSchedule:
    schedule_id: str
    owner_user_id: int
    channel_id: int
    status: str
    started_at: datetime
    ends_at: datetime
    published_slots: int


class ContentPublisherStore:
    """Private SQLite registry for jobs, immutable draft versions and decisions."""

    def __init__(self, database_path: str | Path, now: Callable[[], datetime] | None = None,
                 author: LocalPostAuthor | None = None):
        self.database_path = str(database_path)
        self._now = now or (lambda: datetime.now(UTC))
        self.author = author or LocalPostAuthor(DeterministicLocalAdapter())
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _timestamp(self) -> str:
        return self._now().astimezone(UTC).isoformat()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_jobs (
                    id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    channel_key TEXT NOT NULL CHECK(channel_key = 'metrichit'),
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'in_review', 'revision_requested', 'rejected', 'ready_to_publish'
                    )),
                    current_version INTEGER NOT NULL CHECK(current_version > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_drafts (
                    job_id TEXT NOT NULL REFERENCES content_jobs(id),
                    version INTEGER NOT NULL CHECK(version > 0),
                    content TEXT NOT NULL,
                    image_brief TEXT NOT NULL,
                    image_artifact TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    revision_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, version)
                );
                CREATE TABLE IF NOT EXISTS content_decisions (
                    id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES content_jobs(id),
                    version INTEGER NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('approve', 'revise', 'reject')),
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_channel_candidates (
                    owner_user_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    username TEXT,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_channel_binding (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    username TEXT,
                    bound_by_user_id INTEGER NOT NULL,
                    bound_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_owner_binding (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    owner_user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    verified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_publications (
                    job_id TEXT NOT NULL REFERENCES content_jobs(id),
                    version INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    published_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, version)
                );
                CREATE TABLE IF NOT EXISTS content_test_schedule (
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
                CREATE TABLE IF NOT EXISTS content_test_schedule_slots (
                    schedule_id TEXT NOT NULL,
                    slot_index INTEGER NOT NULL CHECK(slot_index >= 0 AND slot_index < 20),
                    due_at TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'sending', 'published', 'skipped')),
                    telegram_message_id INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(schedule_id, slot_index)
                );
                """
            )

    def _render(self, topic: str, revision_note: str = "", opening: str | None = None) -> tuple[str, str]:
        clean_topic = " ".join(topic.split())
        if not clean_topic:
            raise ValueError("Тема не может быть пустой.")
        profile = AuthorProfile(
            tone="прямой, спокойный, профессиональный", audience="владельцы сайтов и SEO-специалисты",
            product_facts=("MetricHit помогает усиливать подготовленный сайт и не заменяет техническое SEO.",),
            constraints=("Не раскрывать поисковую механику бота.",),
            default_cta="Перед запуском зафиксируйте текущие позиции и период проверки.",
        )
        content = self.author.draft(profile, PostRequest(
            PostKind.PRODUCT, clean_topic, opening or "Разбираем тему спокойно, на конкретной ситуации и без общих обещаний.",
        )).text
        if revision_note:
            content += f"\n\nУчтено при доработке: {revision_note.strip()}"
        image_brief = (
            f"MetricHit, тема {clean_topic}: квадратная JPEG карточка с крупным заголовком из 3 6 слов, "
            "читаемым на мобильном экране. Премиальная многослойная 3D композиция на полностью непрозрачном "
            "графитовом почти чёрном фоне, со стеклянными панелями, глубиной и спокойным дорогим светом. "
            "Палитра: графит, сдержанный cyan и заметный, но не кричащий тёплый оранжевый акцент. Никакого "
            "размытия, тумана, белых или мутных краёв, логотипов, URL, мелкого текста, стрелок, графиков, "
            "скриншотов, интерфейсов, людей и водяных знаков."
        )
        return sanitize_plain_text(content), image_brief

    @staticmethod
    def _hash(content: str, image_brief: str) -> str:
        return hashlib.sha256(f"{content}\0{image_brief}".encode("utf-8")).hexdigest()

    def create_job(self, owner_user_id: int, topic: str) -> Draft:
        content, image_brief = self._render(topic)
        job_id = uuid.uuid4().hex[:16]
        version = 1
        artifact = f"placeholder://metrichit/{job_id}/v{version}"
        timestamp = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO content_jobs VALUES (?, ?, 'metrichit', ?, 'in_review', ?, ?, ?)",
                (job_id, owner_user_id, " ".join(topic.split()), version, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO content_drafts VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (job_id, version, content, image_brief, artifact, self._hash(content, image_brief), timestamp),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> Draft:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT j.id, j.current_version, j.topic, j.status, d.content,
                          d.image_brief, d.image_artifact, d.content_hash
                   FROM content_jobs j JOIN content_drafts d
                     ON d.job_id = j.id AND d.version = j.current_version
                   WHERE j.id = ?""",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return Draft(
            job_id=str(row["id"]), version=int(row["current_version"]), topic=str(row["topic"]),
            content=str(row["content"]), image_brief=str(row["image_brief"]),
            image_artifact=str(row["image_artifact"]), content_hash=str(row["content_hash"]),
            status=str(row["status"]),
        )

    def list_jobs(self, owner_user_id: int) -> list[Draft]:
        with self._connect() as connection:
            ids = connection.execute(
                "SELECT id FROM content_jobs WHERE owner_user_id = ? ORDER BY created_at DESC, id DESC",
                (owner_user_id,),
            ).fetchall()
        return [self.get(str(row["id"])) for row in ids]

    def request_revision(self, job_id: str, version: int, actor_user_id: int) -> Decision:
        return self._transition(job_id, version, actor_user_id, "revise", "revision_requested")

    def reject(self, job_id: str, version: int, actor_user_id: int) -> Decision:
        return self._transition(job_id, version, actor_user_id, "reject", "rejected")

    def approve(self, job_id: str, version: int, actor_user_id: int) -> Decision:
        return self._transition(job_id, version, actor_user_id, "approve", "ready_to_publish")

    def _transition(
        self, job_id: str, version: int, actor_user_id: int, action: str, target: str
    ) -> Decision:
        timestamp = self._timestamp()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, current_version, status FROM content_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return Decision(False, "missing", "Черновик не найден.")
            if int(row["owner_user_id"]) != actor_user_id:
                return Decision(False, str(row["status"]), ACCESS_DENIED)
            if int(row["current_version"]) != version:
                return Decision(False, str(row["status"]), "Эта кнопка относится к устаревшей версии.")
            if str(row["status"]) != "in_review":
                return Decision(False, str(row["status"]), "Решение по этой версии уже принято.")
            changed = connection.execute(
                """UPDATE content_jobs SET status = ?, updated_at = ?
                   WHERE id = ? AND current_version = ? AND status = 'in_review'""",
                (target, timestamp, job_id, version),
            ).rowcount
            if changed != 1:
                return Decision(False, str(row["status"]), "Состояние черновика изменилось.")
            connection.execute(
                "INSERT INTO content_decisions(job_id, version, actor_user_id, action, outcome, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, version, actor_user_id, action, target, timestamp),
            )
        return Decision(True, target, "Решение сохранено.")

    def revise(self, job_id: str, actor_user_id: int, note: str) -> Draft:
        clean_note = " ".join(note.split())
        if not clean_note:
            raise ValueError("Укажите, что нужно изменить.")
        timestamp = self._timestamp()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, topic, status, current_version FROM content_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if int(row["owner_user_id"]) != actor_user_id:
                raise PermissionError(ACCESS_DENIED)
            if str(row["status"]) != "revision_requested":
                raise ValueError("Сначала нажмите «Доработать» у актуальной версии.")
            version = int(row["current_version"]) + 1
            content, image_brief = self._render(str(row["topic"]), clean_note)
            artifact = f"placeholder://metrichit/{job_id}/v{version}"
            connection.execute(
                "INSERT INTO content_drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, version, content, image_brief, artifact, self._hash(content, image_brief), clean_note, timestamp),
            )
            connection.execute(
                "UPDATE content_jobs SET status = 'in_review', current_version = ?, updated_at = ? WHERE id = ?",
                (version, timestamp, job_id),
            )
        return self.get(job_id)

    def remember_channel_candidate(self, owner_user_id: int, candidate: ChannelCandidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO content_channel_candidates(owner_user_id, channel_id, title, username, observed_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(owner_user_id) DO UPDATE SET channel_id=excluded.channel_id,
                     title=excluded.title, username=excluded.username, observed_at=excluded.observed_at""",
                (owner_user_id, candidate.channel_id, candidate.title, candidate.username, self._timestamp()),
            )

    def bind_channel(self, owner_user_id: int, candidate: ChannelCandidate) -> ChannelBinding:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT channel_id FROM content_channel_binding WHERE singleton = 1"
            ).fetchone()
            if existing is not None and int(existing["channel_id"]) != candidate.channel_id:
                raise ValueError("Тестовый канал уже подключён; смена канала заблокирована.")
            connection.execute(
                """INSERT INTO content_channel_binding(singleton, channel_id, title, username, bound_by_user_id, bound_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO NOTHING""",
                (candidate.channel_id, candidate.title, candidate.username, owner_user_id, self._timestamp()),
            )
        return self.channel_binding()

    def bind_verified_owner_channel(
        self, owner_user_id: int, candidate: ChannelCandidate
    ) -> ChannelBinding:
        """Atomically persist the first Telegram-verified owner and exact channel."""
        timestamp = self._timestamp()
        with self._connect() as connection:
            owner = connection.execute(
                "SELECT owner_user_id, channel_id FROM content_owner_binding WHERE singleton = 1"
            ).fetchone()
            if owner is not None and (
                int(owner["owner_user_id"]) != owner_user_id
                or int(owner["channel_id"]) != candidate.channel_id
            ):
                raise ValueError("Владелец и тестовый канал уже привязаны.")
            channel = connection.execute(
                "SELECT channel_id FROM content_channel_binding WHERE singleton = 1"
            ).fetchone()
            if channel is not None and int(channel["channel_id"]) != candidate.channel_id:
                raise ValueError("Тестовый канал уже подключён; смена канала заблокирована.")
            connection.execute(
                """INSERT INTO content_channel_binding
                   (singleton, channel_id, title, username, bound_by_user_id, bound_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO NOTHING""",
                (candidate.channel_id, candidate.title, candidate.username, owner_user_id, timestamp),
            )
            connection.execute(
                """INSERT INTO content_owner_binding
                   (singleton, owner_user_id, channel_id, verified_at)
                   VALUES (1, ?, ?, ?)
                   ON CONFLICT(singleton) DO NOTHING""",
                (owner_user_id, candidate.channel_id, timestamp),
            )
        return self.channel_binding()

    def verified_owner_user_ids(self) -> frozenset[int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id FROM content_owner_binding WHERE singleton = 1"
            ).fetchone()
        return frozenset() if row is None else frozenset({int(row["owner_user_id"])})

    def bind_latest_channel_candidate(self, owner_user_id: int) -> ChannelBinding:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT channel_id, title, username FROM content_channel_candidates WHERE owner_user_id = ?",
                (owner_user_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Сначала перешлите боту сообщение из нужного канала.")
        return self.bind_channel(owner_user_id, ChannelCandidate(
            int(row["channel_id"]), str(row["title"]), row["username"],
        ))

    def channel_binding(self) -> ChannelBinding:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT channel_id, title, username FROM content_channel_binding WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise ValueError("Тестовый канал ещё не привязан.")
        return ChannelBinding(int(row["channel_id"]), str(row["title"]), row["username"])

    def record_publication(self, job_id: str, version: int, actor_user_id: int,
                           channel_id: int, telegram_message_id: int) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, current_version, status FROM content_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if int(row["owner_user_id"]) != actor_user_id:
                raise PermissionError(ACCESS_DENIED)
            if int(row["current_version"]) != version or str(row["status"]) != "ready_to_publish":
                raise ValueError("К публикации доступна только одобренная актуальная версия.")
            connection.execute(
                "INSERT INTO content_publications VALUES (?, ?, ?, ?, ?)",
                (job_id, version, channel_id, telegram_message_id, self._timestamp()),
            )

    def is_published(self, job_id: str, version: int) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM content_publications WHERE job_id = ? AND version = ?", (job_id, version)
            ).fetchone() is not None

    def start_test_schedule(self, owner_user_id: int) -> TestSchedule:
        binding = self.channel_binding()
        started_at = self._now().astimezone(UTC)
        ends_at = started_at + timedelta(seconds=TEST_DURATION_SECONDS)
        schedule_id = uuid.uuid4().hex
        timestamp = started_at.isoformat()
        with self._connect() as connection:
            existing = connection.execute("SELECT status FROM content_test_schedule WHERE singleton = 1").fetchone()
            if existing is not None:
                raise ValueError("Тестовое расписание уже создавалось; повторный запуск заблокирован.")
            connection.execute(
                "INSERT INTO content_test_schedule VALUES (1, ?, ?, ?, 'active', ?, ?, NULL, ?)",
                (schedule_id, owner_user_id, binding.channel_id, timestamp, ends_at.isoformat(), timestamp),
            )
            for slot_index, (topic, opening) in enumerate(TEST_POSTS):
                content, image_brief = self._render(topic, opening=opening)
                due_at = started_at + timedelta(seconds=slot_index * TEST_INTERVAL_SECONDS)
                connection.execute(
                    """INSERT INTO content_test_schedule_slots
                       (schedule_id, slot_index, due_at, content, content_hash, status, telegram_message_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?)""",
                    (schedule_id, slot_index, due_at.isoformat(), content,
                     self._hash(content, image_brief), timestamp),
                )
        return self.test_schedule()

    def test_schedule(self) -> TestSchedule:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT s.schedule_id, s.owner_user_id, s.channel_id, s.status, s.started_at, s.ends_at,
                          COUNT(sl.slot_index) FILTER (WHERE sl.status = 'published') AS published_slots
                   FROM content_test_schedule s
                   LEFT JOIN content_test_schedule_slots sl ON sl.schedule_id = s.schedule_id
                   WHERE s.singleton = 1 GROUP BY s.schedule_id"""
            ).fetchone()
        if row is None:
            raise ValueError("Тестовое расписание ещё не запущено.")
        return TestSchedule(
            schedule_id=str(row["schedule_id"]), owner_user_id=int(row["owner_user_id"]),
            channel_id=int(row["channel_id"]), status=str(row["status"]),
            started_at=datetime.fromisoformat(str(row["started_at"])),
            ends_at=datetime.fromisoformat(str(row["ends_at"])),
            published_slots=int(row["published_slots"]),
        )

    def stop_test_schedule(self, owner_user_id: int) -> TestSchedule:
        timestamp = self._timestamp()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, status FROM content_test_schedule WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise ValueError("Активного тестового расписания нет.")
            if int(row["owner_user_id"]) != owner_user_id:
                raise PermissionError(ACCESS_DENIED)
            if str(row["status"]) != "active":
                raise ValueError("Тестовое расписание уже остановлено.")
            connection.execute(
                """UPDATE content_test_schedule SET status='stopped', stopped_at=?, updated_at=?
                   WHERE singleton=1 AND status='active'""", (timestamp, timestamp),
            )
            connection.execute(
                """UPDATE content_test_schedule_slots SET status='skipped', updated_at=?
                   WHERE schedule_id=(SELECT schedule_id FROM content_test_schedule WHERE singleton=1)
                     AND status='pending'""", (timestamp,),
            )
        return self.test_schedule()

    def claim_due_test_slot(self) -> tuple[TestSchedule, int, str] | None:
        """Durably claim at most one due slot before any external send."""
        current = self._now().astimezone(UTC)
        timestamp = current.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            schedule = connection.execute(
                "SELECT * FROM content_test_schedule WHERE singleton=1"
            ).fetchone()
            if schedule is None or str(schedule["status"]) != "active":
                return None
            schedule_id = str(schedule["schedule_id"])
            if current >= datetime.fromisoformat(str(schedule["ends_at"])):
                connection.execute(
                    "UPDATE content_test_schedule SET status='completed', updated_at=? WHERE singleton=1",
                    (timestamp,),
                )
                connection.execute(
                    "UPDATE content_test_schedule_slots SET status='skipped', updated_at=? WHERE schedule_id=? AND status='pending'",
                    (timestamp, schedule_id),
                )
                return None
            due = connection.execute(
                """SELECT slot_index, content FROM content_test_schedule_slots
                   WHERE schedule_id=? AND status='pending' AND due_at<=?
                   ORDER BY slot_index""", (schedule_id, timestamp),
            ).fetchall()
            if not due:
                return None
            chosen = due[-1]
            if len(due) > 1:
                connection.executemany(
                    "UPDATE content_test_schedule_slots SET status='skipped', updated_at=? WHERE schedule_id=? AND slot_index=?",
                    [(timestamp, schedule_id, int(row["slot_index"])) for row in due[:-1]],
                )
            connection.execute(
                """UPDATE content_test_schedule_slots SET status='sending', updated_at=?
                   WHERE schedule_id=? AND slot_index=? AND status='pending'""",
                (timestamp, schedule_id, int(chosen["slot_index"])),
            )
        return self.test_schedule(), int(chosen["slot_index"]), str(chosen["content"])

    def finish_test_slot(self, schedule_id: str, slot_index: int, telegram_message_id: int) -> TestSchedule:
        timestamp = self._timestamp()
        with self._connect() as connection:
            changed = connection.execute(
                """UPDATE content_test_schedule_slots SET status='published', telegram_message_id=?, updated_at=?
                   WHERE schedule_id=? AND slot_index=? AND status='sending'""",
                (telegram_message_id, timestamp, schedule_id, slot_index),
            ).rowcount
            if changed != 1:
                raise ValueError("Слот публикации уже обработан.")
            remaining = connection.execute(
                "SELECT COUNT(*) FROM content_test_schedule_slots WHERE schedule_id=? AND status='pending'",
                (schedule_id,),
            ).fetchone()[0]
            if remaining == 0:
                connection.execute(
                    "UPDATE content_test_schedule SET status='completed', updated_at=? WHERE schedule_id=? AND status='active'",
                    (timestamp, schedule_id),
                )
        return self.test_schedule()

    def fail_test_slot(self, schedule_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_test_schedule SET status='failed', updated_at=? WHERE schedule_id=? AND status='active'",
                (self._timestamp(), schedule_id),
            )


class ContentPublisherBot:
    """Owner-only control UI for manual drafts and one bounded automatic test."""

    def __init__(
        self, store: ContentPublisherStore, owner_user_ids: set[int] | None, transport: TelegramTransport
    ):
        self.store = store
        self.owner_user_ids = frozenset(owner_user_ids or ())
        self.transport = transport
        self.offset: int | None = None

    @classmethod
    def from_environment(
        cls, store: ContentPublisherStore, owner_user_ids: set[int] | None = None
    ) -> "ContentPublisherBot":
        """Build the live adapter without storing its secret or contacting Telegram."""
        if owner_user_ids is None:
            raw_owner_ids = os.environ.get("METRICHIT_PUBLISHER_OWNER_IDS", "")
            try:
                owner_user_ids = {int(value.strip()) for value in raw_owner_ids.split(",") if value.strip()}
            except ValueError as error:
                raise ValueError("METRICHIT_PUBLISHER_OWNER_IDS must contain numeric Telegram user ids") from error
        return cls(store, owner_user_ids, UrllibTelegramTransport(os.environ.get("METRICHIT_PUBLISHER_BOT_TOKEN", "")))

    @staticmethod
    def review_keyboard(draft: Draft) -> dict[str, object]:
        suffix = f"{draft.job_id}:{draft.version}"
        return {"inline_keyboard": [[
            {"text": "✅ Одобрить", "callback_data": f"cp:a:{suffix}"},
            {"text": "✏️ Доработать", "callback_data": f"cp:v:{suffix}"},
            {"text": "❌ Отклонить", "callback_data": f"cp:r:{suffix}"},
        ]]}

    @staticmethod
    def preview(draft: Draft) -> str:
        return (
            f"Черновик {draft.job_id} · версия {draft.version}\nСтатус: {draft.status}\n\n"
            f"{draft.content}\n\nКартинка — бриф:\n{draft.image_brief}\n"
            f"Артефакт: {draft.image_artifact}"
        )

    def poll_once(self, timeout: int = 0) -> int:
        payload: dict[str, object] = {"timeout": timeout}
        if self.offset is not None:
            payload["offset"] = self.offset
        response = self.transport.call("getUpdates", payload)
        updates = response.get("result", []) if response.get("ok") else []
        handled = 0
        for update in updates if isinstance(updates, list) else []:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self.offset = update_id + 1
            if self._handle_update(update):
                handled += 1
        self.publish_due_test_post()
        return handled

    def run_forever(self, timeout: int = 5) -> None:
        """Keep polling while the local process is running."""
        while True:
            self.poll_once(timeout=timeout)

    def publish_due_test_post(self) -> bool:
        claimed = self.store.claim_due_test_slot()
        if claimed is None:
            return False
        schedule, slot_index, content = claimed
        try:
            response = self.transport.call("sendMessage", channel_message_payload(schedule.channel_id, content))
            result = response.get("result")
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if not isinstance(message_id, int):
                raise RuntimeError("Telegram не вернул идентификатор опубликованного сообщения.")
            finished = self.store.finish_test_slot(schedule.schedule_id, slot_index, message_id)
        except Exception:
            self.store.fail_test_slot(schedule.schedule_id)
            raise
        if finished.status == "completed":
            self.transport.call("sendMessage", {
                "chat_id": schedule.owner_user_id,
                "text": f"Тест завершён автоматически. Опубликовано: {finished.published_slots}.",
            })
        return True

    def _authorized(self, user_id: object, chat: object) -> bool:
        active_owner_ids = self.owner_user_ids or self.store.verified_owner_user_ids()
        return (
            isinstance(user_id, int) and user_id in active_owner_ids
            and isinstance(chat, dict) and chat.get("type") == "private" and chat.get("id") == user_id
        )

    @staticmethod
    def _private_sender(user_id: object, chat: object) -> bool:
        return (
            isinstance(user_id, int) and isinstance(chat, dict)
            and chat.get("type") == "private" and chat.get("id") == user_id
        )

    def _try_bind_verified_owner(
        self, user_id: object, chat: object, message: dict[str, object]
    ) -> bool:
        """Bootstrap only from a private channel forward whose sender is its admin."""
        if self.owner_user_ids or self.store.verified_owner_user_ids():
            return False
        candidate = self._forwarded_channel(message)
        if not self._private_sender(user_id, chat) or candidate is None:
            return False
        try:
            response = self.transport.call("getChatMember", {
                "chat_id": candidate.channel_id, "user_id": int(user_id),
            })
            member = response.get("result") if response.get("ok") is True else None
            status = member.get("status") if isinstance(member, dict) else None
            if status not in {"administrator", "creator", "owner"}:
                return False
            binding = self.store.bind_verified_owner_channel(int(user_id), candidate)
        except Exception:
            return False
        self.transport.call("sendMessage", {
            "chat_id": int(user_id),
            "text": f"Владелец и тестовый канал подтверждены: {binding.title}. Для запуска отправьте /start_test.",
        })
        return True

    def _handle_update(self, update: dict[str, object]) -> bool:
        message = update.get("message")
        if isinstance(message, dict):
            chat, sender, text = message.get("chat"), message.get("from"), message.get("text")
            if not isinstance(chat, dict) or not isinstance(sender, dict):
                return False
            chat_id, user_id = chat.get("id"), sender.get("id")
            if not self._authorized(user_id, chat):
                if self._try_bind_verified_owner(user_id, chat, message):
                    return True
                if isinstance(chat_id, int):
                    self.transport.call("sendMessage", {"chat_id": chat_id, "text": ACCESS_DENIED})
                return True
            candidate = self._forwarded_channel(message)
            if candidate is not None:
                self.store.remember_channel_candidate(int(user_id), candidate)
                binding = self.store.bind_channel(int(user_id), candidate)
                self.transport.call("sendMessage", {
                    "chat_id": int(chat_id),
                    "text": f"Тестовый канал подключён: {binding.title}. Для запуска отправьте /start_test.",
                })
                return True
            if not isinstance(text, str):
                return False
            self._handle_text(int(chat_id), int(user_id), text)
            return True
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            sender, callback_message = callback.get("from"), callback.get("message")
            chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
            user_id = sender.get("id") if isinstance(sender, dict) else None
            callback_id = callback.get("id")
            if not self._authorized(user_id, chat):
                if isinstance(callback_id, str):
                    self._answer(callback_id, ACCESS_DENIED, alert=True)
                return True
            self._handle_callback(str(callback_id), int(user_id), str(callback.get("data", "")))
            return True
        return False

    def _handle_text(self, chat_id: int, user_id: int, text: str) -> None:
        command, _, argument = text.strip().partition(" ")
        try:
            if command == "/draft":
                draft = self.store.create_job(user_id, argument)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": self.preview(draft),
                    "reply_markup": self.review_keyboard(draft),
                })
                return
            if command == "/show":
                draft = self.store.get(argument.strip())
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": self.preview(draft),
                    "reply_markup": self.review_keyboard(draft) if draft.status == "in_review" else {"inline_keyboard": []},
                })
                return
            if command == "/revise":
                job_id, separator, note = argument.partition(" ")
                if not separator:
                    raise ValueError("Формат: /revise ID что изменить")
                draft = self.store.revise(job_id, user_id, note)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": self.preview(draft),
                    "reply_markup": self.review_keyboard(draft),
                })
                return
            if command == "/list":
                jobs = self.store.list_jobs(user_id)
                body = "\n".join(f"{item.job_id} · v{item.version} · {item.status} · {item.topic}" for item in jobs)
                self.transport.call("sendMessage", {"chat_id": chat_id, "text": body or "Черновиков пока нет."})
                return
            if command == "/bind":
                binding = self.store.bind_latest_channel_candidate(user_id)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": f"Привязан канал: {binding.title}.",
                })
                return
            if command == "/start_test":
                self.store.start_test_schedule(user_id)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "Тест запущен: 20 постов, по одному каждые 3 минуты. "
                        "Через час расписание остановится автоматически. Команда остановки: /stop"
                    ),
                })
                return
            if command == "/stop":
                schedule = self.store.stop_test_schedule(user_id)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"Расписание остановлено. Опубликовано: {schedule.published_slots}.",
                })
                return
            if command == "/status":
                schedule = self.store.test_schedule()
                self.transport.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"Тест: {schedule.status}. Опубликовано: {schedule.published_slots} из {TEST_TOTAL_POSTS}.",
                })
                return
            if command == "/publish":
                draft = self.store.get(argument.strip())
                binding = self.store.channel_binding()
                if draft.status != "ready_to_publish":
                    raise ValueError("Сначала явно одобрите актуальную версию черновика.")
                if self.store.is_published(draft.job_id, draft.version):
                    raise ValueError("Эта версия уже опубликована.")
                response = self.transport.call(
                    "sendMessage", channel_message_payload(binding.channel_id, draft.content)
                )
                result = response.get("result")
                message_id = result.get("message_id") if isinstance(result, dict) else None
                if not isinstance(message_id, int):
                    raise RuntimeError("Telegram не вернул идентификатор опубликованного сообщения.")
                self.store.record_publication(draft.job_id, draft.version, user_id, binding.channel_id, message_id)
                self.transport.call("sendMessage", {"chat_id": chat_id, "text": "Опубликовано в привязанном канале."})
                return
            help_text = "Команды теста: /start_test, /status, /stop"
            self.transport.call("sendMessage", {"chat_id": chat_id, "text": help_text})
        except (KeyError, ValueError, PermissionError) as error:
            self.transport.call("sendMessage", {"chat_id": chat_id, "text": f"Ошибка: {error}"})

    def _handle_callback(self, callback_id: str, user_id: int, data: str) -> None:
        parts = data.split(":")
        if len(parts) != 4 or parts[0] != "cp" or parts[1] not in {"a", "v", "r"}:
            self._answer(callback_id, "Неизвестное действие.", alert=True)
            return
        action, job_id = parts[1], parts[2]
        try:
            version = int(parts[3])
        except ValueError:
            self._answer(callback_id, "Некорректная версия.", alert=True)
            return
        if action == "a":
            decision = self.store.approve(job_id, version, user_id)
            message = "Одобрено. Версия готова к публикации, но не опубликована." if decision.accepted else decision.reason
        elif action == "v":
            decision = self.store.request_revision(job_id, version, user_id)
            message = f"{decision.reason} Отправьте /revise {job_id} что изменить" if decision.accepted else decision.reason
        else:
            decision = self.store.reject(job_id, version, user_id)
            message = "Черновик отклонён." if decision.accepted else decision.reason
        self._answer(callback_id, message, alert=not decision.accepted)

    def _answer(self, callback_id: str, text: str, *, alert: bool = False) -> None:
        self.transport.call("answerCallbackQuery", {
            "callback_query_id": callback_id, "text": text, "show_alert": alert,
        })

    @staticmethod
    def _forwarded_channel(message: dict[str, object]) -> ChannelCandidate | None:
        """Extract only a channel source from a private forwarded Telegram update."""
        origin = message.get("forward_origin")
        channel = origin.get("chat") if isinstance(origin, dict) and origin.get("type") == "channel" else None
        if not isinstance(channel, dict):
            channel = message.get("forward_from_chat")
        if not isinstance(channel, dict):
            return None
        channel_id, title, username = channel.get("id"), channel.get("title"), channel.get("username")
        if not isinstance(channel_id, int) or not isinstance(title, str) or not title.strip():
            return None
        return ChannelCandidate(channel_id, title.strip(), username if isinstance(username, str) else None)


def main() -> None:
    """Run the dedicated publisher bot from environment-only configuration."""
    database_path = Path(os.environ.get("METRICHIT_PUBLISHER_DB", "data/content-publisher.sqlite"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    ContentPublisherBot.from_environment(ContentPublisherStore(database_path)).run_forever()


if __name__ == "__main__":
    main()
