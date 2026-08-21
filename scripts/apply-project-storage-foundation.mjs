import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/project-storage-foundation-2026-08-21.md';
const semanticKey = 'architecture.project_storage_foundation';
const owner = 'owner';
const reviewedAt = '2026-08-21T18:00:00.000Z';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-project-storage:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) {
    if (row[field] !== value) throw new Error(`${label}.${field} differs`);
  }
}

export function applyProjectStorageFoundation(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');

  const title = 'Фундамент физического хранилища проектов «Ядра»';
  const content = 'Первый этап независимых проектных контуров завершён: каждому каноническому UUID проекта детерминированно соответствует отдельный SQLite-файл data/projects/<project_id>/project.sqlite. Защита пути запрещает выход из корня, перенаправление и пересечение хранилищ; служебная идентичность файла позволяет безопасную идемпотентную повторную инициализацию и явно отклоняет чужой, повреждённый или несовместимый файл. Этап не переносит существующие данные, не меняет legacy-базу или её схему, не переключает рабочий runtime, не меняет операторскую панель и не реализует экспорт/импорт.';
  const data = JSON.stringify({
    revision: 1,
    root: 'data/projects',
    layout: '<project_id>/project.sqlite',
    project_id: 'canonical_lowercase_uuid_v4',
    storage_format: 1,
    path_traversal_allowed: false,
    redirected_or_shared_paths_allowed: false,
    reinitialization: 'validate_only_and_idempotent',
    legacy_database_changed: false,
    runtime_connected: false,
    migrated_existing_data: false,
    operator_panel_changed: false,
    export_import_implemented: false,
    evidence: {
      decision: decisionPath,
      contract: 'documents/project-storage.md',
      implementation: 'src/metrichit_os/project_storage.py',
    },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-21',
  });
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const candidateId = uuid(`candidate:${semanticKey}:1`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };

  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare(
      "SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?",
    ).get(semanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    const conflict = database.prepare(
      "SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))",
    ).get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(database.prepare(
      "INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-21', 'internal')",
    ).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(
      "INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-21', 'internal', 1)",
    ).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(
      "INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-21', 'internal', 1)",
    ).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-21', 'internal', 1)",
    ).run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?",
      ).run(owner, reviewedAt, 'Одобрено прямым решением владельца от 21.08.2026.', reviewedAt, candidateId);
    }

    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), {
      type: 'decision', semantic_key: semanticKey, title, content, data_json: data,
      status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'project storage decision');
    assertRow(database.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), {
      data_json: metadata, status: 'active',
    }, 'source');
    assertRow(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), {
      content: decision, data_json: metadata, source_id: sourceId, version: 1,
    }, 'document');
    assertRow(database.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), {
      document_id: documentId, content: decision, data_json: metadata, version: 1,
    }, 'document version');
    database.exec('COMMIT');
    return { databasePath, semanticKey, candidateId, created };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`Applied project storage foundation: ${JSON.stringify(applyProjectStorageFoundation(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
}
