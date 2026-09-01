import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-visual-standard-policy-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-01T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-editorial-visual-standard:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyEditorialVisualStandardPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Статьи MetricHit: обязательный визуальный пакет';
  const content = 'Каждый содержательный черновик статьи по умолчанию получает визуальный пакет: обложку для целевой площадки и две оригинальные поддерживающие иллюстрации для конкретных разделов, если владелец явно не отказался от него. Исполнитель визуально проверяет все изображения до поставки и регенерирует слабые. Запрещены выдуманные доказательства, данные, кейсы, скриншоты интерфейса, логотипы и клиентские идентификаторы. Отдельное согласование не требуется, кроме глобальной смены стиля, реальных фотографий или логотипов и внешней публикации.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-01' });
  const data = JSON.stringify({ applies_to: ['articles', 'article_drafts'], default_visual_package: { cover: 1, supporting_visuals: 2, total: 3, opt_out: 'explicit_owner_instruction' }, requirements: ['section_specific_purpose', 'original_asset', 'visual_inspection_before_delivery', 'regenerate_if_weak'], prohibited: ['fabricated_proof', 'fabricated_data', 'fabricated_case_studies', 'ui_screenshots', 'logos', 'client_identifiers'], owner_approval_required_for: ['global_style_change', 'real_photography', 'real_logos', 'external_publication'], evidence: { path: decisionPath } });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const policyId = stableUuid('candidate:content.editorial_visual_standard');
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get('content.editorial_visual_standard', policyId);
    if (duplicate) throw new Error('Semantic duplicate blocks editorial visual standard policy');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-01', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', 'content.editorial_visual_standard', ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(policyId, title, content, data, sourceId, owner).changes);
    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(policyId);
    if (candidate.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 01.09.2026.', reviewedAt, policyId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(policyId), { type: 'editorial_rule', semantic_key: 'content.editorial_visual_standard', title, content, data_json: data, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'editorial visual standard policy');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, policyId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied editorial visual standard policy: ${JSON.stringify(applyEditorialVisualStandardPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
