import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/tenchat-publication-and-indexation-continuity-2026-08-30.md';
const owner = 'owner';
const reviewedAt = '2026-08-30T09:00:00.000Z';
const tenchatPolicyReviewedAt = '2026-08-31T00:00:00.000Z';
const projectId = '00000000-0000-4000-a000-000000000102';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-tenchat-continuity:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyTenchatPublicationAndIndexationContinuity(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');

  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_continuity_request_and_independent_public_page_verification',
    decision_date: '2026-08-30',
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const tenchatPolicySourceId = stableUuid('source:editorial.tenchat_format_and_search_policy:2026-08-31');
  const tenchatPolicyDocumentId = stableUuid('document:editorial.tenchat_format_and_search_policy:2026-08-31');
  const tenchatPolicyVersionId = stableUuid('document-version:editorial.tenchat_format_and_search_policy:2026-08-31');
  const tenchatPolicyId = stableUuid('candidate:editorial.tenchat_format_and_search_policy');
  const taskId = stableUuid('task:operations.tenchat_pf_promotion_setup');

  const tenchatPolicyTitle = 'Редакционное правило TenChat: объём и поисковая подача';
  const tenchatPolicyContent = 'Для поста MetricHit в TenChat действует технический максимум 7 000 знаков, включая пробелы и пунктуацию. Рабочий целевой объём — 4 000–5 500 знаков; объём не является самоцелью, поэтому лимит не заполняется ради длины. Материал строится вокруг одного поискового интента. Основной ключ естественно присутствует в заголовке и начале текста; далее тема раскрывается через практические объяснения, примеры или кейсы и 2–4 уместные ссылки. Переоптимизация — повторение ключей, ссылочный спам или текст, написанный для роботов вместо читателя, — не допускается.';
  const tenchatPolicyData = JSON.stringify({
    platform: 'TenChat',
    maximum_characters: 7000,
    character_count_includes: ['spaces', 'punctuation'],
    target_characters: { minimum: 4000, maximum: 5500 },
    length_is_not_a_goal: true,
    primary_search_intents: 1,
    primary_keyword_placement: ['title', 'opening'],
    required_content_development: ['practical_explanations', 'examples_or_cases'],
    appropriate_links: { minimum: 2, maximum: 4 },
    prohibited: ['keyword_repetition', 'link_spam', 'robot_oriented_text'],
    evidence: { path: decisionPath },
  });
  const tenchatPolicyMetadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-31',
  });

  const publications = [
    {
      semanticKey: 'publication.tenchat_first_post_2026_08_30',
      revision: 1,
      allowedPriorRevisions: [],
      title: 'Первая публикация MetricHit в TenChat',
      content: 'Первая публикация MetricHit в TenChat независимо проверена 30.08.2026: «Накрутка ПФ в Яндексе: как управлять продвижением по запросам, региону и бюджету». Публичная страница содержит согласованные заголовок, текст, обложку 4:5, ссылку «Накрутка ПФ», ссылку go.mtrhit.ru и хештеги. URL: https://tenchat.ru/media/6013324-nakrutka-pf-v-yandekse-kak-upravlyat-prodvizheniyem-po-zaprosam-regionu-i-byudzhetu.',
      data: {
        platform: 'TenChat',
        publication_date: '2026-08-30',
        publication_status: 'independently_verified',
        public_url: 'https://tenchat.ru/media/6013324-nakrutka-pf-v-yandekse-kak-upravlyat-prodvizheniyem-po-zaprosam-regionu-i-byudzhetu',
        title: 'Накрутка ПФ в Яндексе: как управлять продвижением по запросам, региону и бюджету',
        local_material_path: 'work/social/tenchat/drafts/2026-08-29-first-publication.md',
        asset_path: 'work/social/tenchat/assets/2026-08-29-metrichit-tenchat-pf-yandex-1080x1350.png',
        asset_format: { width: 1080, height: 1350, aspect_ratio: '4:5' },
        verified_elements: ['title', 'text', 'cover', 'anchor_nakrutka_pf', 'go_mtrhit_ru_link', 'hashtags'],
        promotion_campaign_status: 'not_started_requires_separate_owner_command',
        semantic_subset_location: 'work/social/tenchat/drafts/2026-08-29-first-publication.md',
        evidence: { path: decisionPath },
        revision: 1,
      },
    },
    {
      semanticKey: 'publication.sostav_nakrutka_pf_2026_08_29',
      revision: 3,
      allowedPriorRevisions: [0, 2],
      title: 'Публикация «Накрутка ПФ» на Sostav / SBlogs',
      content: 'Публикация «Накрутка ПФ» на Sostav / SBlogs от 29.08.2026 доступна по URL https://www.sostav.ru/blogs/293151/104675. Проверка 30.08.2026 подтвердила индексацию Яндексом точным url:-запросом: один результат с заголовком «Накрутка ПФ»; страница разрешает index, follow, canonical корректный. Индексация Google не подтверждена из-за anti-automation.',
      data: {
        platform: 'Sostav / SBlogs',
        publication_date: '2026-08-29',
        publication_status: 'confirmed',
        public_url: 'https://www.sostav.ru/blogs/293151/104675',
        final_article_path: 'work/articles/published/2026-08-29-sostav-nakrutka-pf.md',
        indexation_check_date: '2026-08-30',
        yandex_indexation: { status: 'confirmed', method: 'exact_url_query', result_count: 1, result_title: 'Накрутка ПФ' },
        page_directives: { robots: 'index, follow', canonical: 'correct' },
        google_indexation: { status: 'not_confirmed', reason: 'anti_automation' },
        evidence: { path: decisionPath },
        revision: 3,
        supersedes_semantic_revision: 2,
      },
    },
    {
      semanticKey: 'publication.oborot_nakrutka_pf_business_2026_08_29',
      revision: 2,
      allowedPriorRevisions: [1],
      title: 'Публикация «Накрутка ПФ: как бизнесу управлять поисковым продвижением и бюджетом» на Oborot.ru',
      content: 'Публикация на Oborot.ru доступна по URL https://oborot.ru/blogs/nakrutka-pf-i277755.html; заголовок страницы «Накрутка ПФ | Oborot.ru», noindex не обнаружен. Проверка 30.08.2026 не подтвердила индексацию Яндексом из-за SmartCaptcha и отсутствия точного результата в доступном поиске. Индексация Google также не подтверждена из-за anti-automation.',
      data: {
        platform: 'Oborot.ru',
        publication_date: '2026-08-29',
        publication_status: 'confirmed',
        public_url: 'https://oborot.ru/blogs/nakrutka-pf-i277755.html',
        final_article_path: 'work/articles/published/2026-08-29-oborot-nakrutka-pf-business.md',
        indexation_check_date: '2026-08-30',
        page_access: { status: 'available', title: 'Накрутка ПФ | Oborot.ru', noindex_detected: false },
        yandex_indexation: { status: 'not_confirmed', reasons: ['smartcaptcha', 'no_exact_result_in_accessible_search'] },
        google_indexation: { status: 'not_confirmed', reason: 'anti_automation' },
        evidence: { path: decisionPath },
        revision: 2,
        supersedes_semantic_revision: 1,
      },
    },
  ];

  const taskTitle = 'Настроить ПФ-продвижение опубликованной TenChat-страницы';
  const taskContent = 'После отдельной команды владельца использовать сохранённый operational semantic subset из 44 запросов для настройки ПФ-продвижения опубликованной TenChat-страницы. Кампания ещё не запускалась. Эта operational continuity не заменяет стратегические этапы research-MVP и маркетинговых skills.';
  const taskData = JSON.stringify({
    priority: 'operational_next',
    due_date: null,
    standalone: true,
    project_id: projectId,
    scope: 'tenchat_pf_promotion',
    public_url: publications[0].data.public_url,
    semantic_subset_location: publications[0].data.semantic_subset_location,
    campaign_status: 'not_started',
    requires_separate_owner_command: true,
  });

  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, tasks: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    for (const publication of publications) {
      const candidateId = stableUuid(`candidate:${publication.semanticKey}:revision:${publication.revision}`);
      const existing = database.prepare("SELECT id, coalesce(json_extract(data_json, '$.revision'), 0) AS revision FROM memory_candidates WHERE semantic_key = ? AND status IN ('pending', 'approved') AND id <> ?").all(publication.semanticKey, candidateId);
      for (const row of existing) {
        if (!publication.allowedPriorRevisions.includes(Number(row.revision))) {
          throw new Error(`Semantic duplicate or unexpected evolution blocks ${publication.semanticKey} revision ${row.revision}`);
        }
      }
      const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, publication.semanticKey);
      if (conflict) throw new Error(`Open memory conflict blocks ${publication.semanticKey}`);
    }
    const policyDuplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get('editorial.tenchat_format_and_search_policy', tenchatPolicyId);
    if (policyDuplicate) throw new Error('Semantic duplicate blocks TenChat editorial policy');
    const policyConflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(tenchatPolicyId, 'editorial.tenchat_format_and_search_policy');
    if (policyConflict) throw new Error('Open memory conflict blocks TenChat editorial policy');

    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-30', 'internal')").run(sourceId, 'Continuity публикаций TenChat, Sostav и Oborot', `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-30', 'internal', 1)").run(documentId, 'Continuity публикаций TenChat, Sostav и Oborot', decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-30', 'internal', 1)").run(versionId, documentId, 'Continuity публикаций TenChat, Sostav и Oborot', decision, metadata, sourceId, owner).changes);
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-31', 'internal')").run(tenchatPolicySourceId, tenchatPolicyTitle, `Repository file: ${decisionPath}`, tenchatPolicyMetadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-31', 'internal', 1)").run(tenchatPolicyDocumentId, tenchatPolicyTitle, decision, tenchatPolicyMetadata, tenchatPolicySourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-31', 'internal', 1)").run(tenchatPolicyVersionId, tenchatPolicyDocumentId, tenchatPolicyTitle, decision, tenchatPolicyMetadata, tenchatPolicySourceId, owner).changes);

    for (const publication of publications) {
      const candidateId = stableUuid(`candidate:${publication.semanticKey}:revision:${publication.revision}`);
      const data = JSON.stringify(publication.data);
      created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'publication_state', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-30', 'internal', 1)").run(candidateId, publication.semanticKey, publication.title, publication.content, data, sourceId, owner).changes);
      const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(candidateId);
      if (candidate?.status === 'pending') {
        database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым поручением владельца о continuity от 30.08.2026 и доступными независимыми проверками публичных страниц.', reviewedAt, candidateId);
      }
      assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), { type: 'publication_state', semantic_key: publication.semanticKey, title: publication.title, content: publication.content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, `${publication.semanticKey} candidate`);
    }

    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', 'editorial.tenchat_format_and_search_policy', ?, ?, ?, 'pending', ?, ?, '2026-08-31', 'internal', 1)").run(tenchatPolicyId, tenchatPolicyTitle, tenchatPolicyContent, tenchatPolicyData, tenchatPolicySourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(tenchatPolicyId)?.status === 'pending') {
      database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, tenchatPolicyReviewedAt, 'Одобрено прямым поручением владельца от 31.08.2026.', tenchatPolicyReviewedAt, tenchatPolicyId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(tenchatPolicyId), { type: 'editorial_rule', semantic_key: 'editorial.tenchat_format_and_search_policy', title: tenchatPolicyTitle, content: tenchatPolicyContent, data_json: tenchatPolicyData, status: 'approved', source_id: tenchatPolicySourceId, reviewed_by: owner, reviewed_at: tenchatPolicyReviewedAt }, 'TenChat editorial policy');

    created.tasks += Number(database.prepare("INSERT OR IGNORE INTO tasks (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'standalone_task', ?, ?, ?, 'pending', ?, ?, '2026-08-30', 'internal', 1)").run(taskId, taskTitle, taskContent, taskData, sourceId, owner).changes);
    assertFields(database.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId), { type: 'standalone_task', title: taskTitle, content: taskContent, data_json: taskData, status: 'pending', source_id: sourceId, author: owner }, 'TenChat promotion task');
    if (!database.prepare('SELECT id FROM sources WHERE id = ?').get(sourceId)) throw new Error('Missing continuity source');
    if (!database.prepare('SELECT id FROM documents WHERE id = ?').get(documentId)) throw new Error('Missing continuity document');
    if (!database.prepare('SELECT id FROM document_versions WHERE id = ?').get(versionId)) throw new Error('Missing continuity document version');
    assertFields(database.prepare('SELECT * FROM sources WHERE id = ?').get(tenchatPolicySourceId), { data_json: tenchatPolicyMetadata, status: 'active' }, 'TenChat editorial policy source');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(tenchatPolicyDocumentId), { content: decision, data_json: tenchatPolicyMetadata, source_id: tenchatPolicySourceId, version: 1 }, 'TenChat editorial policy document');
    assertFields(database.prepare('SELECT * FROM document_versions WHERE id = ?').get(tenchatPolicyVersionId), { document_id: tenchatPolicyDocumentId, content: decision, data_json: tenchatPolicyMetadata, version: 1 }, 'TenChat editorial policy document version');

    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, tenchatPolicyId, taskId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`Applied TenChat publication and indexation continuity: ${JSON.stringify(applyTenchatPublicationAndIndexationContinuity(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
}
