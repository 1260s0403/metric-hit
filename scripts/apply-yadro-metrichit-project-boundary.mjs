import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/yadro-metrichit-project-boundary-2026-08-17.md';
const semanticKey = 'architecture.operating_core_and_departments';
const owner = 'owner';
const reviewedAt = '2026-08-17T18:30:00.000Z';
const revision = 6;

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-operating-context:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyYadroMetricHitProjectBoundary(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const title = 'Граница «Ядра» и проекта MetricHit';
  const content = '«Ядро» — основной проект и control plane системы. MetricHit — первый проект внутри системы, которым «Ядро» помогает управлять. MetricHit не является подпроектом «Ядра», отделом или равноправным «Ядру» control plane. В данных роль «Ядра» — control_plane, а роль MetricHit — managed_project; их стабильные ID и scope существующих объектов сохраняются без массового переназначения. Новые задачи, рекомендации и идеи по умолчанию относятся к MetricHit; допустим один уровень подпроектов. Разработка автономных отделов, включая редакцию, отложена до отдельной команды владельца; сейчас отделы не строятся, а отсутствующая editorial DB обозначает состояние paused.';
  const data = JSON.stringify({
    core_product: 'yadro',
    core_role: 'primary_project_and_control_plane',
    shared_capabilities: ['memory', 'decisions', 'projects', 'tasks', 'audit', 'strategy_governance'],
    core_project: 'Ядро',
    first_managed_project: 'MetricHit',
    metrichit_role: 'managed_project_inside_yadro_system',
    project_roles: { yadro: 'control_plane', metrichit: 'managed_project' },
    metrichit_is_department: false,
    metrichit_is_internal_technical_module: false,
    hierarchy: { max_subproject_depth: 1, cross_project_children_allowed: false },
    required_scope_for_new: ['task', 'artem_recommendation', 'owner_idea'],
    default_project: 'MetricHit',
    legacy_records_mass_reassigned: false,
    global_scope_excluded: ['approved_memory', 'decisions', 'strategy', 'audit'],
    autonomous_departments: { status: 'deferred', activation_requires: 'separate_owner_command' },
    editorial_database_when_paused: 'not_initialized',
    revision,
    supersedes_semantic_revision: revision - 1,
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-17' });
  const sourceId = uuid(`source:${decisionPath}:${revision}`);
  const documentId = uuid(`document:${decisionPath}:${revision}`);
  const versionId = uuid(`version:${decisionPath}:${revision}`);
  const candidateId = uuid(`candidate:${semanticKey}:${revision}`);
  // Revision 1 was created by the original import workflow before its UUID seed
  // was standardized; revision 2 uses the current deterministic seed.
  const supersededCandidateIds = new Set(['5d253851-f261-4c61-aae5-a59a3ca47597', uuid(`candidate:${semanticKey}:2`), uuid(`candidate:${semanticKey}:3`), uuid(`candidate:${semanticKey}:4`), uuid(`candidate:${semanticKey}:5`)]);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const sameKey = db.prepare("SELECT id,status FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").all(semanticKey, candidateId);
    const competing = sameKey.filter((row) => row.status !== 'approved' || !supersededCandidateIds.has(row.id));
    if (competing.length) throw new Error(`Semantic duplicate or evolution requires an explicit superseding revision for ${semanticKey}`);
    const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-17', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-17', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 17.08.2026.', reviewedAt, candidateId);
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'project boundary candidate');
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, semanticKey, candidateId, created };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`Applied Yadro–MetricHit project boundary: ${JSON.stringify(applyYadroMetricHitProjectBoundary(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
}
