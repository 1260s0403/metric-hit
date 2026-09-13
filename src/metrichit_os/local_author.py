"""Offline-first drafting for MetricHit Telegram posts.

This module intentionally has no transport, credentials, network client, or
model runtime.  A future local-model integration only needs to implement
``LocalModelAdapter``; callers keep using ``LocalPostAuthor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from base64 import b64decode
import re
from typing import Protocol


class PostKind(StrEnum):
    PRODUCT = "product"
    CHECKLIST = "checklist"
    UPDATE = "update"
    CTA = "cta"


class AuthorError(ValueError):
    """Base error for invalid author input or an invalid model response."""


class FactIntegrityError(AuthorError):
    """A draft did not preserve the supplied product facts verbatim."""


class TelegramFormattingError(AuthorError):
    """A draft cannot be represented as a safe Telegram Markdown message."""


class RevisionError(AuthorError):
    """Revision feedback is unsupported or would alter more than requested."""


class PublicDisclosureError(AuthorError):
    """Public drafts must not disclose the bot's search-result mechanics."""


class ImageGenerationError(AuthorError):
    """An image generator returned an unusable post asset."""


@dataclass(frozen=True)
class AuthorProfile:
    tone: str
    audience: str
    product_facts: tuple[str, ...]
    constraints: tuple[str, ...]
    default_cta: str
    formatting: str = "Telegram Markdown"

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

    def __post_init__(self) -> None:
        if not self.topic.strip() or not self.opening.strip():
            raise AuthorError("topic and opening must not be empty")
        if self.cta is not None and not self.cta.strip():
            raise AuthorError("cta must not be blank when supplied")


@dataclass(frozen=True)
class AuthorPrompt:
    profile: AuthorProfile
    request: PostRequest


@dataclass(frozen=True)
class ImagePrompt:
    """A local generator receives only the public post theme and presentation intent."""

    kind: PostKind
    topic: str
    audience: str


@dataclass(frozen=True)
class GeneratedImage:
    """Raster asset prepared alongside a draft, without any publication behaviour."""

    content: bytes
    media_type: str
    prompt: str

    def __post_init__(self) -> None:
        if not self.content:
            raise ImageGenerationError("generated image must not be empty")
        if not self.media_type.startswith("image/"):
            raise ImageGenerationError("generated image must use an image media type")
        if not self.prompt.strip():
            raise ImageGenerationError("generated image prompt must not be empty")


@dataclass(frozen=True)
class Draft:
    kind: PostKind
    topic: str
    text: str
    facts: tuple[str, ...]
    cta: str
    image: GeneratedImage
    revision: int = 1


class LocalModelAdapter(Protocol):
    """Replaceable local-model boundary. Implementations must be offline-safe."""

    def generate(self, prompt: AuthorPrompt) -> str: ...


class LocalImageAdapter(Protocol):
    """Replaceable offline boundary for themed raster generation."""

    def generate_image(self, prompt: ImagePrompt) -> GeneratedImage: ...


_SECTIONS = {
    PostKind.PRODUCT: "Что важно",
    PostKind.CHECKLIST: "Чек-лист перед запуском",
    PostKind.UPDATE: "Что обновилось",
    PostKind.CTA: "Следующий шаг",
}

REQUIRED_PUBLIC_LINKS = (
    "https://t.me/mtr_hit",
    "https://go.mtrhit.ru/",
    "https://t.me/Metric_Hit",
)

_PROHIBITED_SEARCH_MECHANICS = re.compile(
    r"(?:поисков\w*\s+(?:выдач\w*|результат\w*)|"
    r"открыва\w*[^\n.]{0,80}(?:результат\w*|сайт)|"
    r"целев\w*\s+сайт[^\n.]{0,60}последн\w*|"
    r"не\s+возвращ\w*[^\n.]{0,60}поиск\w*|"
    r"действ\w*\s+внутри\s+сайт\w*)",
    re.IGNORECASE,
)


def validate_telegram_markdown(text: str) -> None:
    """Reject formatting that cannot be sent as the module's Markdown subset."""
    if not text.strip():
        raise TelegramFormattingError("draft must not be empty")
    if len(text) > 4096:
        raise TelegramFormattingError("Telegram message exceeds 4096 characters")
    if "\r" in text or "<" in text or ">" in text:
        raise TelegramFormattingError("HTML and carriage returns are not allowed")
    if text.count("**") % 2:
        raise TelegramFormattingError("bold Markdown markers must be balanced")


