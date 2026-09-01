import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/vk-post-writing-standard-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-01T00:00:00.000Z';
const semanticKey = 'editorial.vk_post_writing_standard';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-vk-post-writing-standard:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

export function applyVkPostWritingStandard(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Стандарт объёма и SEO-структуры новых VK-постов';
  const candidateContent = 'Для каждого нового публичного VK-поста MetricHit действует целевой объём основного текста 1 800–2 800 русских знаков без внутренней metadata и URL. Узкая новость или чек-лист допустимы в диапазоне 1 200–1 799 знаков только при полном решении одного интента и с зафиксированной в QA причиной; 3 000–4 000 знаков допустимы только для действительно нужного подробного практического разбора и тоже с причиной. Объём нельзя увеличивать только ради SEO; менее 1 200 и более 4 000 знаков не допускаются. Один утверждённый кластер, один интент и основной запрос обязательны: запрос естественно находится в заголовке и первом абзаце и обычно встречается два-три раза суммарно без keyword stuffing. Заголовок, начало, подзаголовки или чек-лист и практический вывод раскрывают ту же задачу. Структура обязательна: ясный заголовок, ответ в начале, полезные подзаголовки или чек-лист, конкретные практические детали, практический вывод и один естественный CTA. QA отклоняет воду, повторения и неподтверждённые SEO-обещания. Правило не обещает позицию и не требует проверять индексацию свежего черновика; Telegram, статьи и TenChat не затрагиваются.';
  const candidateData = JSON.stringify({
    platform: 'VK', applies_to: ['new_public_posts'], excluded_formats: ['telegram', 'article', 'tenchat'],
    body_character_count: {
      count_scope: 'russian_post_body_excluding_internal_metadata_and_urls', target: { minimum: 1800, maximum: 2800 },
      narrow_news_or_checklist_exception: { minimum: 1200, maximum: 1799, requires_single_intent_fully_solved: true, requires_qa_rationale: true },
      detailed_practical_breakdown_exception: { minimum: 3000, maximum: 4000, requires_genuine_practical_need: true, requires_qa_rationale: true },
      prohibited: ['below_1200', 'above_4000', 'length_for_seo_only'],
    },
    primary_query: { placements: ['headline', 'opening_paragraph'], expected_natural_mentions_total: { minimum: 2, maximum: 3 }, keyword_stuffing_prohibited: true },
    content_scope: { selected_cluster_count: 1, user_intent_count: 1, sections_serve_same_query_and_task: true },
    structure: ['clear_headline', 'opening_answers_query', 'useful_subheads_or_checklist', 'concrete_practical_details', 'practical_conclusion', 'one_natural_cta'],
    delivery_validation: ['vk_body_character_count', 'vk_semantic_structure'],
    prohibited: ['padding_or_repetition', 'unsupported_seo_claims', 'ranking_promise', 'fresh_draft_indexation_check'],
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-01' });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error('Semantic duplicate blocks VK post writing standard');
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error('Open memory conflict blocks VK post writing standard');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-01', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым указанием владельца MetricHit от 01.09.2026.', reviewedAt, candidateId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'editorial_rule', semantic_key: semanticKey, title, content: candidateContent, data_json: candidateData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'VK post writing standard candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: documentContent, data_json: metadata, source_id: sourceId, version: 1 }, 'VK post writing standard document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId, semanticKey };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied VK post writing standard: ${JSON.stringify(applyVkPostWritingStandard(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
