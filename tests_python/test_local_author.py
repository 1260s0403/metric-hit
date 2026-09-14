import pytest

from metrichit_os.local_author import (
    AuthorProfile, DeterministicLocalAdapter, FactIntegrityError, LocalPostAuthor,
    MAX_POST_LENGTH, MIN_POST_LENGTH, PostKind, PostRequest, PublicDisclosureError, RevisionError, TelegramFormattingError,
    CANONICAL_FOOTER, CANONICAL_URLS, THEMATIC_DIRECTIONS, sanitize_plain_text,
    validate_plain_text, validate_publication_text,
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
    assert draft.text.startswith("**Тема**")
    assert all(fact in draft.text for fact in profile.product_facts)
    validate_publication_text(draft.text)
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


def test_plain_text_sanitizer_keeps_only_canonical_urls_and_removes_markup_emoji_hidden_unicode() -> None:
    unsafe = "**Проверка** • https://example.test/путь\u200b\n➡️ Готово [сейчас](https://t.me/test)"

    assert sanitize_plain_text(unsafe) == "Проверка\nГотово сейчас"
    assert sanitize_plain_text(f"Текст {CANONICAL_URLS[0]} https://example.test/") == (
        f"Текст {CANONICAL_URLS[0]}"
    )
    assert sanitize_plain_text(f"Текст {CANONICAL_URLS[0]}.evil") == "Текст"


def test_plain_text_allows_meaningful_icons_only_in_the_exact_footer() -> None:
    assert CANONICAL_FOOTER == (
        "**📢 Основной канал MetricHit: https://t.me/mtr_hit**\n"
        "\n"
        "🌐 Сайт MetricHit: https://go.mtrhit.ru/\n"
        "💬 Поддержка в Telegram: https://t.me/Metric_Hit"
    )
    assert sanitize_plain_text(f"Тема\n\n{CANONICAL_FOOTER}") == f"Тема\n\n{CANONICAL_FOOTER}"
    with pytest.raises(TelegramFormattingError):
        validate_plain_text("Тема 📢")


@pytest.mark.parametrize("kind", list(PostKind))
def test_deterministic_author_enforces_plain_text_length_for_all_formats(
    profile: AuthorProfile, kind: PostKind,
) -> None:
    draft = LocalPostAuthor(DeterministicLocalAdapter()).draft(
        profile,
        PostRequest(kind, "Как проверять страницу перед тестом", "У страницы может быть понятный запрос, но неясная роль в запуске."),
    )

    assert MIN_POST_LENGTH <= len(draft.text) <= MAX_POST_LENGTH
    assert draft.text.endswith(CANONICAL_FOOTER)
    assert all(draft.text.count(url) == 1 for url in CANONICAL_URLS)
    assert draft.text.splitlines()[0] == f"**{draft.topic}**"
    assert draft.text.count("**") == 4


def test_actions_are_reserved_for_practical_instruction_format(profile: AuthorProfile) -> None:
    adapter = DeterministicLocalAdapter()
    author = LocalPostAuthor(adapter)
    instruction = author.draft(profile, PostRequest(
        PostKind.INSTRUCTION, "Проверка страницы", "Нужно подготовить страницу к запуску.",
        direction=THEMATIC_DIRECTIONS[2],
    ))
    informational = author.draft(profile, PostRequest(
        PostKind.INFORMATIONAL, "Контекст выдачи", "Выдача зависит от нескольких условий.",
        direction=THEMATIC_DIRECTIONS[1],
    ))
    assert "основном канале" in instruction.text.casefold()
    assert "основном канале" in informational.text.casefold()
    assert adapter.prompts[-1].request.direction == THEMATIC_DIRECTIONS[1]


@pytest.mark.parametrize("body", [
    "**Тема**\n\n- Первый пункт\n\nВ основном канале MetricHit есть продолжение.\n\n",
    "**Тема**\n\n1. Первый пункт\n\nВ основном канале MetricHit есть продолжение.\n\n",
    "**Тема**\n\nКороткий вывод без перехода.\n\n",
])
def test_invite_validator_rejects_decorative_lists_and_missing_main_channel_bridge(body: str) -> None:
    padded = body + ("Текст " * 100) + "\n\n" + CANONICAL_FOOTER
    with pytest.raises(TelegramFormattingError):
        validate_publication_text(padded)


@pytest.mark.parametrize("text", [
    "**Короткий текст**\n\n" + CANONICAL_FOOTER,
    "**Тема**\n\n" + ("Текст " * 200) + "\n\n" + CANONICAL_FOOTER + "\n\nлишнее",
    "**Тема**\n\n" + ("Здесь важно " * 80) + "\n\n" + CANONICAL_FOOTER,
])
def test_publication_quality_validator_rejects_bad_length_footer_or_generic_filler(text: str) -> None:
    with pytest.raises(TelegramFormattingError):
        validate_publication_text(text)