class DeterministicLocalAdapter:
    """Offline test adapter; it never downloads or invokes a language model."""

    def __init__(self) -> None:
        self.prompts: list[AuthorPrompt] = []

    def generate(self, prompt: AuthorPrompt) -> str:
        self.prompts.append(prompt)
        request, profile = prompt.request, prompt.profile
        facts = "\n".join(f"• {fact}" for fact in profile.product_facts)
        cta = request.cta or profile.default_cta
        return (
            f"**{request.topic.strip()}**\n\n"
            f"{request.opening.strip()}\n\n"
            f"**{_SECTIONS[request.kind]}**\n{facts}\n\n"
            f"{cta.strip()}\n\n"
            "В основном канале MetricHit — разборы и следующие шаги.\n"
            f"➡️ {REQUIRED_PUBLIC_LINKS[0]}\n\n"
            f"Сайт: {REQUIRED_PUBLIC_LINKS[1]}\n"
            f"Поддержка: {REQUIRED_PUBLIC_LINKS[2]}"
        )


class DeterministicLocalImageAdapter:
    """Offline baseline that yields a valid PNG and a topic-specific generator prompt.

    It is deliberately a test-safe fallback, not a substitute for a selected
    local image model.  A local model only needs to implement ``LocalImageAdapter``.
    """

    _PIXEL_PNG = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/" \
        "zX2k7wAAAABJRU5ErkJggg=="
    )

    def __init__(self) -> None:
        self.prompts: list[ImagePrompt] = []

    def generate_image(self, prompt: ImagePrompt) -> GeneratedImage:
        self.prompts.append(prompt)
        return GeneratedImage(
            content=self._PIXEL_PNG,
            media_type="image/png",
            prompt=(
                f"Telegram post cover about {prompt.topic.strip()} for {prompt.audience.strip()}. "
                "Clean editorial illustration, no text, no logos, no watermark."
            ),
        )


class LocalPostAuthor:
    """Creates and revises drafts without knowing a model engine or publisher."""

    def __init__(self, adapter: LocalModelAdapter, image_adapter: LocalImageAdapter | None = None):
        self._adapter = adapter
        self._image_adapter = image_adapter or DeterministicLocalImageAdapter()

    def draft(self, profile: AuthorProfile, request: PostRequest) -> Draft:
        self._reject_public_mechanics(profile, request)
        text = self._adapter.generate(AuthorPrompt(profile=profile, request=request))
        facts = tuple(fact.strip() for fact in profile.product_facts)
        cta = (request.cta or profile.default_cta).strip()
        self._validate(text, facts, cta)
        image = self._image_adapter.generate_image(ImagePrompt(
            kind=request.kind, topic=request.topic.strip(), audience=profile.audience.strip(),
        ))
        self._validate_image(image, request.topic)
        return Draft(kind=request.kind, topic=request.topic.strip(), text=text, facts=facts, cta=cta, image=image)

    def revise(self, draft: Draft, feedback: str) -> Draft:
        """Apply only ``Замени CTA на: ...``; all non-CTA text stays byte-identical."""
        prefix = "Замени CTA на:"
        if not feedback.startswith(prefix):
            raise RevisionError("supported feedback: 'Замени CTA на: <новый CTA>'")
        replacement = feedback.removeprefix(prefix).strip()
        if not replacement:
            raise RevisionError("replacement CTA must not be empty")
        if draft.text.count(draft.cta) != 1:
            raise RevisionError("draft CTA must occur exactly once")
        text = draft.text.replace(draft.cta, replacement, 1)
        self._validate(text, draft.facts, replacement)
        return Draft(
            kind=draft.kind, topic=draft.topic, text=text, facts=draft.facts,
            cta=replacement, image=draft.image, revision=draft.revision + 1,
        )

    @staticmethod
    def _validate(text: str, facts: tuple[str, ...], cta: str) -> None:
        validate_telegram_markdown(text)
        missing = [fact for fact in facts if fact not in text]
        if missing:
            raise FactIntegrityError(f"draft omits supplied facts: {', '.join(missing)}")
        if cta not in text:
            raise FactIntegrityError("draft omits the requested CTA")
        missing_links = [link for link in REQUIRED_PUBLIC_LINKS if link not in text]
        if missing_links:
            raise FactIntegrityError(f"draft omits required public links: {', '.join(missing_links)}")

    @staticmethod
    def _reject_public_mechanics(profile: AuthorProfile, request: PostRequest) -> None:
        public_fields = (request.topic, request.opening, request.cta or "", *profile.product_facts)
        if any(_PROHIBITED_SEARCH_MECHANICS.search(value) for value in public_fields):
            raise PublicDisclosureError("public drafts must not disclose bot search-result mechanics")

    @staticmethod
    def _validate_image(image: GeneratedImage, topic: str) -> None:
        if topic.strip().casefold() not in image.prompt.casefold():
            raise ImageGenerationError("generated image prompt must include the post topic")
