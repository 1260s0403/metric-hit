import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/model-routing-policy-2026-08-13.md';
const owner = 'owner';
const reviewedAt = '2026-08-13T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-model-routing:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyModelRoutingPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Model routing decision contains U+FFFD');
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-13',
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const candidateId = stableUuid('candidate:ai.model_routing_policy');
  const title = 'Политика выбора модели Codex';
  const candidateContent = 'По умолчанию: GPT-5.6 Terra, reasoning Medium. Перед сложными архитектурными, security-критичными и особо ответственными задачами предлагать GPT-5.6 Sol; перед массовой однотипной обработкой и фоновыми операциями — GPT-5.6 Luna. Переключение возможно только после уведомления и явного подтверждения владельца; после специальной задачи предлагать вернуться на Terra Medium.';
  const candidateData = JSON.stringify({
    default_model: 'GPT-5.6 Terra',
    default_reasoning: 'Medium',
    sol_for: ['complex_architecture', 'security_critical', 'high_responsibility'],
    luna_for: ['bulk_classification', 'bulk_extraction', 'large_homogeneous_processing', 'background_operations'],
    owner_confirmation_required: true,
    return_recommendation: 'GPT-5.6 Terra / Medium',
    evidence: { path: decisionPath },
  });

  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  try {
    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-13', 'internal')
    `).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-13', 'internal', 1)
    `).run(documentId, title, content, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-13', 'internal', 1)
    `).run(versionId, documentId, title, content, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'ai_policy', 'ai.model_routing_policy', ?, ?, ?, 'pending', ?, ?, '2026-08-13', 'internal', 1)
    `).run(candidateId, title, candidateContent, candidateData, sourceId, owner).changes);

    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
            review_note = ?, updated_at = ?, version = version + 1
        WHERE id = ?
      `).run(owner, reviewedAt, 'Одобрено на основании прямого решения владельца MetricHit от 13.08.2026.', reviewedAt, candidateId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), {
      type: 'ai_policy', semantic_key: 'ai.model_routing_policy', title,
      content: candidateContent, data_json: candidateData, source_id: sourceId,
      status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'model routing candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      content, data_json: metadata, source_id: sourceId, version: 1,
    }, 'model routing document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const result = applyModelRoutingPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
  console.log(`Applied model routing policy to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
}

