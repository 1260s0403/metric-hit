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
    default_cta: str = ""
    formatting: str = "plain text"

    def __post_init__(self) -> None:
        for field in ("tone", "audience", "formatting"):
            if not getattr(self, field).strip():
                raise AuthorError(f"{field} must not be empty")
        if any(not fact.strip() for fact in self.product_facts):
            raise AuthorError("product_facts must not contain empty facts")
        if any(not constraint.strip() for constraint in self.constraints):
            raise AuthorError("constraints must not contain empty values")


@dataclass(frozen=True)
class PostRequest:
    kind: PostKind
    topic: str
    opening: str
    cta: str | None = None
    direction: str | None = None
    source_notes: str | None = None
    conclusion: str | None = None

    def __post_init__(self) -> None:
        if not self.topic.strip() or not self.opening.strip():
            raise AuthorError("topic and opening must not be empty")
        if self.cta is not None and not self.cta.strip():
            raise AuthorError("cta must not be blank when supplied")
        if self.direction is not None and not self.direction.strip():
            raise AuthorError("direction must not be blank when supplied")
        if self.source_notes is not None and not self.source_notes.strip():
            raise AuthorError("source_notes must not be blank when supplied")
        if self.conclusion is not None and not self.conclusion.strip():
            raise AuthorError("conclusion must not be blank when supplied")


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

CANONICAL_FOOTER = (
    "**📢 Основной канал MetricHit: https://t.me/mtr_hit**\n"
    "\n"
    "🌐 Сайт MetricHit: https://go.mtrhit.ru/\n"
    "💬 Поддержка в Telegram: https://t.me/Metric_Hit"
)
CANONICAL_URLS = (
    "https://t.me/mtr_hit",
    "https://go.mtrhit.ru/",
    "https://t.me/Metric_Hit",
)
_CANONICAL_URL = re.compile(
    r"(?<![A-Za-z0-9_./-])(" + "|".join(re.escape(url) for url in CANONICAL_URLS) + r")(?![A-Za-z0-9_./-])"
)
_CANONICAL_FOOTER = re.compile(re.escape(CANONICAL_FOOTER))
_URL = re.compile(r"(?i)\b(?:https?://|www\.|t\.me/)[^\s<>()]+")
_HTML_TAG = re.compile(r"<[^>\n]*>")
_HTML_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+);")
_DISALLOWED = re.compile(r"[^A-Za-zА-Яа-яЁё0-9 \n.,;:!?()\-\"']")
MIN_POST_LENGTH = 600
MAX_POST_LENGTH = 750
_FORBIDDEN_META_PHRASES = (
    "практический формат", "материал должен помогать", "в этой логике", "здесь важно",
)
_DECORATIVE_LIST_LINE = re.compile(r"(?m)^\s*(?:[-*•▪◦]|\d+[.)])\s+")
_MAIN_CHANNEL_BRIDGE = "основном канале"
_BOLD_LINE = re.compile(r"^\*\*[^*\n]+\*\*$")


