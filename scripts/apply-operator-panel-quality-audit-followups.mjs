import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/operator-panel-quality-audit-followups-2026-08-19.md';
const semanticKey = 'operations.operator_panel_quality_audit_followups';
const owner = 'owner';
const reviewedAt = '2026-08-19T00:00:00.000Z';
const projectId = '00000000-0000-4000-a000-000000000102';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-operator-panel-quality-audit:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyOperatorPanelQualityAuditFollowups(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const title = 'Ближайший этап: устранение регрессий operator panel';
  const content = 'Владелец утвердил ближайшим этапом устранение регрессий, выявленных быстрой проверкой качества: оставить по одной реализации рендера для каждого экрана operator panel, убрать дублирующиеся и устаревшие скрытые элементы управления, привести E2E-проверки к текущему интерфейсу, заменить фиксированное ожидание количества открытых задач в проверке состояния рабочей области и затем повторить полный относящийся набор проверок до чистого результата. Это техническая доработка качества существующего MVP без расширения функциональности или изменения архитектуры.';
  const taskContent = '1. Оставить по одной реализации рендера для каждого экрана operator panel.\n2. Убрать дублирующиеся и устаревшие скрытые элементы управления.\n3. Привести E2E-проверки к текущему интерфейсу.\n4. Убрать фиксированное число открытых задач из проверки состояния рабочей области.\n5. Повторить полный относящийся набор проверок до чистого результата.';
  const data = JSON.stringify({ priority: 'high', scope: 'operator_panel_quality', followups: ['one_renderer_per_screen', 'remove_duplicate_and_obsolete_hidden_controls', 'align_e2e_with_current_ui', 'remove_fixed_open_task_count_from_workspace_status_test', 'rerun_relevant_checks_to_clean_pass'], evidence: { path: decisionPath } });
  const taskData = JSON.stringify({ priority: 'high', due_date: null, standalone: true, project_id: projectId, decision_semantic_key: semanticKey });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-19' });
  const sourceId = uuid(`source:${decisionPath}`), documentId = uuid(`document:${decisionPath}`), versionId = uuid(`version:${decisionPath}`), candidateId = uuid(`candidate:${semanticKey}`), taskId = uuid(`task:${semanticKey}`);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, tasks: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = db.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-19', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-19', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-19', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-19', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    created.tasks += Number(db.prepare("INSERT OR IGNORE INTO tasks (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'standalone_task', ?, ?, ?, 'pending', ?, ?, '2026-08-19', 'internal', 1)").run(taskId, title, taskContent, taskData, sourceId, owner).changes);
    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 19.08.2026.', reviewedAt, candidateId);
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'quality audit decision');
    assertRow(db.prepare('SELECT * FROM tasks WHERE id=?').get(taskId), { type: 'standalone_task', title, content: taskContent, data_json: taskData, status: 'pending', source_id: sourceId, author: owner }, 'quality audit task');
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, semanticKey, candidateId, taskId, created };
  } catch (error) { db.exec('ROLLBACK'); throw error; } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied operator panel quality-audit follow-ups: ${JSON.stringify(applyOperatorPanelQualityAuditFollowups(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
