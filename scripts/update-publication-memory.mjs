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
  const canonicalUrl = requiredText(update.canonicalUrl, 'canonicalUrl');
  const publishedAt = requiredText(update.publishedAt, 'publishedAt');
  const reviewedAt = requiredText(update.reviewedAt, 'reviewedAt');
  if (!URL.canParse(canonicalUrl) || !/^https?:\/\//u.test(canonicalUrl)) throw new Error('canonicalUrl must be an http(s) URL');
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
  return { ...update, semanticKey, title, content, platform, canonicalUrl, publishedAt, reviewedAt,
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

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const command = process.argv[2] ?? 'sostav-first-article';
  const databasePath = process.argv[3] ? resolve(process.argv[3]) : defaultDatabasePath;
  const update = command === 'oborot-editorial-integration' ? oborotEditorialIntegrationUpdate
    : command === 'oborot-internet-shop-publication' ? oborotInternetShopPublicationUpdate
      : command === 'tenchat-internet-shop-publication' ? tenchatInternetShopPublicationUpdate
        : command === 'vk-community-cover-publication' ? vkCommunityCoverPublicationUpdate : sostavFirstArticleUpdate;
  if (!['sostav-first-article', 'oborot-editorial-integration', 'oborot-internet-shop-publication', 'tenchat-internet-shop-publication', 'vk-community-cover-publication'].includes(command)) {
    throw new Error('Usage: update-publication-memory.mjs <sostav-first-article|oborot-editorial-integration|oborot-internet-shop-publication|tenchat-internet-shop-publication|vk-community-cover-publication> [databasePath]');
  }
  console.log(JSON.stringify(updatePublicationMemory(databasePath, update)));
}
