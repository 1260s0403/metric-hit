import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/backend-runtime-python-fastapi-2026-08-14.md';
const owner = 'owner';
const reviewedAt = '2026-08-14T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-python-fastapi:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyBackendRuntimePythonFastapi(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Architecture decision contains U+FFFD');

  const title = 'Целевой backend Python/FastAPI';
  const candidateContent = 'Целевой backend MetricHit OS — Python 3.13 и FastAPI. Новая функциональность Node.js заморожена, а существующее Node.js-ядро остаётся эталоном совместимости. SQLite сохраняется для MVP. Удаление Node.js-ядра возможно только после функционального паритета, прохождения полного набора тестов и отдельного решения владельца. Python-зависимости устанавливаются только в проектное окружение .venv, без глобальной установки.';
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-14',
  });
  const candidateData = JSON.stringify({
    target_runtime: 'python-3.13',
    target_framework: 'fastapi',
    node_new_features: 'frozen',
    node_role: 'compatibility_reference',
    mvp_database: 'sqlite',
    node_removal_requires: ['functional_parity', 'all_tests_pass', 'separate_owner_decision'],
    dependency_scope: '.venv',
    evidence: { path: decisionPath },
  });

  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const candidateId = stableUuid('candidate:architecture.backend_runtime_python_fastapi');
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-14', 'internal')
    `).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(documentId, title, content, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(versionId, documentId, title, content, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'decision', 'architecture.backend_runtime_python_fastapi', ?, ?, ?, 'pending', ?, ?, '2026-08-14', 'internal', 1)
    `).run(candidateId, title, candidateContent, candidateData, sourceId, owner).changes);

    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?, review_note = ?,
            updated_at = ?, version = version + 1
        WHERE id = ?
      `).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 14.08.2026.', reviewedAt, candidateId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), {
      type: 'decision', semantic_key: 'architecture.backend_runtime_python_fastapi', title,
      content: candidateContent, data_json: candidateData, source_id: sourceId,
      status: 'approved', author: owner, valid_at: '2026-08-14', access_level: 'internal',
      reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'backend runtime candidate');
    assertFields(database.prepare('SELECT * FROM sources WHERE id = ?').get(sourceId), {
      type: 'owner_decision', title, content: `Repository file: ${decisionPath}`,
      data_json: metadata, status: 'active', author: owner,
      valid_at: '2026-08-14', access_level: 'internal', version: 1,
    }, 'backend runtime source');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      type: 'owner_decision', title, content, data_json: metadata, status: 'active',
      source_id: sourceId, author: owner, valid_at: '2026-08-14',
      access_level: 'internal', version: 1,
    }, 'backend runtime document');
    assertFields(database.prepare('SELECT * FROM document_versions WHERE id = ?').get(versionId), {
      document_id: documentId, type: 'owner_decision', title, content,
      data_json: metadata, status: 'active', source_id: sourceId, author: owner,
      valid_at: '2026-08-14', access_level: 'internal', version: 1,
    }, 'backend runtime document version');
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
  const result = applyBackendRuntimePythonFastapi(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
  console.log(`Applied backend runtime decision to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
}
