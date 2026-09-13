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
    source_notes: str | None = None

    def __post_init__(self) -> None:
        if not self.topic.strip() or not self.opening.strip():
            raise AuthorError("topic and opening must not be empty")
        if self.cta is not None and not self.cta.strip():
            raise AuthorError("cta must not be blank when supplied")
        if self.direction is not None and not self.direction.strip():
            raise AuthorError("direction must not be blank when supplied")
        if self.source_notes is not None and not self.source_notes.strip():
            raise AuthorError("source_notes must not be blank when supplied")


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
    "Основной канал MetricHit: https://t.me/mtr_hit\n"
    "Сайт MetricHit: https://go.mtrhit.ru/\n"
    "Поддержка в Telegram: https://t.me/Metric_Hit"
)
CANONICAL_URLS = (
    "https://t.me/mtr_hit",
    "https://go.mtrhit.ru/",
    "https://t.me/Metric_Hit",
)
_CANONICAL_URL = re.compile(
    r"(?<![A-Za-z0-9_./-])(" + "|".join(re.escape(url) for url in CANONICAL_URLS) + r")(?![A-Za-z0-9_./-])"
)
_URL = re.compile(r"(?i)\b(?:https?://|www\.|t\.me/)[^\s<>()]+")
_HTML_TAG = re.compile(r"<[^>\n]*>")
_HTML_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+);")
_DISALLOWED = re.compile(r"[^A-Za-zА-Яа-яЁё0-9 \n.,;:!?()\-\"']")
MIN_POST_LENGTH = 900
MAX_POST_LENGTH = 1400
_FORBIDDEN_META_PHRASES = (
    "практический формат", "материал должен помогать", "в этой логике", "здесь важно",
)


