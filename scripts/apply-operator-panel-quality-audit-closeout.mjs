import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/operator-panel-quality-audit-closeout-2026-08-19.md';
const completionSemanticKey = 'operations.operator_panel_quality_audit_followups_completion';
const originalSemanticKey = 'operations.operator_panel_quality_audit_followups';
const owner = 'owner';
const reviewedAt = '2026-08-19T00:00:00.000Z';
const projectId = '00000000-0000-4000-a000-000000000102';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-operator-panel-quality-audit-closeout:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function originalUuid(key) {
  const hash = createHash('sha256').update(`metrichit-operator-panel-quality-audit:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyOperatorPanelQualityAuditCloseout(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');

  const title = 'Завершён этап устранения регрессий operator panel';
  const content = 'На поставке 9f0ac1e оставлена единая актуальная реализация экранов, устранены дублирующиеся и устаревшие скрытые элементы управления, E2E-контракты приведены к итоговому интерфейсу, а проверка состояния рабочей области больше не зависит от фиксированного количества открытых задач. Подтверждено: Python — 167 passed, 1 skipped; Node — 51 passed; проверки синтаксиса, зависимостей и изменений прошли. Исходная быстрая проверка качества остаётся историческим основанием этапа; результат не утверждает более широкую проверку или переработку проекта.';
  const data = JSON.stringify({
    completed_commit: '9f0ac1e',
    completed_scope: ['one_current_renderer_per_screen', 'remove_duplicate_and_obsolete_hidden_controls', 'align_e2e_with_final_ui', 'non_brittle_workspace_status_assertion'],
    verification: { python: { passed: 167, skipped: 1 }, node: { passed: 51 }, checks: ['syntax', 'dependencies', 'git_diff_check'] },
    screenshots: { stored_locally: true, ignored_working_artifacts: true },
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-19' });
  const originalTaskId = originalUuid(`task:${originalSemanticKey}`);
  const taskData = JSON.stringify({
    priority: 'high', due_date: null, standalone: true, project_id: projectId, decision_semantic_key: originalSemanticKey,
    completion: { commit: '9f0ac1e', completed_at: reviewedAt, verification: { python: '167 passed, 1 skipped', node: '51 passed', checks: ['syntax', 'dependencies', 'git_diff_check'] } },
  });
  const sourceId = uuid(`source:${decisionPath}`), documentId = uuid(`document:${decisionPath}`), versionId = uuid(`version:${decisionPath}`), candidateId = uuid(`candidate:${completionSemanticKey}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, completedTasks: 0 };

  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(completionSemanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${completionSemanticKey}`);
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, completionSemanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${completionSemanticKey}`);

    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-19', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-19', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-19', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-19', 'internal', 1)").run(candidateId, completionSemanticKey, title, content, data, sourceId, owner).changes);
    const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 19.08.2026.', reviewedAt, candidateId);

    const task = database.prepare('SELECT status, data_json FROM tasks WHERE id=?').get(originalTaskId);
    if (!task) throw new Error('Missing original quality-audit follow-up task');
    if (task.status === 'pending') {
      database.prepare("UPDATE tasks SET status='completed', data_json=?, updated_at=?, version=version+1 WHERE id=?").run(taskData, reviewedAt, originalTaskId);
      created.completedTasks += 1;
    } else if (task.status !== 'completed' || task.data_json !== taskData) {
      throw new Error('Original quality-audit follow-up task differs from expected completed result');
    }

    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: completionSemanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'quality-audit closeout decision');
    assertRow(database.prepare('SELECT * FROM tasks WHERE id=?').get(originalTaskId), { status: 'completed', data_json: taskData }, 'completed quality-audit task');
    assertRow(database.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(database.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    database.exec('COMMIT');
    return { databasePath, completionSemanticKey, candidateId, originalTaskId, created };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied operator panel quality-audit closeout: ${JSON.stringify(applyOperatorPanelQualityAuditCloseout(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
