import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/decision-governance-policy-2026-08-15.md';
const semanticKey = 'architecture.decision_governance_policy';
const reviewedAt = '2026-08-17T00:00:00.000Z';
const owner = 'owner';
const revision = 16;

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
  let content = 'Контур решений относится к центральному ядру, а не к отделу или автономному агенту. Явно утверждённые владельцем решения могут сохраняться как approved; предложения, выводы и непринятые варианты остаются pending candidates, а потенциальные решения никогда не auto-approve. Перед сохранением проверяются semantic duplicate, evolution и conflicts. Решения могут связываться с проектом, задачей, источником и при необходимости Git-коммитом. В current context включаются только значимые approved-решения; технические мелкие правки решениями не считаются. Контур охватывает архитектуру, продукт, приоритеты, правила, бюджеты, сроки, права, ограничения и направления проектов. Канонический workflow engineering: Strategy → internal native Codex task-thread/subagent → commit/result. Strategy — единственный постоянный видимый проектный чат и read-only поток: он обсуждает и анализирует, читает approved memory, Git и документы. Только после явного утверждения владельцем конкретного изменения репозитория Strategy создаёт ровно одну внутреннюю native engineering-задачу/subagent; он никогда не создаёт user-owned/sidebar-чат и не использует create_thread. Planning, analysis, context reads, неутверждённые предложения и pending candidates не создают engineering-задачу. Strategy не изменяет файлы репозитория — включая memory, docs, config, code и tests — независимо от размера изменения; их изменяет только отдельный native task-thread. Постоянный developer-чат не требуется. Repo-side handoff хранит решение, контекст задачи и известный итог/commit hash для audit; он не конкурирует с native task-thread как очередь исполнения. Существующие handoff-next, handoff-claim и handoff-complete и lifecycle ready → in_progress → completed остаются совместимым внутренним механизмом, но не обязательны для startup или пользовательского процесса. UI, daemon, scheduler, OpenAI API и интеграция внутреннего API Codex не реализуются. Будущий UI входит в управление кандидатами памяти и должен стать основой «Центра решений владельца».';
  content += ' Управление native Codex task-thread строго изолирует задачи: одно пользовательское engineering-решение создаёт ровно один native task-thread. До создания Strategy проверяет, нет ли уже thread для текущего пользовательского turn/решения. Повторная обработка того же turn маршрутизируется идемпотентно: если thread уже есть, Strategy сообщает его ID и status и ничего не создаёт. Каждая новая engineering-задача создаёт новый native task-thread; Strategy никогда не заменяет scope существующего или завершённого task-thread. Пока другой engineering thread действительно выполняется, Strategy не запускает второй thread и не переназначает первый: он ждёт завершения либо запрашивает у владельца явную отмену. После commit/result и чистого git status предыдущий thread закрыт для новых задач.';
  content += ' Сразу после запуска native executor-а Strategy сообщает владельцу имя executor-а и точный scope. Пока executor активен, Strategy удерживает пользовательский work turn открытым и не отправляет финальный ответ о завершении; при необходимости допустим только явно помеченный in-progress комментарий. Финальный итог Strategy публикует только после commit/result и проверенного чистого git status, либо при реальном blocker: готово/blocked, commit (если есть), проверки, git status и blocker (если есть). Для этого не вводятся периодические статусы, scheduler, UI или новая функциональность; остальной workflow не меняется.';
  content += ' Strategy — основной human-language координатор продукта, архитектуры, приоритетов и разработки: до решений он читает approved memory, current context, operating context, roadmap и фактический Git, отмечает существенные пробелы и противоречия и предлагает ближайшие MVP-шаги. Он не требует повторять известный контекст и не считает историю чата канонической истиной. Если чат стал слишком длинным, регулярно требует сжатия, теряет важные детали, путает решения или заметно расходует контекст, Strategy сам предлагает новый чат. Перед переходом он read-only сверяет approved memory, current context и roadmap на полноту значимых утверждённых решений, планов, ограничений, незавершённых задач и ближайших следующих шагов. При пробеле отдельный native task-thread синхронизирует канонический контекст; после сверки Strategy подтверждает, что новый чат продолжит работу по startup protocol без старой истории.';
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
    execution: { separate_llm_call_required: false, separate_agent_required: false, output: 'short_decision_delta', persistence: 'validated_by_regular_code', target_overhead: 'few_percent_or_less', implementation: 'native_codex_task_thread', canonical_path: ['strategy', 'native_codex_task_thread', 'commit_result'] },
    strategy: { mode: 'read_only', primary_role: ['product', 'architecture', 'priorities', 'development'], pre_decision_context: ['approved_memory', 'current_context', 'operating_context', 'roadmap', 'git_state'], proactively_flags: ['material_gaps', 'contradictions', 'mvp_next_steps'], owner_repeats_known_context: false, chat_history_is_canonical_truth: false, visible_project_chat: 'strategy_only', permitted_actions: ['discuss', 'analyze', 'read_approved_memory', 'read_git', 'read_documents', 'create_internal_native_task_thread'], repository_file_modifications_allowed: false, repository_file_modification_scope: ['memory', 'docs', 'config', 'code', 'tests'], repository_file_modification_size_exception: false, repository_file_modifications_require: 'separate_native_task_thread', engineering_task_creation_requires: 'explicit_owner_approved_repository_change', user_owned_sidebar_chat_creation_allowed: false, create_thread_allowed: false, no_engineering_task_for: ['planning', 'analysis', 'context_reads', 'unapproved_proposals', 'pending_candidates'], executor_lifecycle_reporting: { announce_after_launch: ['executor_name', 'exact_scope'], active_executor: { keep_user_work_turn_open: true, final_completion_answer_allowed: false, interim_communication: 'clearly_marked_in_progress_comment_only' }, publish_final_outcome_only_after: ['commit_or_result', 'verified_clean_git_status'], final_outcome_on_real_blocker: true, publish_after_completion: ['completed_or_blocked', 'commit_if_any', 'checks', 'git_status', 'blocker_if_any'], periodic_statuses: false, scheduler: false, ui: false, new_functionality: false }, continuity: { transition_triggers: ['chat_too_long', 'repeated_compaction', 'important_detail_loss', 'decision_confusion', 'material_context_waste'], pre_transition_review: ['approved_memory', 'current_context', 'roadmap', 'significant_approved_decisions', 'plans', 'constraints', 'unfinished_tasks', 'immediate_next_steps'], synchronization_when_gap_found: 'separate_native_codex_task_thread', new_chat_confirmation: 'startup_protocol_recovers_context_without_old_transcript', new_chat_inherits_role_via: 'startup_protocol' } },
    handoff: { create_command: 'handoff-create', next_command: 'handoff-next', claim_command: 'handoff-claim', complete_command: 'handoff-complete', task_type: 'standalone_task', atomic_decision_task_link: true, native_task_thread: 'internal_execution_mechanism', repo_side_role: 'decision_task_context_and_result_audit', repo_side_is_execution_queue: false, permanent_developer_chat_required: false, user_workflow_requires_lifecycle_commands: false, lifecycle: ['ready', 'in_progress', 'completed'], claim_complete_idempotent: true, completion_links_commit_hash: true, one_native_thread_per_user_engineering_decision: true, strategy_checks_existing_thread_by_user_turn_or_decision_before_create: true, repeated_user_turn_routing_is_idempotent: true, existing_thread_response_includes_id_and_status: true, existing_thread_prevents_second_creation: true, new_engineering_task_requires_new_native_thread: true, strategy_may_replace_existing_or_completed_thread_scope: false, active_engineering_thread_blocks_second_thread: true, maximum_active_executors: 1, active_thread_requires_wait_or_owner_explicit_cancellation: true, thread_closed_after_commit_result_and_clean_git_status: true, completed_thread_reuse_allowed: false },
    future_ui: ['memory_candidate_management', 'owner_decision_center'],
    functionality_implemented: 'repo_side_record_audit_with_native_task_thread_execution',
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
    decision_date: '2026-08-17',
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
    const activeSameKey = db.prepare(`SELECT id,status,data_json FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?`).all(semanticKey, candidateId);
    const isApprovedTaskContextEvolution = (row) => {
      if (row.status !== 'approved') return false;
      try {
        const data = JSON.parse(row.data_json);
        return typeof data.handoff_task_id === 'string' && (approvedLineage.has(data.supersedes_candidate_id) || data.supersedes_candidate_id === candidateId);
      } catch {
        return false;
      }
    };
    const competing = activeSameKey.filter((row) => !(approvedLineage.has(row.id) && row.status === 'approved') && !isApprovedTaskContextEvolution(row));
    if (competing.length) throw new Error(`Semantic duplicate or evolution requires an explicit superseding revision for ${semanticKey}`);
    const conflict = db.prepare(`SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))`).get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(db.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-17', 'internal')`).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)`).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)`).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-17', 'internal', 1)`).run(candidateId, semanticKey, title, content, policyData, sourceId, owner).changes);

    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 17.08.2026.', reviewedAt, candidateId);
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
