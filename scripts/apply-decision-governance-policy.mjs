import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/decision-governance-policy-2026-08-15.md';
const semanticKey = 'architecture.decision_governance_policy';
const reviewedAt = '2026-08-15T17:00:00.000Z';
const owner = 'owner';
const revision = 3;

function uuid(key) {
  const hex = createHash('sha256').update(`metrichit-decision-governance:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) {
    if (row[field] !== value) throw new Error(`${label}.${field} differs`);
  }
}

export function applyDecisionGovernancePolicy(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');

  const title = 'Политика контура решений MetricHit OS';
  const content = 'Контур решений относится к центральному ядру, а не к отделу или автономному агенту. Явно утверждённые владельцем решения могут сохраняться как approved; предложения, выводы и непринятые варианты остаются pending candidates, а потенциальные решения никогда не auto-approve. Перед сохранением проверяются semantic duplicate, evolution и conflicts. Решения могут связываться с проектом, задачей, источником и при необходимости Git-коммитом. В current context включаются только значимые approved-решения; технические мелкие правки решениями не считаются. Контур охватывает архитектуру, продукт, приоритеты, правила, бюджеты, сроки, права, ограничения и направления проектов. Реализован минимальный repo-side strategy → developer handoff: стратегический поток передаёт явно утверждённый короткий decision delta, обычный Python-код валидирует его и атомарно сохраняет approved candidate вместе со связанной standalone engineering task в существующем task-контуре; developer-поток получает следующую задачу read-only CLI-командой. Отдельный LLM-вызов, агент, UI, daemon и scheduler не используются. Будущий UI входит в управление кандидатами памяти и должен стать основой «Центра решений владельца».';
  const policyData = JSON.stringify({
    belongs_to: 'central_core',
    is_department: false,
    is_autonomous_agent: false,
    owner_explicit_decisions: 'approved_allowed',
    unaccepted_material: 'pending_candidate_only',
    potential_decisions_auto_approve: false,
    pre_save_checks: ['semantic_duplicate', 'evolution', 'conflicts'],
    links: ['project', 'task', 'source', 'git_commit_optional'],
    current_context: 'significant_approved_only',
    excludes: ['minor_technical_changes'],
    scopes: ['architecture', 'product', 'priorities', 'rules', 'budgets', 'deadlines', 'rights', 'constraints', 'project_directions'],
    execution: { separate_llm_call_required: false, separate_agent_required: false, output: 'short_decision_delta', persistence: 'validated_by_regular_code', target_overhead: 'few_percent_or_less', implementation: 'repo_side_cli' },
    handoff: { create_command: 'handoff-create', next_command: 'handoff-next', task_type: 'standalone_task', atomic_decision_task_link: true, read_only_next: true },
    future_ui: ['memory_candidate_management', 'owner_decision_center'],
    functionality_implemented: 'minimal_cli_handoff_only',
    revision,
    supersedes_semantic_revision: revision - 1,
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-15',
  });

  const sourceId = uuid(`source:${decisionPath}:${revision}`);
  const documentId = uuid(`document:${decisionPath}:${revision}`);
  const versionId = uuid(`version:${decisionPath}:${revision}`);
  const candidateId = uuid(`candidate:${semanticKey}:${revision}`);
  const approvedLineage = new Set([
    uuid(`candidate:${semanticKey}`),
    ...Array.from({ length: revision - 2 }, (_, index) => uuid(`candidate:${semanticKey}:${index + 2}`)),
  ]);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const activeSameKey = db.prepare(`SELECT id,status FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?`).all(semanticKey, candidateId);
    const competing = activeSameKey.filter((row) => !(approvedLineage.has(row.id) && row.status === 'approved'));
    if (competing.length) throw new Error(`Semantic duplicate or evolution requires an explicit superseding revision for ${semanticKey}`);
    const conflict = db.prepare(`SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))`).get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(db.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-15', 'internal')`).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-15', 'internal', 1)`).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-15', 'internal', 1)`).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-15', 'internal', 1)`).run(candidateId, semanticKey, title, content, policyData, sourceId, owner).changes);

    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 15.08.2026.', reviewedAt, candidateId);
    }
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: policyData, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'decision governance candidate');
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, semanticKey, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally {
    db.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const result = applyDecisionGovernancePolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase);
  console.log(`Applied decision governance policy: ${JSON.stringify(result)}`);
}
