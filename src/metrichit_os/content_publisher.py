"""Local, approval-gated content publisher foundation for MetricHit.

The module owns no Telegram credentials and has no channel publishing method.
It accepts the same narrow ``call(method, payload)`` transport shape as the
existing Telegram bot and stops at ``ready_to_publish``.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from .local_author import AuthorProfile, DeterministicLocalAdapter, LocalPostAuthor, PostKind, PostRequest


ACCESS_DENIED = "Доступ к контент-паблишеру закрыт."


class TelegramTransport(Protocol):
    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]: ...


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
                """
            )

    def _render(self, topic: str, revision_note: str = "") -> tuple[str, str]:
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
            PostKind.PRODUCT, clean_topic, "Разбираем тему коротко и по делу.",
        )).text
        if revision_note:
            content += f"\n\nУчтено при доработке: {revision_note.strip()}"
        image_brief = (
            f"MetricHit, тема «{clean_topic}»: чистая деловая иллюстрация 16:9, "
            "график динамики и интерфейс аналитики без мелкого текста, логотипов третьих лиц и обещаний результата."
        )
        return content, image_brief

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


class ContentPublisherBot:
    """Owner-only Telegram review UI; deliberately incapable of publishing."""

    def __init__(
        self, store: ContentPublisherStore, owner_user_ids: set[int], transport: TelegramTransport
    ):
        if not owner_user_ids:
            raise ValueError("At least one owner user id is required")
        self.store = store
        self.owner_user_ids = frozenset(owner_user_ids)
        self.transport = transport
        self.offset: int | None = None

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
        return handled

    def _authorized(self, user_id: object, chat: object) -> bool:
        return (
            isinstance(user_id, int) and user_id in self.owner_user_ids
            and isinstance(chat, dict) and chat.get("type") == "private" and chat.get("id") == user_id
        )

    def _handle_update(self, update: dict[str, object]) -> bool:
        message = update.get("message")
        if isinstance(message, dict):
            chat, sender, text = message.get("chat"), message.get("from"), message.get("text")
            if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(text, str):
                return False
            chat_id, user_id = chat.get("id"), sender.get("id")
            if not self._authorized(user_id, chat):
                if isinstance(chat_id, int):
                    self.transport.call("sendMessage", {"chat_id": chat_id, "text": ACCESS_DENIED})
                return True
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
            help_text = "Команды: /draft тема, /list, /show ID, /revise ID что изменить"
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
