import pytest

from metrichit_os.local_author import (
    AuthorProfile, DeterministicLocalAdapter, FactIntegrityError, LocalPostAuthor,
    MAX_POST_LENGTH, MIN_POST_LENGTH, PostKind, PostRequest, PublicDisclosureError, RevisionError, TelegramFormattingError,
    sanitize_plain_text, validate_plain_text,
)


@pytest.fixture
def profile() -> AuthorProfile:
    return AuthorProfile(
        tone="спокойный и деловой",
        audience="владельцы сайтов",
        product_facts=(
            "Новый пользователь может один раз получить 1 000 тестовых кликов после регистрации и обращения в Telegram-поддержку с логином.",
            "Неиспользованный остаток не сгорает.",
        ),
        constraints=("Не обещать рост позиций.", "Не выдумывать характеристики продукта."),
        default_cta="Проверьте исходные позиции перед запуском.",
    )


@pytest.mark.parametrize("kind", list(PostKind))
def test_deterministic_mode_supports_every_post_kind_without_model(profile: AuthorProfile, kind: PostKind) -> None:
    adapter = DeterministicLocalAdapter()
    draft = LocalPostAuthor(adapter).draft(profile, PostRequest(kind, "Тема", "Короткое вступление."))

    assert draft.kind is kind
    assert draft.text.startswith("Тема")
    assert all(fact in draft.text for fact in profile.product_facts)
    assert draft.text == sanitize_plain_text(draft.text)
    assert adapter.prompts == [adapter.prompts[0]]
    assert adapter.prompts[0].profile == profile


def test_author_passes_profile_rules_and_requested_cta_to_adapter(profile: AuthorProfile) -> None:
    adapter = DeterministicLocalAdapter()
    draft = LocalPostAuthor(adapter).draft(
        profile, PostRequest(PostKind.CTA, "Старт", "Готовим запуск.", "Напишите нам в поддержку."),
    )

    prompt = adapter.prompts[0]
    assert prompt.profile.tone == "спокойный и деловой"
    assert prompt.profile.audience == "владельцы сайтов"
    assert prompt.profile.constraints == profile.constraints
    assert prompt.profile.formatting == "plain text"
    assert draft.cta == "Напишите нам в поддержку."


def test_author_rejects_adapter_that_omits_a_supplied_fact(profile: AuthorProfile) -> None:
    class IncompleteAdapter:
        def generate(self, _prompt):
            return "**Тема**\n\nТолько один факт.\n\nПроверьте исходные позиции перед запуском."

    with pytest.raises(FactIntegrityError, match="omits supplied facts"):
        LocalPostAuthor(IncompleteAdapter()).draft(profile, PostRequest(PostKind.PRODUCT, "Тема", "Вступление."))


@pytest.mark.parametrize("topic,opening,facts", [
    ("Поисковая выдача", "Нейтральное вступление.", None),
    ("Тема", "Бот открывает результаты поиска.", None),
    ("Тема", "Нейтральное вступление.", ("Целевой сайт открывается последним.",)),
])
def test_author_rejects_search_mechanics_in_public_drafts(
    profile: AuthorProfile, topic: str, opening: str, facts: tuple[str, ...] | None,
) -> None:
    guarded_profile = profile if facts is None else AuthorProfile(
        tone=profile.tone, audience=profile.audience, product_facts=facts,
        constraints=profile.constraints, default_cta=profile.default_cta,
    )
    with pytest.raises(PublicDisclosureError, match="must not disclose"):
        LocalPostAuthor(DeterministicLocalAdapter()).draft(
            guarded_profile, PostRequest(PostKind.PRODUCT, topic, opening),
        )


def test_revision_changes_only_requested_cta(profile: AuthorProfile) -> None:
    author = LocalPostAuthor(DeterministicLocalAdapter())
    original = author.draft(profile, PostRequest(PostKind.PRODUCT, "Тема", "Вступление."))
    revised = author.revise(original, "Замени CTA на: Получите консультацию в Telegram.")

    assert revised.revision == 2
    assert revised.cta == "Получите консультацию в Telegram."
    assert original.cta not in revised.text
    assert revised.text.replace(revised.cta, original.cta) == original.text


def test_revision_rejects_unscoped_feedback(profile: AuthorProfile) -> None:
    draft = LocalPostAuthor(DeterministicLocalAdapter()).draft(profile, PostRequest(PostKind.UPDATE, "Тема", "Вступление."))
    with pytest.raises(RevisionError):
        LocalPostAuthor(DeterministicLocalAdapter()).revise(draft, "Перепиши весь пост")


@pytest.mark.parametrize("text", ["**Незакрытый", "<b>HTML</b>", "x" * 4097])
def test_plain_text_validator_rejects_unsupported_markup(text: str) -> None:
    with pytest.raises(TelegramFormattingError):
        validate_plain_text(text)


def test_plain_text_sanitizer_removes_urls_markdown_emoji_and_hidden_unicode() -> None:
    unsafe = "**Проверка** • https://example.test/путь\u200b\n➡️ Готово [сейчас](https://t.me/test)"

    assert sanitize_plain_text(unsafe) == "Проверка\nГотово сейчас"


@pytest.mark.parametrize("kind", list(PostKind))
def test_deterministic_author_enforces_substantive_plain_text_post_contract(
    profile: AuthorProfile, kind: PostKind,
) -> None:
    draft = LocalPostAuthor(DeterministicLocalAdapter()).draft(
        profile,
        PostRequest(kind, "Как проверять страницу перед тестом", "У страницы может быть понятный запрос, но неясная роль в запуске."),
    )

    assert MIN_POST_LENGTH <= len(draft.text) <= MAX_POST_LENGTH
    assert all(phrase in draft.text for phrase in ("Сначала", "Затем", "После этого", "Отдельно"))
    assert "http" not in draft.text.casefold()
    assert "**" not in draft.text
    assert draft.text == sanitize_plain_text(draft.text)
