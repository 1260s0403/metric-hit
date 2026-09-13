"""Offline-first drafting for MetricHit Telegram posts.

This module intentionally has no transport, credentials, network client, or
model runtime.  A future local-model integration only needs to implement
``LocalModelAdapter``; callers keep using ``LocalPostAuthor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Protocol


class PostKind(StrEnum):
    """Publication form, not a promise that every post is an instruction."""

    INFORMATIONAL = "informational"
    INSTRUCTION = "instruction"
    DIAGNOSTIC = "diagnostic"
    EXPLANATORY = "explanatory"
    PRODUCT = "product"
    CHECKLIST = "checklist"
    UPDATE = "update"
    CTA = "cta"


class AuthorError(ValueError):
    """Base error for invalid author input or an invalid model response."""


class FactIntegrityError(AuthorError):
    """A draft did not preserve the supplied product facts verbatim."""


class TelegramFormattingError(AuthorError):
    """A draft cannot be represented as safe plain Telegram text."""


class RevisionError(AuthorError):
    """Revision feedback is unsupported or would alter more than requested."""


class PublicDisclosureError(AuthorError):
    """Public drafts must not disclose the bot's search-result mechanics."""


@dataclass(frozen=True)
class AuthorProfile:
    tone: str
    audience: str
    product_facts: tuple[str, ...]
    constraints: tuple[str, ...]
    default_cta: str
    formatting: str = "plain text"

    def __post_init__(self) -> None:
        for field in ("tone", "audience", "default_cta", "formatting"):
            if not getattr(self, field).strip():
                raise AuthorError(f"{field} must not be empty")
        if not self.product_facts or any(not fact.strip() for fact in self.product_facts):
            raise AuthorError("product_facts must contain non-empty facts")
        if any(not constraint.strip() for constraint in self.constraints):
            raise AuthorError("constraints must not contain empty values")


@dataclass(frozen=True)
class PostRequest:
    kind: PostKind
    topic: str
    opening: str
    cta: str | None = None
    direction: str | None = None

    def __post_init__(self) -> None:
        if not self.topic.strip() or not self.opening.strip():
            raise AuthorError("topic and opening must not be empty")
        if self.cta is not None and not self.cta.strip():
            raise AuthorError("cta must not be blank when supplied")
        if self.direction is not None and not self.direction.strip():
            raise AuthorError("direction must not be blank when supplied")


@dataclass(frozen=True)
class AuthorPrompt:
    profile: AuthorProfile
    request: PostRequest


@dataclass(frozen=True)
class Draft:
    kind: PostKind
    topic: str
    text: str
    facts: tuple[str, ...]
    cta: str
    revision: int = 1


class LocalModelAdapter(Protocol):
    """Replaceable local-model boundary. Implementations must be offline-safe."""

    def generate(self, prompt: AuthorPrompt) -> str: ...


THEMATIC_DIRECTIONS = (
    "ПФ и решения о запуске и использовании",
    "поисковая выдача Яндекса и контекст ранжирования",
    "SEO готовность сайта и страниц, включая техническую и коммерческую релевантность",
    "семантическое ядро, стратегия запросов и интент",
    "региональное таргетирование",
    "аналитика, мониторинг и диагностика",
    "обновления поисковых систем только при наличии фактического источника",
)

_INSTRUCTION_KINDS = {PostKind.INSTRUCTION, PostKind.CHECKLIST}
_DIAGNOSTIC_KINDS = {PostKind.DIAGNOSTIC}

_PROHIBITED_SEARCH_MECHANICS = re.compile(
    r"(?:поисков\w*\s+(?:выдач\w*|результат\w*)|"
    r"открыва\w*[^\n.]{0,80}(?:результат\w*|сайт)|"
    r"целев\w*\s+сайт[^\n.]{0,60}последн\w*|"
    r"не\s+возвращ\w*[^\n.]{0,60}поиск\w*|"
    r"действ\w*\s+внутри\s+сайт\w*)",
    re.IGNORECASE,
)

_URL = re.compile(r"(?i)\b(?:https?://|www\.|t\.me/)[^\s<>()]+")
_HTML_TAG = re.compile(r"<[^>\n]*>")
_HTML_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+);")
_DISALLOWED = re.compile(r"[^A-Za-zА-Яа-яЁё0-9 \n.,;:!?()\-\"']")
MIN_POST_LENGTH = 900
MAX_POST_LENGTH = 1400