def sanitize_plain_text(text: str) -> str:
    """Return the narrow plain-text subset allowed in channel publications.

    Only the exact canonical footer, including its three meaningful icons,
    survives. Other URLs, markup, emoji, non-printing Unicode and non-standard
    symbols are removed rather than passed through to Telegram.
    """
    protected: dict[str, str] = {}
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    def protect(match: re.Match[str]) -> str:
        marker = f"CANONICALURL{len(protected)}"
        protected[marker] = match.group(0)
        return marker

    value = _CANONICAL_FOOTER.sub(lambda match: protect(match), value)
    value = _CANONICAL_URL.sub(protect, value)
    value = _URL.sub("", value)
    value = re.sub(r"\(\s*\)", "", value)
    value = _HTML_TAG.sub("", value)
    value = _HTML_ENTITY.sub(" ", value)
    value = _DISALLOWED.sub("", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    for marker, url in protected.items():
        value = value.replace(marker, url)
    return value.strip()


def validate_plain_text(text: str) -> None:
    """Reject text outside the intentionally small plain-text channel subset."""
    if not text.strip():
        raise TelegramFormattingError("draft must not be empty")
    if len(text) > 4096:
        raise TelegramFormattingError("Telegram message exceeds 4096 characters")
    if text != sanitize_plain_text(text):
        raise TelegramFormattingError("draft must use plain text without markup, links, or hidden characters")


def validate_publication_text(text: str) -> None:
    """Apply the short invite-channel contract before a post is stored or sent."""
    if not text.strip() or "\r" in text or _HTML_TAG.search(text) or _HTML_ENTITY.search(text):
        raise TelegramFormattingError("draft must use safe Telegram text")
    if not MIN_POST_LENGTH <= len(text) <= MAX_POST_LENGTH:
        raise TelegramFormattingError(
            f"draft must contain {MIN_POST_LENGTH}-{MAX_POST_LENGTH} characters including the required footer"
        )
    if not text.endswith(CANONICAL_FOOTER) or text.count(CANONICAL_FOOTER) != 1:
        raise TelegramFormattingError("draft must end with the required MetricHit footer")
    if any(text.count(url) != 1 for url in CANONICAL_URLS):
        raise TelegramFormattingError("draft must contain each canonical MetricHit URL exactly once")
    if len(_URL.findall(text)) != len(CANONICAL_URLS):
        raise TelegramFormattingError("invite post must not contain arbitrary links")
    lines = text.splitlines()
    first_nonempty = next((line for line in lines if line), "")
    main_channel_line = "**📢 Основной канал MetricHit: https://t.me/mtr_hit**"
    if first_nonempty != lines[0] or not _BOLD_LINE.fullmatch(first_nonempty):
        raise TelegramFormattingError("invite post must start with one bold headline")
    if text.count("**") != 4 or main_channel_line not in lines:
        raise TelegramFormattingError("invite post allows bold text only for the headline and main channel footer line")
    main_channel_index = lines.index(main_channel_line)
    if lines[main_channel_index + 1:] != ["", "🌐 Сайт MetricHit: https://go.mtrhit.ru/", "💬 Поддержка в Telegram: https://t.me/Metric_Hit"]:
        raise TelegramFormattingError("invite footer structure is invalid")
    body = text.removesuffix(CANONICAL_FOOTER).rstrip()
    if _DISALLOWED.search(body.replace("**", "")):
        raise TelegramFormattingError("invite post contains unsupported markup or symbols")
    if _DECORATIVE_LIST_LINE.search(body):
        raise TelegramFormattingError("invite post must not use a decorative list")
    if _MAIN_CHANNEL_BRIDGE not in body.casefold():
        raise TelegramFormattingError("invite post must give a concise reason to continue in the main channel")
    lowered = text.casefold()
    if any(phrase in lowered for phrase in _FORBIDDEN_META_PHRASES):
        raise TelegramFormattingError("draft contains generic editorial filler")


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
        lead = f"**{request.topic.strip()}**\n\n{request.opening.strip()}"
        if request.source_notes is not None:
            body = request.source_notes.strip()
        else:
            body = (
                "Сначала определите одну страницу и задачу пользователя. Если смешать запросы, регионы или "
                "периоды, цифра не подскажет решение."
                "\n\nЭто помогает отделить наблюдение от предположения."
            )
        conclusion = request.conclusion or self._contextual_conclusion(request)
        sections = [lead, body, conclusion, facts, cta.strip()]
        return "\n\n".join(section for section in sections if section)

    @staticmethod
    def _contextual_conclusion(request: PostRequest) -> str:
        """A concise bridge; the main channel keeps the deeper explanation."""
        if request.kind in _INSTRUCTION_KINDS:
            return "В основном канале MetricHit разбираем, как превратить такую проверку в последовательный план действий."
        if request.kind in _DIAGNOSTIC_KINDS:
            return "В основном канале MetricHit разбираем, какие признаки помогают проверить такую гипотезу глубже."
        return "В основном канале MetricHit разбираем, как применять этот принцип к страницам и группам запросов."


class LocalPostAuthor:
    """Creates and revises drafts without knowing a model engine or publisher."""

    def __init__(self, adapter: LocalModelAdapter):
        self._adapter = adapter

    def draft(self, profile: AuthorProfile, request: PostRequest) -> Draft:
        self._reject_public_mechanics(profile, request)
        generated = self._adapter.generate(AuthorPrompt(profile=profile, request=request))
        text = f"{generated}\n\n{CANONICAL_FOOTER}"
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
        missing = [fact for fact in facts if fact not in text]
        if missing:
            raise FactIntegrityError(f"draft omits supplied facts: {', '.join(missing)}")
        if cta and cta not in text:
            raise FactIntegrityError("draft omits the requested CTA")
        validate_publication_text(text)

    @staticmethod
    def _reject_public_mechanics(profile: AuthorProfile, request: PostRequest) -> None:
        public_fields = (
            request.topic, request.opening, request.cta or "", request.source_notes or "", *profile.product_facts,
        )
        if any(_PROHIBITED_SEARCH_MECHANICS.search(value) for value in public_fields):
            raise PublicDisclosureError("public drafts must not disclose bot search-result mechanics")
