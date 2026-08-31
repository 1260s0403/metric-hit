import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-publication-policy-and-timeweb-draft-2026-08-29.md';
const owner = 'owner';
const reviewedAt = '2026-08-29T00:00:00.000Z';
const contourReviewedAt = '2026-08-31T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-editorial-publication-policy:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

function approve(database, candidateId, candidateReviewedAt = reviewedAt) {
  const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
  if (candidate.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, candidateReviewedAt, `Одобрено прямым решением владельца MetricHit от ${candidateReviewedAt.slice(0, 10).split('-').reverse().join('.')}.`, candidateReviewedAt, candidateId);
}

export function applyEditorialPublicationPolicyAndTimewebDraft(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const policyTitle = 'Правила подготовки статей MetricHit';
  const policyContent = 'Статьи MetricHit оригинальны, сохраняют подтверждённые кейсы и цифры, естественно используют утверждённые ключи и содержат не менее 9 000 знаков содержательного текста. Тарифная сетка, пороги пополнения и таблицы тарифов запрещены; допустимо контекстное упоминание «от 0,15 ₽ за клик». Служебные SEO-метки не публикуются. В статье четыре естественные ссылки на https://go.mtrhit.ru/: в начале, две внутри и в финале/CTA. Нужны две оригинальные эффектные иллюстрации, соответствующие деловой или технической площадке. Заявка на авторство описывает регулярное экспертное направление MetricHit, а не одну статью.';
  const draftTitle = 'Черновик Timeweb Cloud: «Сервис накрутки ПФ: как SEO-команде выстроить управляемое продвижение в Яндексе»';
  const draftContent = 'Материал сохранён как article в канале articles для Timeweb Cloud. Статус: draft/unpublished; публичный URL отсутствует. Материал не публиковался и не является результатом.';
  const registryTitle = 'Текущее состояние editorial-реестра MetricHit';
  const registryContent = 'Историческая запись о пустых реестрах редакции больше не описывает текущее состояние: зарегистрирован один article-материал для Timeweb Cloud со статусом draft. Публикаций и результатов в реестре нет; внешний URL отсутствует.';
  const contourTitle = 'Редакционный контур MetricHit: завершённый фундамент и следующий research-MVP';
  const contourContent = 'Внутри собственного project.sqlite MetricHit завершён редакционный контур: foundation (`39079d11`), разделение направлений articles/social (`edac95db`) и workflow материалов (`1336b461`). Текущая schema редакции — v6; в реестре есть один article-материал для Timeweb Cloud со статусом draft, а публикаций и результатов нет. Articles и social используют общую editorial-память, но получают изолированную выборку своего направления; производный social-материал связан с исходной статьёй без дублирования. Workflow: idea → plan → draft → review → published → result, с возвратом review → draft; published требует подтверждения владельца или проверяемого URL, result — подтверждённой публикации. Следующий, ещё не реализованный этап — on-demand research-MVP: реестр надёжных источников, датированные research-находки, дедупликация и оценка релевантности к семантическому ядру и editorial-реестру, краткий research-brief по запросу. Scheduled monitoring, автопубликация, UI редакции и маркетинговые skills не входят в этот этап и требуют отдельных решений владельца. Полный central backup успешно создан: `MetricHit-backup-20260831T082016Z`; штатный restore-test пройден. Имеются несвязанные UI E2E failures; они не относятся к editorial-поставкам.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-29' });
  const policyData = JSON.stringify({ applies_to: ['articles', 'author_applications'], minimum_content_characters: 9000, prohibited: ['tariff_grid', 'topup_thresholds', 'tariff_tables', 'service_seo_labels', 'bare_urls', 'link_spam', 'copied_or_mechanically_reordered_text'], permitted_minimum_price: 'от 0,15 ₽ за клик', landing: 'https://go.mtrhit.ru/', landing_link_distribution: ['beginning', 'body_1', 'body_2', 'final_cta'], required_original_illustrations: 2, evidence: { path: decisionPath } });
  const draftData = JSON.stringify({ channel: 'articles', platform: 'Timeweb Cloud', publication_status: 'draft', public_url: null, final_article_path: 'work/articles/drafts/2026-08-29-timeweb-cloud-pf-service-selection.md', evidence: { path: decisionPath } });
  const registryData = JSON.stringify({ articles_materials: 1, articles_drafts: 1, articles_publications: 0, articles_results: 0, evidence: { path: decisionPath } });
  const contourData = JSON.stringify({ project_id: '00000000-0000-4000-a000-000000000102', editorial_schema_version: 6, completed_commits: ['39079d11d7e30451fa789e5214e4a43acb66ef62', 'edac95db67d2ef7f43325926a504f04adfb07177', '1336b46131b12ef6d8fe6bbbce4a025e3d7b2d7a'], tracks: ['articles', 'social'], content_registry: { articles_materials: 1, articles_drafts: 1, articles_publications: 0, articles_results: 0 }, workflow: { states: ['idea', 'plan', 'draft', 'review', 'published', 'result'], rework: 'review_to_draft', publication_requires: ['owner_confirmation', 'verifiable_url'], result_requires: 'confirmed_publication' }, next_research_mvp: { status: 'planned_not_implemented', scope: ['source_registry', 'dated_research_findings', 'deduplication_and_relevance_to_semantic_core_and_editorial_registry', 'on_demand_research_brief'], excludes: ['scheduled_monitoring', 'autopublishing'] }, deferred: ['editorial_ui', 'marketing_skills'], known_technical_context: ['unrelated_operator_panel_ui_e2e_failures'], backup_restore: { backup_id: 'MetricHit-backup-20260831T082016Z', restore_test: 'passed', operator_panel_url: 'http://127.0.0.1:8778/', operator_panel_http_status: 200 }, revision: 2, supersedes_candidate_id: 'd550a526-221e-4b4f-a9ca-07ada1372390', supersedes_semantic_revision: 1, evidence: { path: decisionPath, verified_at: '2026-08-31T00:00:00.000Z' } });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const policyId = stableUuid('candidate:content.editorial_article_preparation_policy');
  const draftId = stableUuid('candidate:publication.timeweb_cloud_draft_2026_08_29');
  const registryId = stableUuid('candidate:editorial.registry_current_state');
  const contourId = stableUuid('candidate:editorial.metrichit_contour_and_research_mvp:revision:2');
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-29', 'internal')").run(sourceId, policyTitle, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(documentId, policyTitle, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(versionId, documentId, policyTitle, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', 'content.editorial_article_preparation_policy', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(policyId, policyTitle, policyContent, policyData, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'publication_state', 'publication.timeweb_cloud_draft_2026_08_29', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(draftId, draftTitle, draftContent, draftData, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', 'editorial.registry_current_state', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(registryId, registryTitle, registryContent, registryData, sourceId, owner).changes);
    const contourRevisions = database.prepare("SELECT coalesce(json_extract(data_json, '$.revision'), 0) AS revision FROM memory_candidates WHERE semantic_key='editorial.metrichit_contour_and_research_mvp' AND status IN ('pending', 'approved') AND id<>?").all(contourId);
    if (contourRevisions.some(({ revision }) => ![0, 1].includes(Number(revision)))) throw new Error('Unexpected editorial contour revision blocks revision 2');
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', 'editorial.metrichit_contour_and_research_mvp', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(contourId, contourTitle, contourContent, contourData, sourceId, owner).changes);
    approve(database, policyId);
    approve(database, draftId);
    approve(database, registryId);
    approve(database, contourId, contourReviewedAt);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(policyId), { type: 'editorial_rule', semantic_key: 'content.editorial_article_preparation_policy', title: policyTitle, content: policyContent, data_json: policyData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'editorial article policy');
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(draftId), { type: 'publication_state', semantic_key: 'publication.timeweb_cloud_draft_2026_08_29', title: draftTitle, content: draftContent, data_json: draftData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'Timeweb draft state');
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(registryId), { type: 'decision', semantic_key: 'editorial.registry_current_state', title: registryTitle, content: registryContent, data_json: registryData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'editorial registry current state');
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(contourId), { type: 'decision', semantic_key: 'editorial.metrichit_contour_and_research_mvp', title: contourTitle, content: contourContent, data_json: contourData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: contourReviewedAt }, 'editorial contour revision');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, policyId, draftId, registryId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied editorial publication policy and Timeweb draft: ${JSON.stringify(applyEditorialPublicationPolicyAndTimewebDraft(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
