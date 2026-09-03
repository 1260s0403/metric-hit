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
const reviewedAt = '2026-09-03T06:55:00.000Z';
const owner = 'owner';
const revision = 32;
const operationsRevision = 19;
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
  content += ' Управление native Codex task-thread строго изолирует задачи: одно пользовательское engineering-решение создаёт ровно один native task-thread. До создания Strategy проверяет, нет ли уже thread для текущего пользовательского turn/решения. Повторная обработка того же turn маршрутизируется идемпотентно: если thread уже есть, Strategy сообщает его ID и status и ничего не создаёт. Каждая новая engineering-задача создаёт новый native task-thread; Strategy никогда не заменяет scope существующего или завершённого task-thread. Controlled parallel execution v1 допускает максимум четыре активных writer thread только через resource-aware handoff: разные неканонические Git worktree и ветки, точные path/SQLite/shared declarations и отсутствие пересечений. Пятый writer, ancestor/descendant path overlap, одна SQLite, core/policy/config/migration/dependency/shared-runtime, central control-plane, memory/context-pack или integration resource блокируются fail-closed. Разные project SQLite совместимы. Интеграция получает отдельный последовательный lease и блокируется при stale base. После commit/result и чистого git status thread закрыт для новых задач.';
  content += ' Strategy — read-only human-facing router: он назначает одного named executor-а с точным scope и сообщает только проверенный результат с чистым Git либо точный технический blocker. Он не опирается на ненаблюдаемые промежуточные контроли платформы. Частичный результат не является поставкой; заблокированная задача не передаётся и не переназначается без нового прямого указания владельца.';
  content += ' Контролируемый multi-agent research pilot сохраняет 2–3 независимые параллельные read-only research/audit-ветки одной задачи с обязательным synthesis Strategy. Отдельно controlled parallel execution v1 разрешает до четырёх независимых mutation/code/data/config-задач; внутри каждого набора изменений по-прежнему один named writer/executor, одна ветка, один commit и чистый Git.';
  content += ' Для небольшой изолированной и явно утверждённой правки действует fast path: он ограничен максимум тремя изменёнными отслеживаемыми файлами и исключает новые файлы, зависимости, runtime/configuration/system-изменения, схему данных и миграции; превышение любого предела до реализации переводит задачу в стандартный этап. Strategy передаёт одному executor-у owner approval, точный scope/acceptance, branch/HEAD/status и релевантные ссылки. До мутаций executor проверяет git status --short: при любом выводе сообщает точные грязные файлы и ждёт нового прямого решения владельца, не поглощая, восстанавливая, удаляя, коммитя или обходя их. Executor использует только существующие workflow, файлы и проверки; новые скрипты, файлы, задачи, абстракции и вспомогательные контуры запрещены, пока прямо не названы в acceptance. Он не расширяет и не переосмысливает scope: новая проблема становится отдельной задачей после прямого решения владельца. Поставка — только проверенный результат с чистым Git либо точный технический blocker. Fast path не применяется к архитектуре, SQLite-схеме/миграциям, бизнес-логике, авторизации, security, backup/restore, целостности данных, многомодульному или неясному scope, затрагивающему scope dirty worktree и расхождениям HEAD/контекста. Действующие owner-gates сохраняются.';
  content += ' Краткая постановка задачи состоит из четырёх пунктов: Result — один проверяемый итог; Scope — точные затрагиваемые области; First check — одна существующая быстрая целевая проверка затронутого модуля; Forbidden changes — что не менять. Если такая проверка неизвестна, задача стандартная и сначала в своём scope определяет нужную существующую проверку без широкой регрессии ради поиска. Формулировки «заодно» не расширяют scope. План, отчёт, скрипт, вспомогательный файл или иной механизм допустимы только когда прямо требуются владельцем; если существующий workflow не позволяет получить результат, executor сообщает точный blocker. Обычная UI- или кодовая правка не синхронизирует память, current context, roadmap или policy: это делается только по прямому запросу владельца либо для действительно значимого утверждённого решения. Проверка начинается с одного целевого сценария, а полная регрессия выполняется только для крупного, высокорискового или сквозного изменения. Отсутствие промежуточного сообщения не является критерием остановки: контроль ведётся по финальному сроку и фактическому состоянию рабочей копии; краткое обновление допустимо только при фактическом прогрессе или blocker.';
  content += ' Утверждённые изменения маршрутизируются по реальному риску: малое (локальные UI/CSS/текстовые правки, документация, узкие исправления и синхронизация правила памяти) исполняется одним executor-ом на самой быстрой доступной совместимой одобренной модели с fallback на Terra Medium, целевыми тестами и git diff --check; стандартное использует Terra Medium в ограниченном scope одного модуля с точным acceptance, без повторного полного context, с тестами затронутого модуля и E2E при изменении UI; крупное (архитектура, SQLite schema/migrations, security/auth, backup/restore, data integrity или сквозной многомодульный scope) требует полного startup/context, применимого подтверждения special model по действующей policy и полной регрессии/integrity-проверок. Strategy не относит UI-текст, CSS или узкое исправление к архитектуре без фактического основания. Полная регрессия нужна только для крупного, высокорискового или сквозного изменения и не запускается автоматически после каждого малого изменения. Во всех режимах сохраняются single writer/executor, один commit, чистый Git и относящийся UI E2E.';
  content += ' Managed sandbox является внешней границей платформы: репозиторий не может предоставить Full access, отключить approval или обойти запрет на создание .git/index.lock. При таком отказе executor сразу сообщает точную заблокированную операцию и внешний blocker, использует штатный platform approval flow, если он доступен, и после разрешения продолжает в том же thread без нового executor-а, циклов повторных попыток или неподтверждённого вывода о неисправности Git, БД либо сервера.';
  content += ' Если platform approval необходим, Strategy запрашивает его в текущем чате владельца; работа владельца с телефона не ослабляет owner-gates и не означает обход managed sandbox.';
  content += ' Запрос владельца изменить или построить в названном scope является standing authorization на in-scope реализацию, тесты, обычный git staging и один commit; Strategy не запрашивает повторное промежуточное подтверждение. Отдельное явное решение требуется только для удаления, force-операций, внешней публикации, расходов, изменений доступов/прав, стратегии, политики памяти, настроек/глобальной системы или существенного расширения scope. Managed-sandbox prompts отменить нельзя и они сообщаются только при возникновении.';
  content += ' Strategy — основной human-language координатор продукта, архитектуры, приоритетов и разработки: до решений он читает approved memory, current context, operating context, roadmap и фактический Git, отмечает существенные пробелы и противоречия и предлагает ближайшие MVP-шаги. Он не требует повторять известный контекст и не считает историю чата канонической истиной. Если чат стал слишком длинным, регулярно требует сжатия, теряет важные детали, путает решения или заметно расходует контекст, Strategy сам предлагает новый чат. Перед переходом он read-only сверяет approved memory, current context и roadmap на полноту значимых утверждённых решений, планов, ограничений, незавершённых задач и ближайших следующих шагов. При пробеле отдельный native task-thread синхронизирует канонический контекст; после сверки Strategy подтверждает, что новый чат продолжит работу по startup protocol без старой истории.';
  content += ' AGENTS.md является коротким обязательным startup-контрактом, а полный постоянный контекст хранится в operating-context и roadmap без ослабления safety gates. Первая проверка выбирается из явной карты существующих команд: docs-only — git diff --check; governance/memory — целевой Node test и check-memory; Python — один относящийся pytest-файл; operator panel backend — test_operator_panel.py; UI/E2E — test_operator_panel_e2e.py; JavaScript — node --check operator-panel.js. Широкая регрессия не используется для поиска проверки. Executor переиспользует здоровые project .venv, system Edge/browser, dependency caches, running server и owner-facing port; без доказанной проблемы не переустанавливает зависимости, не перезапускает runtime и не меняет порт. Отсутствующее или сломанное окружение является точным blocker либо отдельной утверждённой environment-задачей.';
  content += ' Структурированная память реализована как наследуемая цепочка Ядро → проект → подпроект → задача. AGENTS.md остаётся короткой конституцией Strategy, а изменяемые знания хранятся вне него. Strategy сначала определяет scope и тип задачи, читает паспорта выбранного scope и только релевантные блоки родительской цепочки; память sibling-проектов и подпроектов не загружается. Каждый scope имеет компактный паспорт. Правила наследуются сверху вниз, причём запреты Ядра нельзя отменить ниже. Память делится на постоянную, рабочую и историческую; история читается только по основанию. Активные записи имеют явные ownership, layer, type, status, source, valid_from и supersedes, а неоднозначные записи направляются в fail-closed очередь. Для исполнителя Strategy формирует временный минимальный task context pack и сохраняет audit маршрута без текста команды и внутреннего reasoning. Общие знания хранятся один раз на ближайшем общем уровне. Детерминированный context compiler собирает минимальный пакет; P0–P5 прошли acceptance на пилоте MetricHit «Редакция» и «Панель». Канонический контракт — documents/structured-memory.md, schema migration — v11, compiler — scripts/structured-memory.mjs.';
  content += ' Orchestration v1 добавляет воспроизводимый временный coordinator между Strategy и одним writer-ом без постоянного отдела или нового сервиса. Первый active pilot profile — MetricHit → Редакция. Coordinator получает только compiler-generated цепочку Ядро → MetricHit → Редакция → задача, формирует одну дочернюю execution card, декларативно выбирает только установленные разрешённые skills и выполняет предметную приёмку. Максимальная глубина — Strategy → coordinator → worker; worker не делегирует. Lifecycle route → coordinator claim → child delegation → worker evidence → coordinator approve/reject → sequential integration → Strategy completion enforced fail-closed и сохраняется в handoff metadata без prompt/reasoning. До трёх read-only research/audit веток разрешены, writer внутри change set один, глобальный предел четырёх writer leases и все resource/stale-base правила сохраняются.';
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
      multi_agent_pilot: {
        enabled: true,
        eligible: ['independent_read_only_research', 'independent_read_only_audit'],
        parallel_branches: { minimum: 2, maximum: 3 },
        orchestration: ['separate_questions_before_dispatch', 'strategy_synthesis_required'],
        branch_mutations_allowed: false,
        branch_forbidden_actions: ['repository_changes', 'database_changes', 'memory_changes', 'configuration_changes', 'git_changes', 'external_publication', 'spending', 'access_or_permission_changes', 'global_system_changes'],
        mutation_invariants: ['one_named_writer_executor', 'one_change_set', 'one_commit', 'clean_git'],
        parallel_writers_allowed: false,
        owner_approval_channel: 'current_owner_chat',
        managed_sandbox_bypass_claim_allowed: false,
      },
      controlled_parallel_execution_v1: {
        enabled: true, maximum_active_writers: 4, canonical_worktree_allowed: false,
        declarations: ['canonical_worktree', 'worktree', 'branch', 'base_head', 'paths', 'sqlite', 'shared'],
        conflict_rules: ['distinct_worktree', 'distinct_branch', 'path_ancestor_descendant', 'same_sqlite', 'same_shared_resource'],
        exclusive_resources: ['core', 'policy', 'config', 'migration', 'dependency', 'shared_runtime', 'central_db', 'memory', 'context_pack', 'integration'],
        distinct_project_sqlite_allowed: true, invalid_or_missing_declaration: 'fail_closed',
        integration: 'single_lease', stale_base: 'blocked', lifecycle_idempotent: true,
      },
      orchestration_v1: {
        enabled: true, implementation: 'structured_memory_and_handoff_metadata', new_service: false,
        maximum_delegation_depth: 2, path: ['strategy', 'department_coordinator', 'worker'],
        coordinator_role: 'temporary_read_only', permanent_department_chat: false,
        pilot_profile: { id: 'metrichit.editorial.v1', scope_id: 'scope:subproject:editorial', task_types: ['editorial', 'research'] },
        context_chain: ['scope:core', 'scope:project:metrichit', 'scope:subproject:editorial', 'scope:task'],
        sibling_memory_loading: false, child_execution_cards: 1, writers_per_change_set: 1,
        maximum_read_only_research_branches: 3, skills: 'declarative_installed_allowlist_no_auto_install',
        lifecycle: ['routed', 'coordinator_claimed', 'delegated', 'worker_in_progress', 'worker_submitted', 'domain_approved', 'integrating', 'integrated', 'completed'],
        rejection_returns_to: 'delegated_with_audit_preserved', completion_requires: ['closed_parent_context_pack', 'coordinator_approval', 'integration_result', 'clean_delivery_evidence'],
      },
      small_change_fast_path: {
        eligible: ['isolated_ui_css_text', 'narrow_fix', 'documentation', 'approved_memory_rule_sync'],
        strategy_full_startup_completed_once: true,
        handoff_context: ['owner_approval', 'exact_scope_acceptance', 'branch_head_status', 'relevant_canonical_references'],
        executor_reads: ['agents_rules', 'branch_head_status', 'scope_files_and_contracts', 'targeted_read_only_memory'],
        repeat_full_context_required: false,
        repo_side_handoff_required: false,
        additional_task_or_agent_required: false,
        planning_artifact_required: false,
        task_brief: ['result', 'scope', 'first_check', 'forbidden_changes'],
        vague_while_you_are_there_expansion_allowed: false,
        unrequested_auxiliary_artifacts_or_mechanisms_allowed: false,
        ordinary_technical_change_syncs_canonical_memory_or_context: false,
        canonical_sync_allowed_for: ['direct_owner_request', 'genuinely_significant_approved_decision'],
        significant_memory_uses_same_executor_and_idempotent_workflow: true,
        maximum_modified_tracked_files: 3,
        new_files_allowed: false,
        excluded_change_categories: ['dependencies', 'runtime_changes', 'configuration_changes', 'system_changes', 'data_schema_or_migrations'],
        limit_exceeded_routes_to: 'standard_staged_task_before_implementation',
        dirty_worktree_mutations_allowed: false,
        dirty_worktree_response: 'report_exact_dirty_files_and_wait_for_new_direct_owner_decision',
        dirty_worktree_forbidden_actions: ['absorb', 'restore', 'delete', 'commit', 'work_around'],
        existing_fast_targeted_check_required: true,
        unknown_targeted_check_routes_to: 'standard_task_identify_existing_scope_check_before_mutations',
        broad_regression_for_check_discovery_allowed: false,
        intermediate_message_absence_is_stop_criterion: false,
        progress_control: 'final_deadline_and_actual_worktree_result',
        responsible_executors: 1,
        commits: 1,
        excluded: ['architecture', 'sqlite_schema_or_migrations', 'business_logic', 'authorization', 'security', 'backup_restore', 'data_integrity', 'multi_module_scope', 'unclear_scope_or_approval', 'overlapping_dirty_worktree', 'head_or_context_mismatch', 'material_contradiction'],
      },
      risk_routing: {
        classifier_must_use_actual_risk: true,
        ui_text_css_narrow_fix_are_not_architecture_by_default: true,
        fast_path_uses_fastest_available_compatible_approved_executor_model: true,
        fast_path_model_owner_confirmation_required: false,
        fast_path_model_unavailable_fallback: 'GPT-5.6 Terra / Medium',
        standard_tasks_model: 'GPT-5.6 Terra / Medium',
        owner_visible_strategy_model_automatically_changed: false,
        special_model_policy_preserved: true,
        small: { scope: ['local_ui_css_text', 'documentation', 'narrow_fix', 'approved_memory_rule_sync'], executor: 1, checks: ['targeted_tests', 'git_diff_check'] },
        standard: { scope: ['bounded_one_module', 'exact_acceptance'], repeat_full_project_context_required: false, checks: ['affected_module_tests', 'ui_e2e_when_ui_changes'] },
        major: { scope: ['architecture', 'sqlite_schema_or_migrations', 'security_or_auth', 'backup_restore', 'data_integrity', 'cross_module'], checks: ['full_startup_context', 'applicable_special_model_approval', 'full_regression', 'integrity_checks'] },
        full_regression_required_for: ['major_change', 'high_risk_change', 'cross_module_change'],
        full_regression_automatic_for_every_small_change: false,
        quality_invariants: ['single_writer_executor', 'one_commit', 'clean_git', 'relevant_ui_e2e', 'full_checks_for_sensitive_high_risk_changes'],
      },
      targeted_check_map: {
        docs_only: 'git diff --check',
        governance_memory: ['node --test tests/decision-governance-policy.test.mjs', 'node scripts/check-memory.mjs'],
        python_module: '.\\.venv\\Scripts\\python.exe -m pytest tests_python\\test_<module>.py -q',
        operator_panel_backend: '.\\.venv\\Scripts\\python.exe -m pytest tests_python\\test_operator_panel.py -q',
        operator_panel_ui_e2e: '.\\.venv\\Scripts\\python.exe -m pytest tests_python\\test_operator_panel_e2e.py -q',
        javascript_syntax: 'node --check src\\metrichit_os\\operator_panel_assets\\operator-panel.js',
        broad_regression_reserved_for: ['major', 'high_risk', 'cross_module'],
      },
      environment_readiness: {
        reuse: ['project_venv', 'system_edge_or_browser', 'dependency_caches', 'healthy_running_server', 'owner_facing_port'],
        no_reinstall_restart_or_port_change_without_evidence: true,
        absent_or_broken_runtime: ['exact_blocker', 'separately_approved_environment_task'],
        forbidden_without_separate_scope: ['install_software', 'change_windows_or_global_settings', 'start_persistent_server', 'change_port'],
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
    hierarchical_memory_target: {
      hierarchy: ['core', 'project', 'subproject', 'task'],
      agents_role: 'compact_strategy_constitution',
      route_before_read: ['scope', 'task_type'],
      scope_passport_fields: ['id', 'purpose', 'current_goal', 'responsibility_boundaries', 'active_rules', 'prohibitions', 'priority', 'next_step', 'relationships', 'memory_pointers'],
      inheritance: { direction: 'top_down', core_prohibitions_overridable: false, lower_scopes: 'clarify_or_extend_only', common_knowledge: 'nearest_common_ancestor_reference' },
      memory_layers: ['permanent', 'working', 'historical'],
      default_read_layers: ['permanent', 'working_summary'],
      historical_read_reasons: ['dispute', 'investigation', 'decision_provenance', 'direct_owner_request'],
      record_fields: ['scope', 'project_id', 'subproject_id_optional', 'memory_layer', 'type', 'status', 'source', 'valid_from', 'supersedes'],
      freshness_statuses: ['active', 'superseded', 'outdated', 'needs_review', 'historical'],
      ambiguous_or_unowned_records: 'triage_queue_excluded_from_active_context',
      task_context_pack: ['result', 'project_id', 'subproject_id_optional', 'relevant_facts_and_rules', 'allowed_changes', 'forbidden_changes', 'first_check', 'acceptance', 'recent_related_decisions', 'open_obligations'],
      task_context_lifecycle: 'temporary_close_after_task',
      permanent_write_after_task: 'significant_confirmed_outcome_only',
      routing_audit: ['selected_scope', 'task_type', 'read_block_ids', 'routing_basis', 'delivered_pack_ids'],
      routing_audit_excludes: ['chain_of_thought', 'private_reasoning'],
      material_ambiguity: 'ask_one_short_owner_question',
      context_compiler_inputs: ['AGENTS.md', 'project_passport', 'subproject_passport', 'active_task_type_rules', 'recent_related_decisions', 'open_obligations'],
      context_compiler_output: 'minimal_sufficient_deterministic_context_pack',
      sibling_scope_loading: false,
    },
    hierarchical_memory_plan: [
      { priority: 'P0', stage: 'contract_and_baseline', acceptance: ['one_canonical_specification', 'explicit_rule_precedence', 'test_command_map', 'no_owner_gate_conflicts', 'current_context_load_baseline'] },
      { priority: 'P1', stage: 'scope_passports_and_record_ownership', depends_on: 'P0', pilot_scopes: ['core', 'metrichit', 'metrichit_editorial', 'metrichit_panel'], acceptance: ['every_test_object_has_one_scope', 'unowned_record_excluded_from_active_memory', 'common_knowledge_not_duplicated'] },
      { priority: 'P2', stage: 'layers_freshness_and_inheritance', depends_on: 'P1', acceptance: ['core_prohibition_cannot_be_overridden', 'supersedes_preserves_history', 'no_sibling_leakage'] },
      { priority: 'P3', stage: 'strategy_router_context_pack_and_audit', depends_on: 'P2', acceptance: ['required_pack_fields_present', 'only_relevant_records_loaded', 'audit_excludes_internal_reasoning', 'temporary_pack_closed_after_task'] },
      { priority: 'P4', stage: 'context_compiler_and_efficiency', depends_on: 'P3', acceptance: ['deterministic_repeat', 'history_and_siblings_not_read_without_reason', 'measurably_lower_load_than_baseline', 'mandatory_rules_retained'] },
      { priority: 'P5', stage: 'metrichit_editorial_and_panel_pilot', depends_on: 'P4', acceptance: ['editorial_gets_core_metrichit_editorial', 'panel_gets_core_metrichit_panel', 'no_cross_subproject_memory', 'ambiguous_panel_command_requests_scope', 'control_tasks_pass_without_manual_extra_context'] },
    ],
    hierarchical_memory_implemented: true,
    hierarchical_memory_delivery: {
      completed_stages: ['P0', 'P1', 'P2', 'P3', 'P4', 'P5'],
      specification: 'documents/structured-memory.md',
      schema_migration: 11,
      compiler: 'scripts/structured-memory.mjs',
      pilot_scopes: ['metrichit_editorial', 'metrichit_panel'],
      baseline_bytes: 147579,
    },
    hierarchical_memory_priority: 'number_one_core_memory_development_priority',
    strategy: { mode: 'read_only', role: 'human_facing_router', exact_scope_only: true, observable_reporting_only: true, repository_file_modifications_allowed: false, executor_result: ['verified_clean_git_result', 'exact_technical_blocker'], recovery: 'new_explicit_owner_direction_only' },
    handoff: { create_command: 'handoff-create', next_command: 'handoff-next', claim_command: 'handoff-claim', integrate_command: 'handoff-integrate', complete_command: 'handoff-complete', orchestration_commands: ['handoff-coordinator-claim', 'handoff-delegate-child', 'handoff-worker-claim', 'handoff-worker-submit', 'handoff-coordinator-review', 'handoff-integration-result', 'handoff-strategy-complete'], task_type: 'standalone_task', atomic_decision_task_link: true, native_task_thread: 'internal_execution_mechanism', repo_side_role: 'decision_task_context_and_resource_lease_audit', repo_side_is_execution_queue: false, permanent_developer_chat_required: false, user_workflow_requires_lifecycle_commands: false, lifecycle: ['ready', 'in_progress', 'completed'], claim_complete_idempotent: true, completion_links_commit_hash: true, one_native_thread_per_user_engineering_decision: true, strategy_checks_existing_thread_by_user_turn_or_decision_before_create: true, repeated_user_turn_routing_is_idempotent: true, existing_thread_response_includes_id_and_status: true, existing_thread_prevents_second_creation: true, new_engineering_task_requires_new_native_thread: true, strategy_may_replace_existing_or_completed_thread_scope: false, active_engineering_thread_blocks_second_writer_thread: false, maximum_active_writer_executors: 4, maximum_parallel_read_only_branches: 3, active_writer_thread_requires_wait_or_owner_explicit_cancellation: false, resource_conflict_requires_wait: true, integration_is_serialized: true, thread_closed_after_commit_result_and_clean_git_status: true, completed_thread_reuse_allowed: false },
    future_ui: ['memory_candidate_management', 'owner_decision_center'],
    functionality_implemented: 'repo_side_record_audit_with_native_task_thread_execution',
    revision,
    supersedes_semantic_revision: revision - 1,
    evidence: { path: decisionPath },
  });
  const policy = JSON.parse(policyData);
  const operationsContent = 'SERVER и C:\\MetricHit\\workspace остаются primary workspace MetricHit. Strategy — read-only human-facing router. Controlled parallel execution v1 допускает максимум четыре независимых writer-а: каждый работает в отдельном неканоническом Git worktree и ветке, объявляет точные path/SQLite/shared resources и имеет один commit. Пересечения, пятая задача и core/shared resources блокируются fail-closed; разные project SQLite совместимы; central control-plane, context pack, memory/policy и integration сериализованы. Read-only research pilot 2–3 веток сохраняется. Orchestration v1 активирует первый временный read-only coordinator profile MetricHit → Редакция: compiler выдаёт только цепочку Ядро → MetricHit → Редакция → задача; coordinator создаёт одну child card, выбирает skills из allowlist и принимает domain evidence одного writer-а. Максимальная глубина два перехода, до трёх read-only веток, lifecycle и sequential integration enforced через handoff metadata; UI, daemon, scheduler, API и автономная production-редакция не добавлены. Fast path, clean Git, проверки, Sol/Luna gates, owner-gates и managed sandbox сохраняются.';
  const hierarchicalOperationsContent = ' AGENTS.md является короткой конституцией Strategy. Перед задачей Strategy определяет scope и тип, затем compiler читает только паспорта и активную память цепочки Ядро → проект → подпроект → задача. Для executor формируется минимальный временный task context pack; sibling scope и история без основания не загружаются, а audit сохраняет fingerprint и технические сигналы без текста команды и внутреннего reasoning. P0–P5 реализованы и прошли acceptance на пилоте MetricHit «Редакция» и «Панель»; контракт находится в documents/structured-memory.md, schema — migration v11.';
  const operationsData = JSON.stringify({
    revision: operationsRevision,
    supersedes_candidate_id: uuid(`candidate:${operationsSemanticKey}:${operationsRevision - 1}`),
    delivery: { result: ['verified_clean_git_result', 'exact_technical_blocker'], partial_output_is_delivery: false, intermediate_message_absence_is_stop_criterion: false, progress_control: 'final_deadline_and_actual_worktree_result', human_update: 'factual_progress_or_blocker_only' },
    external_approval: { preflight_visibility_required: true, preflight_waits_for_approval: false },
    startup_surface: { agents_is_compact_contract: true, detailed_context: ['documents/operating-context.md', 'documents/roadmap.md'], safety_gates_preserved: true },
    targeted_check_map: policy.execution.targeted_check_map,
    environment_readiness: policy.execution.environment_readiness,
    executor_model_routing: { fast_path: 'fastest_available_compatible_approved', fallback: 'GPT-5.6 Terra / Medium', standard: 'GPT-5.6 Terra / Medium', owner_visible_strategy_model_automatically_changed: false, sol_luna_owner_gates_preserved: true },
    task_brief_template: ['result', 'scope', 'first_check', 'forbidden_changes'],
    scope_control: { existing_workflows_only: true, unlisted_artifacts_forbidden: ['plans', 'reports', 'scripts', 'files', 'tasks', 'abstractions', 'auxiliary_workflows'], vague_while_you_are_there_expansion_allowed: false, scope_expansion: 'new_direct_owner_approval_required', replacement_executor_chain_allowed: false, recovery: 'new_explicit_owner_direction_only', fast_path_maximum_modified_tracked_files: 3, fast_path_new_files_allowed: false, fast_path_excluded_change_categories: ['dependencies', 'runtime_changes', 'configuration_changes', 'system_changes', 'data_schema_or_migrations'], fast_path_limit_exceeded_routes_to: 'standard_staged_task_before_implementation', dirty_worktree_mutations_allowed: false, dirty_worktree_response: 'report_exact_dirty_files_and_wait_for_new_direct_owner_decision', dirty_worktree_forbidden_actions: ['absorb', 'restore', 'delete', 'commit', 'work_around'], existing_fast_targeted_check_required: true, unknown_targeted_check_routes_to: 'standard_task_identify_existing_scope_check_before_mutations', broad_regression_for_check_discovery_allowed: false },
    canonical_sync: { ordinary_technical_change_allowed: false, allowed_for: ['direct_owner_request', 'genuinely_significant_approved_decision'] },
    context_routing_target: policy.hierarchical_memory_target,
    context_routing_plan: policy.hierarchical_memory_plan,
    context_routing_implemented: true,
    context_routing_delivery: policy.hierarchical_memory_delivery,
    primary_workspace: 'C:\\MetricHit\\workspace',
    strategy: { owner_visible: true, read_only: true, permanent_project_chat: true },
    repository_mutation: { responsible_executors_per_change_set: 1, maximum_parallel_writers: 4, commits_per_change_set: 1, in_scope_owner_request_is_authorization: true, redundant_intermediate_confirmation_required: false, parallel_writers_allowed: true, resource_leases_required: true, integration_serialized: true },
    controlled_parallel_execution_v1: policy.execution.controlled_parallel_execution_v1,
    orchestration_v1: policy.execution.orchestration_v1,
    multi_agent_pilot: policy.execution.multi_agent_pilot,
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
    decision_date: '2026-08-30',
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

    created.sources += Number(db.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-30', 'internal')`).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-30', 'internal', 1)`).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-30', 'internal', 1)`).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-30', 'internal', 1)`).run(candidateId, semanticKey, title, content, policyData, sourceId, owner).changes);

    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(owner, reviewedAt, 'Одобрено прямым решением владельца от 30.08.2026.', reviewedAt, candidateId);
    }
    created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-30', 'internal', 1)`).run(operationsCandidateId, operationsSemanticKey, 'Рабочий процесс SERVER, Strategy и executor', operationsContent + hierarchicalOperationsContent, operationsData, sourceId, owner).changes);
    const operationsCandidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(operationsCandidateId);
    if (operationsCandidate.status === 'pending') {
      db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(owner, reviewedAt, 'Одобрено прямым решением владельца от 30.08.2026.', reviewedAt, operationsCandidateId);
    }
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: policyData, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'decision governance candidate');
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(operationsCandidateId), { type: 'decision', semantic_key: operationsSemanticKey, title: 'Рабочий процесс SERVER, Strategy и executor', content: operationsContent + hierarchicalOperationsContent, data_json: operationsData, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'server strategy workflow candidate');
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
