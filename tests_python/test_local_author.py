import pytest

from metrichit_os.local_author import (
    AuthorProfile, DeterministicLocalAdapter, FactIntegrityError, LocalPostAuthor,
    PostKind, PostRequest, RevisionError, TelegramFormattingError, validate_telegram_markdown,
)


@pytest.fixture
def profile() -> AuthorProfile:
    return AuthorProfile(
        tone="спокойный и деловой",
        audience="владельцы сайтов",
        product_facts=(
            "Бот открывает несколько результатов поиска, затем целевой сайт последним.",
            "После открытия целевого сайта бот не возвращается в поиск и не действует внутри сайта.",
        ),
        constraints=("Не обещать рост позиций.", "Не выдумывать характеристики продукта."),
        default_cta="Проверьте исходные позиции перед запуском.",
    )


@pytest.mark.parametrize("kind", list(PostKind))
def test_deterministic_mode_supports_every_post_kind_without_model(profile: AuthorProfile, kind: PostKind) -> None:
    adapter = DeterministicLocalAdapter()
    draft = LocalPostAuthor(adapter).draft(profile, PostRequest(kind, "Тема", "Короткое вступление."))

    assert draft.kind is kind
    assert draft.text.startswith("**Тема**")
    assert all(fact in draft.text for fact in profile.product_facts)
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
    assert prompt.profile.formatting == "Telegram Markdown"
    assert draft.cta == "Напишите нам в поддержку."


def test_author_rejects_adapter_that_omits_a_supplied_fact(profile: AuthorProfile) -> None:
    class IncompleteAdapter:
        def generate(self, _prompt):
            return "**Тема**\n\nТолько один факт.\n\nПроверьте исходные позиции перед запуском."

    with pytest.raises(FactIntegrityError, match="omits supplied facts"):
        LocalPostAuthor(IncompleteAdapter()).draft(profile, PostRequest(PostKind.PRODUCT, "Тема", "Вступление."))


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
def test_telegram_format_validator_rejects_unsupported_markup(text: str) -> None:
    with pytest.raises(TelegramFormattingError):
        validate_telegram_markdown(text)
