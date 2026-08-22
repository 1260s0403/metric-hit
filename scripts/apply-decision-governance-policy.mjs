import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/decision-governance-policy-2026-08-15.md';
const semanticKey = 'architecture.decision_governance_policy';
const operationsSemanticKey = 'operations.server_strategy_workflow';
const reviewedAt = '2026-08-17T00:00:00.000Z';
const owner = 'owner';
const revision = 19;
const operationsRevision = 6;
const operationsSupersededCandidateIds = new Set([
  '93280439-9cda-48b9-a84f-90914eb4ab36',
  '39f80dbe-092b-4f63-a8a1-3e13aa09592b',
  ...Array.from({ length: operationsRevision - 2 }, (_, index) => uuid(`candidate:${operationsSemanticKey}:${index + 3}`)),
]);

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
  content += ' Для небольшой изолированной и явно утверждённой правки действует fast path: Strategy выполняет полный startup protocol один раз и передаёт одному executor-у owner approval, точный scope/acceptance, branch/HEAD/status и релевантные ссылки. Executor читает AGENTS, проверяет Git, читает только относящиеся файлы/контракты и извлекает только релевантную память read-only CLI; повторная загрузка всего current context, operating context и roadmap, repo-side handoff, дополнительная задача/agent и плановый артефакт не требуются. Один набор repository mutations выполняет один ответственный executor и завершает одним commit. Значимое правило тот же executor сохраняет штатным идемпотентным memory workflow; техническая мелкая правка в память не записывается. Fast path не применяется к архитектуре, SQLite-схеме/миграциям, бизнес-логике, авторизации, security, backup/restore, целостности данных, многомодульному или неясному scope, затрагивающему scope dirty worktree и расхождениям HEAD/контекста. Действующие owner-gates сохраняются.';
  content += ' Утверждённые изменения маршрутизируются по реальному риску: малое (локальные UI/CSS/текстовые правки, документация, узкие исправления и синхронизация правила памяти) исполняется одним executor-ом сразу на default Terra с целевыми тестами и git diff --check; стандартное — в ограниченном scope одного модуля с точным acceptance, без повторного полного context, с тестами затронутого модуля и E2E при изменении UI; крупное (архитектура, SQLite schema/migrations, security/auth, backup/restore, data integrity или сквозной многомодульный scope) требует полного startup/context, применимого подтверждения special model по действующей policy и полной регрессии/integrity-проверок. Strategy не относит UI-текст, CSS или узкое исправление к архитектуре без фактического основания. Полная регрессия нужна для крупного изменения и этапной поставки, но не автоматически после каждого малого изменения. Во всех режимах сохраняются single writer/executor, один commit, чистый Git и относящийся UI E2E.';
  content += ' Managed sandbox является внешней границей платформы: репозиторий не может предоставить Full access, отключить approval или обойти запрет на создание .git/index.lock. При таком отказе executor сразу сообщает точную заблокированную операцию и внешний blocker, использует штатный platform approval flow, если он доступен, и после разрешения продолжает в том же thread без нового executor-а, циклов повторных попыток или неподтверждённого вывода о неисправности Git, БД либо сервера.';
  content += ' Запрос владельца изменить или построить в названном scope является standing authorization на in-scope реализацию, тесты, обычный git staging и один commit; Strategy не запрашивает повторное промежуточное подтверждение. Отдельное явное решение требуется только для удаления, force-операций, внешней публикации, расходов, изменений доступов/прав, стратегии, политики памяти, настроек/глобальной системы или существенного расширения scope. Managed-sandbox prompts отменить нельзя и они сообщаются только при возникновении.';
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
    execution: {
      separate_llm_call_required: false,
      separate_agent_required: false,
      output: 'short_decision_delta',
      persistence: 'validated_by_regular_code',
      target_overhead: 'few_percent_or_less',
      implementation: 'native_codex_task_thread',
      canonical_path: ['strategy', 'native_codex_task_thread', 'commit_result'],
      small_change_fast_path: {
        eligible: ['isolated_ui_css_text', 'narrow_fix', 'documentation', 'approved_memory_rule_sync'],
        strategy_full_startup_completed_once: true,
        handoff_context: ['owner_approval', 'exact_scope_acceptance', 'branch_head_status', 'relevant_canonical_references'],
        executor_reads: ['agents_rules', 'branch_head_status', 'scope_files_and_contracts', 'targeted_read_only_memory'],
        repeat_full_context_required: false,
        repo_side_handoff_required: false,
        additional_task_or_agent_required: false,
        planning_artifact_required: false,
        significant_memory_uses_same_executor_and_idempotent_workflow: true,
        responsible_executors: 1,
        commits: 1,
        excluded: ['architecture', 'sqlite_schema_or_migrations', 'business_logic', 'authorization', 'security', 'backup_restore', 'data_integrity', 'multi_module_scope', 'unclear_scope_or_approval', 'overlapping_dirty_worktree', 'head_or_context_mismatch', 'material_contradiction'],
      },
      risk_routing: {
        classifier_must_use_actual_risk: true,
        ui_text_css_narrow_fix_are_not_architecture_by_default: true,
        ordinary_tasks_use_default_terra_without_separate_confirmation: true,
        special_model_policy_preserved: true,
        small: { scope: ['local_ui_css_text', 'documentation', 'narrow_fix', 'approved_memory_rule_sync'], executor: 1, checks: ['targeted_tests', 'git_diff_check'] },
        standard: { scope: ['bounded_one_module', 'exact_acceptance'], repeat_full_project_context_required: false, checks: ['affected_module_tests', 'ui_e2e_when_ui_changes'] },
        major: { scope: ['architecture', 'sqlite_schema_or_migrations', 'security_or_auth', 'backup_restore', 'data_integrity', 'cross_module'], checks: ['full_startup_context', 'applicable_special_model_approval', 'full_regression', 'integrity_checks'] },
        full_regression_required_for: ['major_change', 'stage_delivery'],
        full_regression_automatic_for_every_small_change: false,
        quality_invariants: ['single_writer_executor', 'one_commit', 'clean_git', 'relevant_ui_e2e', 'full_checks_for_sensitive_high_risk_changes'],
      },
    },
    platform_boundary: {
      managed_sandbox_is_external: true,
      repository_can_grant_full_access_or_disable_approval: false,
      repository_can_bypass_git_index_lock_denial: false,
      on_denial: ['report_exact_blocked_operation_immediately', 'identify_external_blocker', 'use_platform_approval_if_available', 'continue_same_executor_after_approval'],
      forbidden_reactions: ['spawn_replacement_executor', 'retry_loop', 'claim_git_database_or_server_failure_without_evidence'],
    },
    implementation_authorization: {
      owner_in_scope_request_is_standing_authorization: true,
      includes: ['implementation', 'tests', 'ordinary_git_staging', 'one_commit'],
      redundant_intermediate_confirmation_required: false,
      separate_owner_decision_required_for: ['deletion', 'force_operations', 'external_publication', 'spending', 'access_or_permission_changes', 'strategy_changes', 'memory_policy_changes', 'settings_or_global_system_changes', 'material_scope_expansion'],
      managed_sandbox_prompts_removable: false,
      managed_sandbox_prompts_reported: 'only_when_they_occur',
    },
    owner_gates_preserved: ['deletion', 'force_operations', 'access_changes', 'publication', 'spending', 'strategy_changes', 'memory_changes', 'settings_changes', 'other_dangerous_actions'],
    strategy: { mode: 'read_only', primary_role: ['product', 'architecture', 'priorities', 'development'], pre_decision_context: ['approved_memory', 'current_context', 'operating_context', 'roadmap', 'git_state'], proactively_flags: ['material_gaps', 'contradictions', 'mvp_next_steps'], owner_repeats_known_context: false, chat_history_is_canonical_truth: false, visible_project_chat: 'strategy_only', permitted_actions: ['discuss', 'analyze', 'read_approved_memory', 'read_git', 'read_documents', 'create_internal_native_task_thread'], repository_file_modifications_allowed: false, repository_file_modification_scope: ['memory', 'docs', 'config', 'code', 'tests'], repository_file_modification_size_exception: false, repository_file_modifications_require: 'separate_native_task_thread', engineering_task_creation_requires: 'explicit_owner_approved_repository_change', user_owned_sidebar_chat_creation_allowed: false, create_thread_allowed: false, no_engineering_task_for: ['planning', 'analysis', 'context_reads', 'unapproved_proposals', 'pending_candidates'], executor_lifecycle_reporting: { announce_after_launch: ['executor_name', 'exact_scope'], active_executor: { keep_user_work_turn_open: true, final_completion_answer_allowed: false, interim_communication: 'clearly_marked_in_progress_comment_only' }, publish_final_outcome_only_after: ['commit_or_result', 'verified_clean_git_status'], final_outcome_on_real_blocker: true, publish_after_completion: ['completed_or_blocked', 'commit_if_any', 'checks', 'git_status', 'blocker_if_any'], periodic_statuses: false, scheduler: false, ui: false, new_functionality: false }, continuity: { transition_triggers: ['chat_too_long', 'repeated_compaction', 'important_detail_loss', 'decision_confusion', 'material_context_waste'], pre_transition_review: ['approved_memory', 'current_context', 'roadmap', 'significant_approved_decisions', 'plans', 'constraints', 'unfinished_tasks', 'immediate_next_steps'], synchronization_when_gap_found: 'separate_native_codex_task_thread', new_chat_confirmation: 'startup_protocol_recovers_context_without_old_transcript', new_chat_inherits_role_via: 'startup_protocol' } },
    handoff: { create_command: 'handoff-create', next_command: 'handoff-next', claim_command: 'handoff-claim', complete_command: 'handoff-complete', task_type: 'standalone_task', atomic_decision_task_link: true, native_task_thread: 'internal_execution_mechanism', repo_side_role: 'decision_task_context_and_result_audit', repo_side_is_execution_queue: false, permanent_developer_chat_required: false, user_workflow_requires_lifecycle_commands: false, lifecycle: ['ready', 'in_progress', 'completed'], claim_complete_idempotent: true, completion_links_commit_hash: true, one_native_thread_per_user_engineering_decision: true, strategy_checks_existing_thread_by_user_turn_or_decision_before_create: true, repeated_user_turn_routing_is_idempotent: true, existing_thread_response_includes_id_and_status: true, existing_thread_prevents_second_creation: true, new_engineering_task_requires_new_native_thread: true, strategy_may_replace_existing_or_completed_thread_scope: false, active_engineering_thread_blocks_second_thread: true, maximum_active_executors: 1, active_thread_requires_wait_or_owner_explicit_cancellation: true, thread_closed_after_commit_result_and_clean_git_status: true, completed_thread_reuse_allowed: false },
    future_ui: ['memory_candidate_management', 'owner_decision_center'],
    functionality_implemented: 'repo_side_record_audit_with_native_task_thread_execution',
    revision,
    supersedes_semantic_revision: revision - 1,
    evidence: { path: decisionPath },
  });
  const policy = JSON.parse(policyData);
  const operationsContent = 'SERVER и C:\\MetricHit\\workspace остаются primary workspace MetricHit, а серверный Strategy — единственным постоянным owner-visible координационным чатом и read-only потоком. После явного owner approval каждый набор изменений репозитория выполняет один ответственный native executor и завершается одним commit. Изменения маршрутизируются по риску: малое — fast path на default Terra с целевыми тестами и git diff --check; стандартное — один ограниченный модуль с тестами модуля и UI E2E при необходимости без повторной полной загрузки контекста; крупное — architecture, schema/migrations, security/auth, backup/restore, data integrity либо cross-module scope с полным startup/context, применимым special-model approval и полной регрессией/integrity. Перед работой обязателен delivery envelope: один результат, запрещённые расширения, первая проверка, статус через 2 минуты и deadline — 5 минут для малого изменения, 10 минут для стандартного этапа. Read-only preflight явно показывает необходимость внешнего approval, но не ждёт его. Малый этап к 5-й минуте завершается проверенным результатом или точным blocker; дефект вне acceptance останавливает этап и становится отдельным следующим этапом. Допустима одна in-scope попытка исправления; второй failure — blocker без replacement executor-а. Полная регрессия обязательна для крупного изменения и этапной поставки, но не автоматически для малого. UI-текст, CSS и узкое исправление не являются архитектурой без фактического основания. Single writer, чистый Git, UI E2E и опасные owner-gates сохраняются. Managed sandbox является внешней границей: репозиторий не может гарантировать Full access, отключить approval или разрешить .git/index.lock; platform blocker сообщается немедленно и после штатного approval работа продолжается в том же executor-е.';
  const operationsData = JSON.stringify({
    revision: operationsRevision,
    supersedes_candidate_id: uuid(`candidate:${operationsSemanticKey}:${operationsRevision - 1}`),
    delivery_envelope: { required: true, fields: ['one_complete_result', 'forbidden_expansions', 'first_check', 'status_within_minutes', 'deadline_minutes'] },
    delivery_limits: { status_within_minutes: 2, small_deadline_minutes: 5, standard_deadline_minutes: 10 },
    external_approval: { preflight_visibility_required: true, preflight_waits_for_approval: false },
    scope_control: { defect_outside_acceptance: 'stop_stage_and_create_next_stage', in_scope_fix_attempts: 1, second_failure: 'exact_blocker', replacement_executor_chain_allowed: false },
    primary_workspace: 'C:\\MetricHit\\workspace',
    strategy: { owner_visible: true, read_only: true, permanent_project_chat: true },
    repository_mutation: { responsible_executors: 1, commits: 1, in_scope_owner_request_is_authorization: true, redundant_intermediate_confirmation_required: false },
    small_change_fast_path: policy.execution.small_change_fast_path,
    risk_routing: policy.execution.risk_routing,
    platform_boundary: policy.platform_boundary,
    owner_gates_preserved: policy.owner_gates_preserved,
    implementation_authorization: policy.implementation_authorization,
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
  const operationsCandidateId = uuid(`candidate:${operationsSemanticKey}:${operationsRevision}`);
  const approvedLineage = new Set([
    uuid(`candidate:${semanticKey}`),
    'cdf62d9d-76e3-4280-a2c0-a319c2e1809e',
  'e7629ceb-86fe-41d0-a21d-101a0c33f552',
  'b99868df-1b4d-4598-ab48-fecb476022ac',
  // Approved terminology evolution from the independent-project-contours decision.
  // It explicitly supersedes semantic revision 19 and must remain in the lineage.
  '1c200058-5e54-4d62-a901-bf5113b82b3e',
    ...Array.from({ length: revision - 1 }, (_, index) => uuid(`candidate:${semanticKey}:${index + 2}`)),
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
    const operationsActive = db.prepare(`SELECT id,status FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?`).all(operationsSemanticKey, operationsCandidateId);
    const operationsCompeting = operationsActive.filter((row) => row.status !== 'approved' || !(operationsSupersededCandidateIds.has(row.id) || row.id === uuid(`candidate:${operationsSemanticKey}:${operationsRevision - 1}`)));
    if (operationsCompeting.length) throw new Error(`Semantic duplicate or evolution requires an explicit superseding revision for ${operationsSemanticKey}`);
    const operationsConflict = db.prepare(`SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))`).get(operationsCandidateId, operationsSemanticKey);
    if (operationsConflict) throw new Error(`Open memory conflict blocks ${operationsSemanticKey}`);

    created.sources += Number(db.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-17', 'internal')`).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)`).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)`).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-17', 'internal', 1)`).run(candidateId, semanticKey, title, content, policyData, sourceId, owner).changes);

    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 17.08.2026.', reviewedAt, candidateId);
    }
    created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-17', 'internal', 1)`).run(operationsCandidateId, operationsSemanticKey, 'Рабочий процесс SERVER, Strategy и executor', operationsContent, operationsData, sourceId, owner).changes);
    const operationsCandidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(operationsCandidateId);
    if (operationsCandidate.status === 'pending') {
      db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 17.08.2026.', reviewedAt, operationsCandidateId);
    }
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: policyData, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'decision governance candidate');
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(operationsCandidateId), { type: 'decision', semantic_key: operationsSemanticKey, title: 'Рабочий процесс SERVER, Strategy и executor', content: operationsContent, data_json: operationsData, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'server strategy workflow candidate');
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, semanticKey, operationsSemanticKey, created, sourceId, documentId, versionId, candidateId, operationsCandidateId };
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
