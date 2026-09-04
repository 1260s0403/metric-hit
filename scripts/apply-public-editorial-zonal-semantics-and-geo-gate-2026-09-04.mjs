import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/public-editorial-zonal-semantics-and-geo-gate-2026-09-04.md';
const reviewedAt = '2026-09-04T00:00:00.000Z';
const owner = 'owner';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-editorial-zonal-semantics-geo-gate:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [key, value] of Object.entries(expected)) if (row[key] !== value) throw new Error(`${label}.${key} differs`);
}

export function applyPublicEditorialZonalSemanticsAndGeoGate(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Зонное распределение семантики и geo demand gate';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-04' });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const rules = [
    {
      key: 'content.public_editorial_target_query_volume_ladder_policy', revision: 2,
      title: 'Зонное распределение семантики новых статей вне Telegram',
      content: 'Для новых статей и лонгридов MetricHit вне Telegram применяется автоматическое зонное распределение семантики по актуальному утверждённому не-навигационному ядру из 302 запросов. Самый короткий базовый запрос выбранного кластера длиной 2–3 слова является главным ВЧ-маркером и размещается в H1 и первом абзаце. Коммерческие СЧ/НЧ запросы-модификаторы со словами «купить», «заказать» или «цена» размещаются в H2, а их количество контролируется лестницей объёма площадки. Обязательный смежный профессиональный LSI-лексикон размещается только в H3, маркированных списках и чек-листах; в H1 и H2 он запрещён. LSI-сущности не являются целевыми запросами, не заменяют и не расширяют утверждённое ядро. Telegram, обычные VK-посты, опубликованный архив и существующие черновики исключены.',
      data: { revision: 2, supersedes_revision: 1, applies_to: ['new_public_articles', 'new_longform'], platforms: ['article_platforms', 'tenchat'], excluded_platforms: ['telegram', 'vk'], semantic_core: { keyword_count: 302 }, automatic_zonal_distribution: { primary_hf_marker: { selection: 'shortest_base_query_in_selected_cluster', word_count: [2, 3], zones: ['h1', 'opening_paragraph'] }, commercial_modifiers: { terms: ['купить', 'заказать', 'цена'], zone: 'h2', count_control: 'platform_volume_ladder' }, lsi: { required: true, role: 'non_targeted_professional_lexicon', sources: ['task_context'], categories: ['technical_entities', 'metrics', 'infrastructure_terms'], allowed_zones: ['h3', 'unordered_lists', 'checklists'], prohibited_zones: ['h1', 'h2'], expands_target_query_core: false } }, evidence: { path: decisionPath } },
    },
    {
      key: 'content.geo_demand_gate_automation', revision: 1,
      title: 'Автоматический geo demand gate для редакционных материалов',
      content: 'Любой из 37 запросов группы geo_candidates_after_demand_validation разрешён в H2 новой статьи или лонгрида вне Telegram только при явном флаге geo_demand_owner_confirmed=true в текущей execution card. Без флага geo-запросы и geo-кластер отклоняются fail-closed и не передаются writer-ам или субагентам.',
      data: { revision: 1, applies_to: ['new_public_articles', 'new_longform'], platforms: ['article_platforms', 'tenchat'], excluded_platforms: ['telegram', 'vk'], cluster: 'geo_candidates_after_demand_validation', keyword_count: 37, required_execution_card_flag: 'geo_demand_owner_confirmed', required_value: true, allowed_zone: 'h2', without_flag: 'fail_closed_ignore_for_workers_and_subagents', evidence: { path: decisionPath } },
    },
  ];
  const database = new DatabaseSync(resolve(databasePath));
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-04', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-04', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-04', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    for (const rule of rules) {
      const candidateId = stableUuid(`candidate:${rule.key}:${rule.revision}`);
      const dataJson = JSON.stringify(rule.data);
      const competing = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND coalesce(json_extract(data_json, '$.revision'),0)>=? AND id<>?").get(rule.key, rule.revision, candidateId);
      if (competing) throw new Error(`Semantic duplicate or newer revision blocks ${rule.key}`);
      if (rule.revision > 1 && !database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status='approved' AND json_extract(data_json, '$.revision')=?").get(rule.key, rule.revision - 1)) throw new Error(`Approved prior revision is required for ${rule.key}`);
      created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-09-04', 'internal', 1)").run(candidateId, rule.key, rule.title, rule.content, dataJson, sourceId, owner).changes);
      if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым подтверждением владельца MetricHit от 04.09.2026.', reviewedAt, candidateId);
      assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { semantic_key: rule.key, content: rule.content, data_json: dataJson, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, rule.key);
    }
    database.exec('COMMIT');
    return { databasePath: resolve(databasePath), created, sourceId, documentId, versionId, candidateIds: rules.map((rule) => stableUuid(`candidate:${rule.key}:${rule.revision}`)) };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(JSON.stringify(applyPublicEditorialZonalSemanticsAndGeoGate(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath), null, 2));