def sanitize_plain_text(text: str) -> str:
    """Return the narrow plain-text subset allowed in channel publications.

    Only the three canonical MetricHit URLs survive. Other URLs, markup,
    emoji, non-printing Unicode and non-standard symbols are removed rather
    than passed through to Telegram. Newlines remain visible paragraph breaks.
    """
    protected: dict[str, str] = {}
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    def protect(match: re.Match[str]) -> str:
        marker = f"CANONICALURL{len(protected)}"
        protected[marker] = match.group(1)
        return marker

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
    """Apply the channel's readable-text contract before a post is stored or sent."""
    validate_plain_text(text)
    if not MIN_POST_LENGTH <= len(text) <= MAX_POST_LENGTH:
        raise TelegramFormattingError(
            f"draft must contain {MIN_POST_LENGTH}-{MAX_POST_LENGTH} characters including the required footer"
        )
    if not text.endswith(CANONICAL_FOOTER) or text.count(CANONICAL_FOOTER) != 1:
        raise TelegramFormattingError("draft must end with the required MetricHit footer")
    if any(text.count(url) != 1 for url in CANONICAL_URLS):
        raise TelegramFormattingError("draft must contain each canonical MetricHit URL exactly once")
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
        lead = f"{request.topic.strip()}\n\n{request.opening.strip()} "
        if request.source_notes is not None:
            body = (
                f"{request.source_notes.strip()}\n\n"
                f"В работе с темой {request.topic.strip()} полезно оставлять след решения: что проверили, "
                "какой вопрос остался открытым и когда к нему вернутся. Это не заменяет анализ, но позволяет "
                "команде обсуждать конкретную страницу или группу запросов, а не общее ощущение от изменений."
            )
        elif request.kind in _INSTRUCTION_KINDS:
            body = (
                "Сначала определите, какую страницу и какие запросы вы проверяете. Затем откройте страницу как "
                "пользователь: понятна ли услуга, следующий шаг и условия обращения. После этого сверяйте выводы с "
                "данными за один и тот же период. Если причина не подтверждается, фиксируйте вопрос, а не меняйте "
                "страницу наугад. Такой порядок оставляет у команды понятное основание для следующего решения."
                "\n\nНе ограничивайтесь формальной проверкой наличия блоков. Сравните заголовок, первый экран, "
                "описание услуги и форму обращения с тем, что человек ожидает получить по запросу. Если между ними "
                "есть разрыв, сначала опишите его словами. Это даёт задачу для доработки вместо длинного списка "
                "несвязанных правок."
            )
        elif request.kind in _DIAGNOSTIC_KINDS:
            body = (
                "Один и тот же симптом не указывает на одну причину. На него влияют страница, намерение запроса, "
                "регион, недавние изменения и период сравнения. Сначала отделите факт из данных от предположения. "
                "Потом проверьте соседние запросы и страницы, которые участвуют в той же задаче пользователя. Так "
                "можно понять, где нужна правка, а где достаточно продолжить наблюдение."
                "\n\nСравнение должно отвечать на один вопрос. Не складывайте в один вывод смену контента, "
                "перенастройку аналитики и изменение спроса. Когда условия записаны рядом с наблюдением, обсуждение "
                "идёт о проверяемой причине, а не о впечатлении от графика."
                " Не торопитесь назначать виноватого до такой сверки."
            )
        elif request.kind == PostKind.EXPLANATORY or request.kind == PostKind.CTA:
            body = (
                "У такой задачи редко бывает одна причина. Роль страницы, полнота ответа, техническая доступность, "
                "коммерческая информация и региональный контекст работают вместе. Изменение одного показателя не "
                "доказывает влияние одного фактора. Полезнее сначала понять задачу пользователя, а затем проверять, "
                "насколько страница действительно отвечает на неё."
                "\n\nНапример, коммерческий запрос не решается одним упоминанием услуги. Читателю нужны условия, "
                "сроки, способ связи и ответ на сомнения, которые возникают до обращения. Страница становится понятнее, "
                "когда эти ответы находятся там, где их ожидают увидеть, а не спрятаны в общем тексте."
            )
        else:
            body = (
                "В SEO полезно разделять факт, наблюдение и вывод. Позиция существует в контексте запроса, страницы, "
                "региона и периода измерения. Одно изменение не стоит выдавать за доказанный эффект, а один показатель "
                "не заменяет картину целиком. Назовите, что известно, и только затем решайте, нужна ли проверка "
                "страницы, семантики или технической части."
                "\n\nТакой подход экономит время команды. Вместо попытки исправить всё сразу появляется короткий "
                "список проверок с понятным основанием: что менялось, какую задачу решает страница и какие данные "
                "нужны для следующего вывода."
                " Это сохраняет фокус и не превращает работу в поток случайных правок."
            )
        conclusion = "Не обещайте результат до проверки. Точный вопрос к данным и странице полезнее уверенного, но неподтверждённого ответа."
        sections = [lead, body, conclusion, facts, cta.strip()]
        return "\n\n".join(section for section in sections if section)


class LocalPostAuthor:
    """Creates and revises drafts without knowing a model engine or publisher."""

    def __init__(self, adapter: LocalModelAdapter):
        self._adapter = adapter

    def draft(self, profile: AuthorProfile, request: PostRequest) -> Draft:
        self._reject_public_mechanics(profile, request)
        generated = sanitize_plain_text(self._adapter.generate(AuthorPrompt(profile=profile, request=request)))
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
        validate_plain_text(text)
        missing = [fact for fact in facts if fact not in text]
        if missing:
            raise FactIntegrityError(f"draft omits supplied facts: {', '.join(missing)}")
        if cta not in text:
            raise FactIntegrityError("draft omits the requested CTA")
        validate_publication_text(text)

    @staticmethod
    def _reject_public_mechanics(profile: AuthorProfile, request: PostRequest) -> None:
        public_fields = (
            request.topic, request.opening, request.cta or "", request.source_notes or "", *profile.product_facts,
        )
        if any(_PROHIBITED_SEARCH_MECHANICS.search(value) for value in public_fields):
            raise PublicDisclosureError("public drafts must not disclose bot search-result mechanics")
