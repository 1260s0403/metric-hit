import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-publication-memory-update:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function json(value) { return JSON.stringify(value); }
function requiredText(value, field) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} is required`);
  return value.trim();
}

function assertPublicationUpdate(update) {
  const semanticKey = requiredText(update.semanticKey, 'semanticKey');
  const title = requiredText(update.title, 'title');
  const content = requiredText(update.content, 'content');
  const platform = requiredText(update.platform, 'platform');
  const canonicalUrl = update.canonicalUrl === null || update.canonicalUrl === undefined
    ? null : requiredText(update.canonicalUrl, 'canonicalUrl');
  const publishedAt = requiredText(update.publishedAt, 'publishedAt');
  const reviewedAt = requiredText(update.reviewedAt, 'reviewedAt');
  if (canonicalUrl !== null && (!URL.canParse(canonicalUrl) || !/^https?:\/\//u.test(canonicalUrl))) {
    throw new Error('canonicalUrl must be an http(s) URL when provided');
  }
  if (Number.isInteger(update.revision) === false || update.revision < 1) throw new Error('revision must be a positive integer');
  if (!Array.isArray(update.expectedPriorRevisions) || !update.expectedPriorRevisions.every(Number.isInteger)) {
    throw new Error('expectedPriorRevisions must be an integer array');
  }
  if (update.allowCreate !== undefined && typeof update.allowCreate !== 'boolean') {
    throw new Error('allowCreate must be a boolean when provided');
  }
  const publicationStatus = update.publicationStatus === undefined
    ? 'independently_verified' : requiredText(update.publicationStatus, 'publicationStatus');
  if (!update.verifiedFacts || typeof update.verifiedFacts !== 'object' || Array.isArray(update.verifiedFacts)) {
    throw new Error('verifiedFacts must be an object');
  }
  const authority = update.authority === undefined
    ? 'direct_owner_request_with_public_readonly_verification' : requiredText(update.authority, 'authority');
  const verificationMethod = update.verificationMethod === undefined
    ? 'public_page_read_only' : requiredText(update.verificationMethod, 'verificationMethod');
  const publicUrlStatus = canonicalUrl === null
    ? 'not_provided_by_owner' : 'owner_provided';
  return { ...update, semanticKey, title, content, platform, canonicalUrl, publicUrlStatus, publishedAt, reviewedAt,
    publicationStatus, authority, verificationMethod };
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) {
    if (row[field] !== value) throw new Error(`${label}.${field} differs`);
  }
}

export function updatePublicationMemory(databasePath = defaultDatabasePath, input) {
  const update = assertPublicationUpdate(input);
  if (!existsSync(databasePath)) throw new Error(`Database does not exist: ${databasePath}`);
  const sourceData = {
    authority: update.authority,
    canonical_url: update.canonicalUrl,
    verification_method: update.verificationMethod,
    verified_at: update.reviewedAt,
    verified_facts: update.verifiedFacts,
  };
  const sourceContent = json(sourceData);
  const sourceId = stableUuid(`source:${update.semanticKey}:revision:${update.revision}`);
  const documentId = stableUuid(`document:${update.semanticKey}:revision:${update.revision}`);
  const versionId = stableUuid(`document-version:${update.semanticKey}:revision:${update.revision}`);
  const candidateId = stableUuid(`candidate:${update.semanticKey}:revision:${update.revision}`);
  const data = json({
    platform: update.platform,
    publication_status: update.publicationStatus,
    canonical_url: update.canonicalUrl,
    public_url: update.canonicalUrl,
    public_url_status: update.publicUrlStatus,
    published_at: update.publishedAt,
    verified_facts: update.verifiedFacts,
    revision: update.revision,
    supersedes_semantic_revisions: update.expectedPriorRevisions,
    evidence: { source_id: sourceId, verification_method: update.verificationMethod },
  });
  const database = new DatabaseSync(resolve(databasePath));
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const existing = database.prepare(`SELECT id,coalesce(json_extract(data_json, '$.revision'), 0) AS revision
      FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?`)
      .all(update.semanticKey, candidateId);
    const revisions = existing.map((row) => Number(row.revision)).sort((left, right) => left - right);
    if (revisions.some((revision) => !update.expectedPriorRevisions.includes(revision))) {
      throw new Error(`Unexpected semantic revision blocks ${update.semanticKey}: ${revisions.join(',')}`);
    }
    if (!revisions.length && !update.allowCreate) throw new Error(`Existing publication record is required for ${update.semanticKey}`);
    created.sources += Number(database.prepare(`INSERT OR IGNORE INTO sources
      (id,type,title,content,data_json,status,author,valid_at,access_level)
      VALUES (?,'owner_decision',?,?,?,'active','owner',?,'internal')`)
      .run(sourceId, `Обновление публикации: ${update.title}`, sourceContent, sourceContent, update.publishedAt).changes);
    created.documents += Number(database.prepare(`INSERT OR IGNORE INTO documents
      (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,'owner_decision',?,?,?,'active',?,'owner',?,'internal',1)`)
      .run(documentId, `Обновление публикации: ${update.title}`, sourceContent, sourceContent, sourceId, update.publishedAt).changes);
    created.versions += Number(database.prepare(`INSERT OR IGNORE INTO document_versions
      (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,?,'owner_decision',?,?,?,'active',?,'owner',?,'internal',1)`)
      .run(versionId, documentId, `Обновление публикации: ${update.title}`, sourceContent, sourceContent, sourceId, update.publishedAt).changes);
    created.candidates += Number(database.prepare(`INSERT OR IGNORE INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,'publication_state',?,?,?,?, 'pending',?,'owner',?,'internal',1)`)
      .run(candidateId, update.semanticKey, update.title, update.content, data, sourceId, update.publishedAt).changes);
    const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate?.status === 'pending') {
      database.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?,
        review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(
        update.reviewedAt, 'Одобрено прямым поручением владельца; факты проверены только публичным read-only просмотром.',
        update.reviewedAt, candidateId,
      );
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), {
      type: 'publication_state', semantic_key: update.semanticKey, title: update.title, content: update.content,
      data_json: data, status: 'approved', source_id: sourceId, reviewed_by: 'owner', reviewed_at: update.reviewedAt,
    }, `${update.semanticKey} candidate`);
    database.exec('COMMIT');
    return { databasePath: resolve(databasePath), created, candidateId, sourceId, documentId, versionId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

export const sostavFirstArticleUpdate = Object.freeze({
  semanticKey: 'publication.sostav_first_article', revision: 1, expectedPriorRevisions: [0],
  title: 'Первая статья MetricHit опубликована в Sostav',
  content: 'Статья «SEO вывело сайт в ТОП, а продажи не выросли: где ломается воронка» опубликована в блоге MetricHit на Sostav / SBlogs. Публичная страница: https://www.sostav.ru/blogs/293151/101025. На странице подтверждены заголовок, блог MetricHit, дата и время публикации 12.08.2026 17:51:40, canonical URL и разрешение index, follow.',
  platform: 'Sostav / SBlogs', canonicalUrl: 'https://www.sostav.ru/blogs/293151/101025',
  publishedAt: '2026-08-12T17:51:40+03:00', reviewedAt: '2026-08-31T23:59:00.000Z',
  verifiedFacts: {
    page_title: 'SEO вывело сайт в ТОП, а продажи не выросли: где ломается воронка',
    blog_name: 'MetricHit', published_timestamp_display: '12.08.2026 17:51:40',
    canonical_url_matches_public_url: true, robots: 'index,follow', page_accessible: true,
  },
});

export const oborotEditorialIntegrationUpdate = Object.freeze({
  semanticKey: 'publication.oborot_nakrutka_pf_business_2026_08_29', revision: 3, expectedPriorRevisions: [1, 2],
  title: 'Oborot.ru подключён к редакции MetricHit для ручного пакета',
  content: 'Oborot.ru подключён и проверен для редакции MetricHit только в режиме manual-package. Вход владельца в существующий аккаунт подтверждён; в доступном кабинете не обнаружены официальный API или self-service механизм автоматической публикации. Публикации остаются ручными и требуют отдельного одобрения владельца. Связанная подтверждённая публикация: https://oborot.ru/blogs/nakrutka-pf-i277755.html.',
  platform: 'Oborot.ru', canonicalUrl: 'https://oborot.ru/blogs/nakrutka-pf-i277755.html',
  publishedAt: '2026-08-29T00:00:00+03:00', reviewedAt: '2026-08-31T23:59:00.000Z',
  authority: 'direct_owner_authenticated_session_confirmation',
  verificationMethod: 'owner_authenticated_session_read_only_inspection',
  verifiedFacts: {
    editorial_connection: 'verified', workflow_mode: 'manual-package',
    connected_publication_url: 'https://oborot.ru/blogs/nakrutka-pf-i277755.html',
    official_publishing_api_exposed: false, self_service_automatic_publishing_exposed: false,
    external_publication_requires_owner_approval: true, session_data_stored: false,
  },
});

export const oborotInternetShopPublicationUpdate = Object.freeze({
  semanticKey: 'publication.oborot_internet_shop_daily_limit_2026_09_01', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed',
  title: 'Статья MetricHit опубликована на Oborot.ru',
  content: 'Статья «Накрутка ПФ для интернет-магазина: как выбрать запросы, категории и дневной лимит в Яндексе» опубликована на Oborot.ru 01.09.2026. Публичная страница: https://oborot.ru/blogs/nakrutka-pf-dlya-internet-magazina-kak-vybrat-zaprosy-kategorii-i-dnevnoj-limit-v-yandekse-i277848.html.',
  platform: 'Oborot.ru',
  canonicalUrl: 'https://oborot.ru/blogs/nakrutka-pf-dlya-internet-magazina-kak-vybrat-zaprosy-kategorii-i-dnevnoj-limit-v-yandekse-i277848.html',
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_provided_public_url',
  verifiedFacts: {
    published: true, publication_date: '2026-09-01',
    article_title: 'Накрутка ПФ для интернет-магазина: как выбрать запросы, категории и дневной лимит в Яндексе',
  },
});

export const tenchatInternetShopPublicationUpdate = Object.freeze({
  semanticKey: 'publication.tenchat_internet_shop_start_category_2026_09_01', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed',
  title: 'Статья MetricHit опубликована в TenChat',
  content: 'Статья «Накрутка ПФ для интернет-магазина: как выбрать стартовую категорию» опубликована в TenChat 01.09.2026. Публичная страница: https://tenchat.ru/media/6035722-nakrutka-pf-dlya-internetmagazina-kak-vybrat-startovuyu-kategoriyu. В публикации использована подтверждённая владельцем обложка из локального пакета TenChat.',
  platform: 'TenChat',
  canonicalUrl: 'https://tenchat.ru/media/6035722-nakrutka-pf-dlya-internetmagazina-kak-vybrat-startovuyu-kategoriyu',
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation_with_owner_provided_public_url', verificationMethod: 'owner_confirmation_with_owner_provided_public_url',
  verifiedFacts: {
    published: true, publication_date: '2026-09-01',
    article_title: 'Накрутка ПФ для интернет-магазина: как выбрать стартовую категорию',
    local_draft_path: 'work/social/tenchat/drafts/2026-09-01-oborot-nakrutka-pf-internet-shop.md',
    cover_asset_path: 'work/social/tenchat/assets/2026-09-01-online-store-category-planning-cover.png',
    cover_asset_sha256: '2d4ac5caf492867520e461b3f2d574280302ee6b134e48aeae38582a30bc51ff',
    cover_asset_dimensions: { width: 1536, height: 1024 },
    independent_fetch: 'not_performed',
  },
});

export const vkCommunityCoverPublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_community_cover_2026_09_01', revision: 2, expectedPriorRevisions: [1],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'Обложка сообщества MetricHit опубликована во VK',
  content: 'Владелец подтвердил публикацию обложки сообщества MetricHit во VK 01.09.2026. Локальный принятый файл: work/social/vk/assets/2026-09-01-metrichit-community-cover-owner-confirmed-published.png. Статус: owner_confirmed_published; отдельное внешнее действие в рамках этого обновления не выполнялось. Handoff для нового чата: обложка завершена; остаются описание сообщества, контакты без номера телефона, дальнейшее наполнение и актуализация закреплённого поста. Автоматизация браузера VK блокируется политикой платформы, но это не препятствие для владельца.',
  platform: 'VK', canonicalUrl: 'https://vk.ru/metrichit',
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, publication_date: '2026-09-01',
    community_url: 'https://vk.ru/metrichit',
    local_asset_path: 'work/social/vk/assets/2026-09-01-metrichit-community-cover-owner-confirmed-published.png',
    source_file_path: 'C:/Users/Administrator/Downloads/Изображение Codex 1 сент. 2026 г., 02_25_27.png',
    asset_sha256: '1bad626ae2e24623538b2696941611f87a0bd5485c70323f372106d18c1caee8',
    asset_dimensions: { width: 1983, height: 793 },
    visual_standard: 'dark graphite, cyan-blue and fire-orange accents',
    safe_zone_standard: 'No important content in the top crop and no text or CTA under the lower-left avatar; wordmark placement follows the live VK safe-zone preview.',
    accepted_headline: 'ПОВЕДЕНЧЕСКОЕ ПРОДВИЖЕНИЕ САЙТОВ В ЯНДЕКСЕ',
    headline_reuse_policy: 'accepted visual, not a required reusable marketing-copy formula',
    installation_evidence: 'owner_confirmed_published',
    new_chat_handoff: {
      completed: 'VK community cover published after owner confirmation',
      open: ['community description', 'contacts without phone number', 'further community filling', 'pinned-post update'],
      browser_automation: 'policy_blocked_not_owner_blocker',
    },
  },
});

export const vkPfYandexServiceUpdate = Object.freeze({
  semanticKey: 'publication.vk_service_nakrutka_pf_yandex_2026_09_01', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed_updated',
  title: 'Услуга MetricHit «Накрутка ПФ в Яндекс» обновлена во VK',
  content: 'Владелец подтвердил актуальное состояние услуги MetricHit «Накрутка ПФ в Яндекс» во VK 01.09.2026. Публичная страница: https://vk.ru/market/product/prodvizhenie-saytov-v-yandekse-240809922-13528771?ref=community_showcase&ref_source=link. Указана цена от 1 000 ₽; в карточке установлена новая квадратная обложка и отображается описание услуги. Внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK',
  canonicalUrl: 'https://vk.ru/market/product/prodvizhenie-saytov-v-yandekse-240809922-13528771?ref=community_showcase&ref_source=link',
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_confirmation_with_owner_provided_public_url_and_screenshot',
  verificationMethod: 'owner_provided_public_url_and_screenshot',
  verifiedFacts: {
    updated: true, confirmation_date: '2026-09-01',
    service_title: 'Накрутка ПФ в Яндекс', price_from_rub: 1000,
    card_cover: 'new_square_cover', description_visible: true,
    external_action_performed_in_this_update: false,
  },
});

export const vkYandexMapsServicePublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_service_nakrutka_yandex_maps_2026_09_01', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'Услуга MetricHit «Накрутка в Яндекс Картах» опубликована во VK',
  content: 'Владелец подтвердил публикацию услуги MetricHit «Накрутка в Яндекс Картах» во VK 01.09.2026. Цена от 5 000 ₽. В карточке установлена вертикальная обложка с текстом «НАКРУТКА В ЯНДЕКС КАРТАХ». Опубликованное описание: «Накрутка в Яндекс Картах для бизнеса, которому важно усилить присутствие в локальной выдаче. Работаем с карточкой организации и спросом в нужном регионе. Перед стартом уточняем задачу, город и текущую ситуацию по карточке. Стоимость — от 5 000 ₽. Итоговый объём подбирается под вашу задачу. Напишите в сообщения сообщества, чтобы обсудить запуск.» Публичный URL владельцем не предоставлен; внешний адрес не указан. Внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_screenshot_confirmation', verificationMethod: 'owner_provided_screenshot',
  verifiedFacts: {
    published: true, confirmation_date: '2026-09-01',
    service_title: 'Накрутка в Яндекс Картах', price_from_rub: 5000,
    card_cover: 'vertical_cover', card_cover_text: 'НАКРУТКА В ЯНДЕКС КАРТАХ',
    description: 'Накрутка в Яндекс Картах для бизнеса, которому важно усилить присутствие в локальной выдаче. Работаем с карточкой организации и спросом в нужном регионе. Перед стартом уточняем задачу, город и текущую ситуацию по карточке. Стоимость — от 5 000 ₽. Итоговый объём подбирается под вашу задачу. Напишите в сообщения сообщества, чтобы обсудить запуск.',
    public_url: null, public_url_status: 'not_provided_by_owner',
    external_action_performed_in_this_update: false,
  },
});

export const vkWebsiteCreationServicePublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_service_website_creation_2026_09_01', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'Услуга MetricHit «Создание сайтов» опубликована во VK',
  content: 'Владелец подтвердил публикацию услуги MetricHit «Создание сайтов» во VK 01.09.2026. Цена от 10 000 ₽. Для карточки выбран второй визуальный вариант; имя локального файла не зафиксировано. Опубликованное описание: «Создание сайтов для бизнеса: лендинги, корпоративные сайты, каталоги и интернет-магазины. Разрабатываем структуру, дизайн и адаптивную версию под мобильные устройства. Настраиваем формы заявок, базовую SEO-подготовку, аналитику и интеграции, необходимые для работы сайта. Перед стартом уточняем задачи бизнеса, целевую аудиторию, услуги и желаемый результат. Подбираем подходящий формат сайта и согласовываем состав работ. Стоимость — от 10 000 ₽. Итоговая цена зависит от типа сайта, количества страниц, функционала и готовности материалов. Напишите в сообщения сообщества — обсудим задачу и подготовим предложение.» Публичный URL владельцем не предоставлен; внешний адрес не указан. Внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, confirmation_date: '2026-09-01',
    service_title: 'Создание сайтов', price_from_rub: 10000,
    card_cover: 'owner_selected_second_visual_variant',
    description: 'Создание сайтов для бизнеса: лендинги, корпоративные сайты, каталоги и интернет-магазины.\n\nРазрабатываем структуру, дизайн и адаптивную версию под мобильные устройства. Настраиваем формы заявок, базовую SEO-подготовку, аналитику и интеграции, необходимые для работы сайта.\n\nПеред стартом уточняем задачи бизнеса, целевую аудиторию, услуги и желаемый результат. Подбираем подходящий формат сайта и согласовываем состав работ.\n\nСтоимость — от 10 000 ₽. Итоговая цена зависит от типа сайта, количества страниц, функционала и готовности материалов.\n\nНапишите в сообщения сообщества — обсудим задачу и подготовим предложение.',
    public_url: null, public_url_status: 'not_provided_by_owner',
    external_action_performed_in_this_update: false,
  },
});

export const vkPrelaunchPfChecklistPublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_prelaunch_pf_checklist', revision: 2, expectedPriorRevisions: [1],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: '7 вещей, которые нужно проверить на сайте до запуска ПФ',
  content: 'Владелец подтвердил публикацию во VK 12.08.2026 поста «7 вещей, которые нужно проверить на сайте до запуска ПФ». В нём приведён чек-лист из семи пунктов: техническая доступность и ошибки, соответствие запроса посадочной странице, скорость и мобильная версия, доступные контакты, элементы доверия, старт с запросов в зоне видимости, Яндекс Метрика и цели ключевых действий. ПФ усиливают подготовленные страницы, но не заменяют SEO и не исправляют слабый сайт. Публичный URL владельцем не предоставлен; пост не закреплён. Внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-08-12T00:00:00.000Z', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, publication_date: '2026-08-12',
    post_title: '7 вещей, которые нужно проверить на сайте до запуска ПФ',
    checklist: ['technical_availability_and_errors', 'query_to_landing_page_relevance', 'page_speed_and_mobile', 'accessible_contacts', 'trust_elements', 'start_with_queries_in_visibility_zone', 'yandex_metrica_and_key_action_goals'],
    pf_do_not_replace_seo_or_fix_weak_sites: true,
    public_url: null, public_url_status: 'not_provided_by_owner', is_pinned: false,
    external_action_performed_in_this_update: false,
  },
});

export const vkAugust16PfServicesIncidentPublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_august_16_pf_services_incident', revision: 2, expectedPriorRevisions: [1],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'Почему 16 августа не работали многие ПФ-сервисы',
  content: 'Владелец подтвердил публикацию во VK 17.08.2026 поста «Почему 16 августа не работали многие ПФ-сервисы». В сообщении об инциденте за 16 августа указано: панель оставалась доступна, выполнение кликов было временно приостановлено; предварительно наиболее вероятной причиной названы региональные ограничения мобильного интернета. Версия о масштабном обновлении антифрода Яндекса проверялась, но публичных подтверждений не обнаружено. Работа сервиса была восстановлена в ночь на 17 августа; за невыполненные клики деньги не списывались, затронутым клиентам начислялись по 300 компенсационных кликов. Публичный URL владельцем не предоставлен; пост не закреплён. Внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-08-17T00:00:00.000Z', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, publication_date: '2026-08-17',
    post_title: 'Почему 16 августа не работали многие ПФ-сервисы',
    incident_date: '2026-08-16', panel_accessible: true, click_execution: 'temporarily_paused',
    preliminary_likely_cause: 'regional_mobile_internet_restrictions',
    yandex_antifraud_update_public_confirmation: false,
    service_restored: 'during_night_to_2026-08-17', incomplete_clicks_charged: false,
    compensation_clicks_to_affected_clients: 300,
    public_url: null, public_url_status: 'not_provided_by_owner', is_pinned: false,
    external_action_performed_in_this_update: false,
  },
});

export const vkMetricHitPfProductOverviewPublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_metrichit_pf_product_overview', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'MetricHit — продвижение сайтов в Яндексе с помощью поведенческих факторов',
  content: 'Владелец подтвердил публикацию во VK 12.08.2026 поста «MetricHit — продвижение сайтов в Яндексе с помощью поведенческих факторов». Это действующий продуктовый пост, а не приветственный и не закреплённый: он описывает настройку сайта, региона, запросов, лимитов кликов и расписания, отслеживание позиций, статистики и расходов, оплату только за выполненные клики без фиксированной абонентской платы, а также 1 000 тестовых кликов после регистрации и обращения в поддержку. В посте отдельно указано, что ПФ не заменяют SEO и не исправляют слабый сайт. Публичный URL владельцем не предоставлен. Внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-08-12T00:00:00.000Z', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, publication_date: '2026-08-12',
    post_title: 'MetricHit — продвижение сайтов в Яндексе с помощью поведенческих факторов',
    product_capabilities: ['site', 'region', 'queries', 'click_limits', 'schedule', 'positions', 'statistics', 'spend'],
    charges_only_for_completed_clicks: true, fixed_subscription_fee: false,
    test_clicks_after_registration_and_support_contact: 1000,
    pf_do_not_replace_seo_or_fix_weak_sites: true,
    post_role: 'existing_product_presentation', is_welcome_post: false, is_pinned: false,
    public_url: null, public_url_status: 'not_provided_by_owner',
    external_action_performed_in_this_update: false,
  },
});

export const vkInternetShopCategoryFirstLaunchPublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_internet_shop_category_first_launch_2026_09_01', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'Накрутка ПФ интернет-магазина: как подготовить первый запуск для категории',
  content: 'Владелец подтвердил публикацию во VK 01.09.2026 поста «Накрутка ПФ интернет-магазина: как подготовить первый запуск для категории». Публичный URL не предоставлен. Финальная обложка — owner-confirmed asset без логотипа, текста и стрелок; отдельное внешнее действие в рамках этого обновления не выполнялось.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-09-01T00:00:00+03:00', reviewedAt: '2026-09-01T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, publication_date: '2026-09-01',
    post_title: 'Накрутка ПФ интернет-магазина: как подготовить первый запуск для категории',
    local_post_path: 'work/social/vk/drafts/2026-09-01-oborot-internet-shop-category-launch.md',
    publication_status: 'owner_confirmed_published',
    public_url: null, public_url_status: 'not_provided_by_owner', is_pinned: false,
    target_queries: [
      'накрутка ПФ интернет-магазина',
      'поведенческие факторы для интернет-магазина',
      'продвижение категорий интернет-магазина в Яндексе',
      'как выбрать запросы для накрутки ПФ',
      'какие запросы продвигать ПФ',
      'как распределить запросы по страницам',
      'один запрос — одна страница SEO',
      'релевантная страница для запроса',
      'настройка проекта ПФ',
      'дневной лимит кликов ПФ',
    ],
    cover_asset_path: 'work/social/vk/assets/2026-09-01-online-store-category-first-launch-cover-owner-confirmed-published.png',
    cover_asset_sha256: '2f84159434661e353827ca06a2208a8e486b89cf6459251c508c9e728a9ed314',
    cover_asset_dimensions: { width: 1122, height: 1402 },
    cover_visual_characteristics: ['deep_graphite', 'glass_panels', 'cyan_blue_accents', 'warm_orange_accents', 'no_logo', 'no_text', 'no_arrow'],
    external_action_performed_in_this_update: false,
  },
});

export const vkBusinessSiteLaunchReadinessPublicationUpdate = Object.freeze({
  semanticKey: 'publication.vk_business_site_launch_readiness_2026_09_02', revision: 1, expectedPriorRevisions: [],
  allowCreate: true, publicationStatus: 'owner_confirmed_published',
  title: 'Накрутка ПФ для бизнеса: как запустить накрутку ПФ, когда сайт готов',
  content: 'Владелец подтвердил публикацию во VK 02.09.2026 статьи «Накрутка ПФ для бизнеса: как запустить накрутку ПФ, когда сайт готов». Публичный URL владельцем не предоставлен. Для этого материала зафиксирован точный список целевых запросов для будущего отдельного рассмотрения ПФ-продвижения; данная запись не подтверждает запуск кампании или независимую индексацию.',
  platform: 'VK', canonicalUrl: null,
  publishedAt: '2026-09-02T00:00:00.000Z', reviewedAt: '2026-09-02T00:00:00.000Z',
  authority: 'direct_owner_publication_confirmation', verificationMethod: 'owner_confirmation',
  verifiedFacts: {
    published: true, publication_date: '2026-09-02',
    post_title: 'Накрутка ПФ для бизнеса: как запустить накрутку ПФ, когда сайт готов',
    local_post_path: 'work/social/vk/drafts/2026-09-02-pf-business-site-launch-readiness.md',
    cover_asset_path: 'work/social/vk/assets/2026-09-02-pf-business-site-launch-readiness-cover.png',
    cover_asset_sha256: '8284cf0ab67b9fd8c9fc4390aa9cc015315ac675ab9cdbc6cdcee13d6eb2fe76',
    public_url: null, public_url_status: 'not_provided_by_owner',
    pf_promotion_target_queries: [
      'как запустить накрутку ПФ',
      'накрутка ПФ самостоятельно',
      'настройка проекта ПФ',
      'когда начинать накрутку ПФ',
      'что проверить перед накруткой ПФ',
      'как выбрать запросы для накрутки ПФ',
      'какие запросы продвигать ПФ',
      'релевантная страница для запроса',
      'аналитика накрутки ПФ',
    ],
    pf_promotion_recording_scope: 'this_article_only',
    pf_campaign_execution_evidence: 'not_recorded_by_this_publication_confirmation',
    independent_yandex_indexation: 'not_performed',
    external_action_performed_in_this_update: false,
  },
});

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const command = process.argv[2] ?? 'sostav-first-article';
  const databasePath = process.argv[3] ? resolve(process.argv[3]) : defaultDatabasePath;
  const update = command === 'oborot-editorial-integration' ? oborotEditorialIntegrationUpdate
    : command === 'oborot-internet-shop-publication' ? oborotInternetShopPublicationUpdate
      : command === 'tenchat-internet-shop-publication' ? tenchatInternetShopPublicationUpdate
          : command === 'vk-community-cover-publication' ? vkCommunityCoverPublicationUpdate
          : command === 'vk-pf-yandex-service' ? vkPfYandexServiceUpdate
            : command === 'vk-yandex-maps-service-publication' ? vkYandexMapsServicePublicationUpdate
              : command === 'vk-website-creation-service-publication' ? vkWebsiteCreationServicePublicationUpdate
                : command === 'vk-prelaunch-pf-checklist-publication' ? vkPrelaunchPfChecklistPublicationUpdate
                  : command === 'vk-august-16-pf-services-incident-publication' ? vkAugust16PfServicesIncidentPublicationUpdate
                    : command === 'vk-metrichit-pf-product-overview-publication' ? vkMetricHitPfProductOverviewPublicationUpdate
                      : command === 'vk-internet-shop-category-first-launch-publication' ? vkInternetShopCategoryFirstLaunchPublicationUpdate
                        : command === 'vk-business-site-launch-readiness-publication' ? vkBusinessSiteLaunchReadinessPublicationUpdate : sostavFirstArticleUpdate;
  if (!['sostav-first-article', 'oborot-editorial-integration', 'oborot-internet-shop-publication', 'tenchat-internet-shop-publication', 'vk-community-cover-publication', 'vk-pf-yandex-service', 'vk-yandex-maps-service-publication', 'vk-website-creation-service-publication', 'vk-prelaunch-pf-checklist-publication', 'vk-august-16-pf-services-incident-publication', 'vk-metrichit-pf-product-overview-publication', 'vk-internet-shop-category-first-launch-publication', 'vk-business-site-launch-readiness-publication'].includes(command)) {
    throw new Error('Usage: update-publication-memory.mjs <sostav-first-article|oborot-editorial-integration|oborot-internet-shop-publication|tenchat-internet-shop-publication|vk-community-cover-publication|vk-pf-yandex-service|vk-yandex-maps-service-publication|vk-website-creation-service-publication|vk-prelaunch-pf-checklist-publication|vk-august-16-pf-services-incident-publication|vk-metrichit-pf-product-overview-publication|vk-internet-shop-category-first-launch-publication|vk-business-site-launch-readiness-publication> [databasePath]');
  }
  console.log(JSON.stringify(updatePublicationMemory(databasePath, update)));
}