def sanitize_plain_text(text: str) -> str:
    """Return the narrow plain-text subset allowed in channel publications.

    URLs, markup, emoji, non-printing Unicode and non-standard symbols are
    removed rather than passed through to Telegram. Newlines remain only as
    visible paragraph breaks.
    """
    value = _URL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    value = re.sub(r"\(\s*\)", "", value)
    value = _HTML_TAG.sub("", value)
    value = _HTML_ENTITY.sub(" ", value)
    value = _DISALLOWED.sub("", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def validate_plain_text(text: str) -> None:
    """Reject text outside the intentionally small plain-text channel subset."""
    if not text.strip():
        raise TelegramFormattingError("draft must not be empty")
    if len(text) > 4096:
        raise TelegramFormattingError("Telegram message exceeds 4096 characters")
    if text != sanitize_plain_text(text):
        raise TelegramFormattingError("draft must use plain text without markup, links, or hidden characters")


def validate_telegram_markdown(text: str) -> None:
    """Compatibility alias for callers that used the previous validator name."""
    validate_plain_text(text)


class DeterministicLocalAdapter:
    """Offline test adapter; it never downloads or invokes a language model."""

    def __init__(self) -> None:
        self.prompts: list[AuthorPrompt] = []

    def generate(self, prompt: AuthorPrompt) -> str:
        self.prompts.append(prompt)
        request, profile = prompt.request, prompt.profile
        facts = "\n".join(profile.product_facts)
        cta = request.cta or profile.default_cta
        lead = f"{request.topic.strip()}\n\n{request.opening.strip()} "
        if request.kind in _INSTRUCTION_KINDS:
            body = (
                "Практический формат уместен, когда нужно подготовить конкретное решение, а не просто описать "
                "ситуацию. Сначала зафиксируйте исходные данные и период, к которому относится наблюдение. Затем "
                "проверьте страницу, группу запросов или настройку, которая действительно участвует в задаче. После "
                "этого сопоставьте изменения с тем, что видит пользователь и поисковая система. Отдельно запишите "
                "вывод и следующий шаг, чтобы не смешивать гипотезу с подтверждённым результатом. Такой порядок "
                "снижает риск делать вывод по одному числу или случайному колебанию."
            )
        elif request.kind in _DIAGNOSTIC_KINDS:
            body = (
                "Диагностика начинается не с универсального рецепта, а с границ наблюдения. Одинаковый симптом может "
                "быть связан со страницей, соответствием интенту, составом запросов, регионом, недавними изменениями "
                "или периодом сравнения. Поэтому полезно отделить то, что известно из данных, от предположения о "
                "причине. Когда сигнал рассматривают в контексте связанных страниц и запросов, видно, где требуется "
                "проверка, а где достаточно продолжить наблюдение. Это делает решение объяснимым и не подменяет анализ "
                "громким выводом."
            )
        elif request.kind == PostKind.EXPLANATORY or request.kind == PostKind.CTA:
            body = (
                "У темы обычно нет одной причины и одного универсального вывода. На результат одновременно влияют "
                "соответствие страницы запросу, качество и полнота содержания, техническая доступность, коммерческие "
                "сигналы и контекст выдачи. Изменение одного показателя само по себе не доказывает, что сработал именно "
                "один фактор. Спокойное объяснение помогает увидеть связь между задачей пользователя, страницей и данными, "
                "а не искать короткий ответ там, где нужен контекст."
            )
        else:
            body = (
                "Это информационная заметка, а не инструкция под видом универсального чек-листа. В SEO и работе с ПФ "
                "важно различать факт, наблюдение и вывод: позиции существуют в контексте запроса, страницы, региона, "
                "конкурентной выдачи и периода измерения. Поэтому одно изменение не стоит описывать как доказанный эффект, "
                "а один показатель не заменяет картину целиком. Полезный пост даёт ориентир, на что смотреть и почему это "
                "имеет значение, без выдуманных кейсов, метрик и обещаний."
            )
        conclusion = (
            "В этой логике нет места для обещаний результата или искусственной уверенности. Материал должен помогать "
            "читателю точнее сформулировать вопрос к данным и к странице. Решение появляется после проверки контекста, "
            "а не вместо неё."
        )
        return f"{lead}\n\n{body}\n\n{conclusion}\n\n{facts}\n\n{cta.strip()}"


class LocalPostAuthor:
    """Creates and revises drafts without knowing a model engine or publisher."""

    def __init__(self, adapter: LocalModelAdapter):
        self._adapter = adapter

    def draft(self, profile: AuthorProfile, request: PostRequest) -> Draft:
        self._reject_public_mechanics(profile, request)
        text = sanitize_plain_text(self._adapter.generate(AuthorPrompt(profile=profile, request=request)))
        facts = tuple(sanitize_plain_text(fact) for fact in profile.product_facts)
        cta = sanitize_plain_text(request.cta or profile.default_cta)
        self._validate(text, facts, cta)
        return Draft(kind=request.kind, topic=sanitize_plain_text(request.topic), text=text, facts=facts, cta=cta)

    def revise(self, draft: Draft, feedback: str) -> Draft:
        """Apply only ``Замени CTA на: ...``; all non-CTA text stays byte-identical."""
        prefix = "Замени CTA на:"
        if not feedback.startswith(prefix):
            raise RevisionError("supported feedback: 'Замени CTA на: <новый CTA>'")
        replacement = sanitize_plain_text(feedback.removeprefix(prefix))
        if not replacement:
            raise RevisionError("replacement CTA must not be empty")
        if draft.text.count(draft.cta) != 1:
            raise RevisionError("draft CTA must occur exactly once")
        text = draft.text.replace(draft.cta, replacement, 1)
        self._validate(text, draft.facts, replacement)
        return Draft(
            kind=draft.kind, topic=draft.topic, text=text, facts=draft.facts,
            cta=replacement, revision=draft.revision + 1,
        )

    @staticmethod
    def _validate(text: str, facts: tuple[str, ...], cta: str) -> None:
        validate_plain_text(text)
        missing = [fact for fact in facts if fact not in text]
        if missing:
            raise FactIntegrityError(f"draft omits supplied facts: {', '.join(missing)}")
        if cta not in text:
            raise FactIntegrityError("draft omits the requested CTA")
        if not MIN_POST_LENGTH <= len(text) <= MAX_POST_LENGTH:
            raise TelegramFormattingError(
                f"draft must contain {MIN_POST_LENGTH}-{MAX_POST_LENGTH} characters"
            )

    @staticmethod
    def _reject_public_mechanics(profile: AuthorProfile, request: PostRequest) -> None:
        public_fields = (request.topic, request.opening, request.cta or "", *profile.product_facts)
        if any(_PROHIBITED_SEARCH_MECHANICS.search(value) for value in public_fields):
            raise PublicDisclosureError("public drafts must not disclose bot search-result mechanics")
