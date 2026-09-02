import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyDecisionGovernancePolicy } from '../scripts/apply-decision-governance-policy.mjs';

test('decision governance policy is approved, exact and idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-decision-governance-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const first = applyDecisionGovernancePolicy(databasePath);
    const second = applyDecisionGovernancePolicy(databasePath);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 2 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

    const db = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const candidates = db.prepare('SELECT status,data_json FROM memory_candidates WHERE semantic_key=?').all(first.semanticKey);
      assert.equal(candidates.length, 1);
      assert.equal(candidates[0].status, 'approved');
      const data = JSON.parse(candidates[0].data_json);
      assert.equal(data.belongs_to, 'central_core');
      assert.equal(data.potential_decisions_auto_approve, false);
      assert.deepEqual(data.pre_save_checks, ['semantic_duplicate', 'evolution', 'conflicts']);
      assert.deepEqual(data.hierarchical_memory_target.hierarchy, ['core', 'project', 'subproject', 'task']);
      assert.equal(data.hierarchical_memory_target.agents_role, 'compact_strategy_constitution');
      assert.deepEqual(data.hierarchical_memory_target.route_before_read, ['scope', 'task_type']);
      assert.equal(data.hierarchical_memory_target.inheritance.core_prohibitions_overridable, false);
      assert.deepEqual(data.hierarchical_memory_target.memory_layers, ['permanent', 'working', 'historical']);
      assert.equal(data.hierarchical_memory_target.sibling_scope_loading, false);
      assert.deepEqual(data.hierarchical_memory_plan.map((stage) => stage.priority), ['P0', 'P1', 'P2', 'P3', 'P4', 'P5']);
      assert.deepEqual(data.hierarchical_memory_plan.at(-1).acceptance.slice(0, 3), ['editorial_gets_core_metrichit_editorial', 'panel_gets_core_metrichit_panel', 'no_cross_subproject_memory']);
      assert.equal(data.hierarchical_memory_implemented, true);
      assert.deepEqual(data.hierarchical_memory_delivery.completed_stages, ['P0', 'P1', 'P2', 'P3', 'P4', 'P5']);
      assert.equal(data.hierarchical_memory_delivery.schema_migration, 11);
      assert.equal(data.hierarchical_memory_delivery.baseline_bytes, 147579);
      assert.equal(data.execution.separate_llm_call_required, false);
      assert.equal(data.execution.target_overhead, 'few_percent_or_less');
      assert.equal(data.execution.implementation, 'native_codex_task_thread');
      assert.deepEqual(data.execution.canonical_path, ['strategy', 'native_codex_task_thread', 'commit_result']);
      assert.equal(data.execution.multi_agent_pilot.enabled, true);
      assert.deepEqual(data.execution.multi_agent_pilot.eligible, ['independent_read_only_research', 'independent_read_only_audit']);
      assert.deepEqual(data.execution.multi_agent_pilot.parallel_branches, { minimum: 2, maximum: 3 });
      assert.deepEqual(data.execution.multi_agent_pilot.orchestration, ['separate_questions_before_dispatch', 'strategy_synthesis_required']);
      assert.equal(data.execution.multi_agent_pilot.branch_mutations_allowed, false);
      assert.equal(data.execution.multi_agent_pilot.parallel_writers_allowed, false);
      assert.equal(data.execution.multi_agent_pilot.owner_approval_channel, 'current_owner_chat');
      assert.equal(data.execution.multi_agent_pilot.managed_sandbox_bypass_claim_allowed, false);
      assert.equal(data.execution.controlled_parallel_execution_v1.maximum_active_writers, 2);
      assert.equal(data.execution.controlled_parallel_execution_v1.canonical_worktree_allowed, false);
      assert.equal(data.execution.controlled_parallel_execution_v1.distinct_project_sqlite_allowed, true);
      assert.equal(data.execution.controlled_parallel_execution_v1.invalid_or_missing_declaration, 'fail_closed');
      assert.equal(data.execution.controlled_parallel_execution_v1.integration, 'single_lease');
      assert.deepEqual(data.execution.small_change_fast_path.eligible, ['isolated_ui_css_text', 'narrow_fix', 'documentation', 'approved_memory_rule_sync']);
      assert.equal(data.execution.small_change_fast_path.strategy_full_startup_completed_once, true);
      assert.deepEqual(data.execution.small_change_fast_path.handoff_context, ['owner_approval', 'exact_scope_acceptance', 'branch_head_status', 'relevant_canonical_references']);
      assert.deepEqual(data.execution.small_change_fast_path.executor_reads, ['agents_rules', 'branch_head_status', 'scope_files_and_contracts', 'targeted_read_only_memory']);
      assert.equal(data.execution.small_change_fast_path.repeat_full_context_required, false);
      assert.equal(data.execution.small_change_fast_path.repo_side_handoff_required, false);
      assert.equal(data.execution.small_change_fast_path.additional_task_or_agent_required, false);
      assert.equal(data.execution.small_change_fast_path.planning_artifact_required, false);
      assert.deepEqual(data.execution.small_change_fast_path.task_brief, ['result', 'scope', 'first_check', 'forbidden_changes']);
      assert.equal(data.execution.small_change_fast_path.vague_while_you_are_there_expansion_allowed, false);
      assert.equal(data.execution.small_change_fast_path.unrequested_auxiliary_artifacts_or_mechanisms_allowed, false);
      assert.equal(data.execution.small_change_fast_path.ordinary_technical_change_syncs_canonical_memory_or_context, false);
      assert.deepEqual(data.execution.small_change_fast_path.canonical_sync_allowed_for, ['direct_owner_request', 'genuinely_significant_approved_decision']);
      assert.equal(data.execution.small_change_fast_path.significant_memory_uses_same_executor_and_idempotent_workflow, true);
      assert.equal(data.execution.small_change_fast_path.maximum_modified_tracked_files, 3);
      assert.equal(data.execution.small_change_fast_path.new_files_allowed, false);
      assert.deepEqual(data.execution.small_change_fast_path.excluded_change_categories, ['dependencies', 'runtime_changes', 'configuration_changes', 'system_changes', 'data_schema_or_migrations']);
      assert.equal(data.execution.small_change_fast_path.limit_exceeded_routes_to, 'standard_staged_task_before_implementation');
      assert.equal(data.execution.small_change_fast_path.dirty_worktree_mutations_allowed, false);
      assert.equal(data.execution.small_change_fast_path.dirty_worktree_response, 'report_exact_dirty_files_and_wait_for_new_direct_owner_decision');
      assert.equal(data.execution.small_change_fast_path.existing_fast_targeted_check_required, true);
      assert.equal(data.execution.small_change_fast_path.unknown_targeted_check_routes_to, 'standard_task_identify_existing_scope_check_before_mutations');
      assert.equal(data.execution.small_change_fast_path.broad_regression_for_check_discovery_allowed, false);
      assert.equal(data.execution.small_change_fast_path.intermediate_message_absence_is_stop_criterion, false);
      assert.equal(data.execution.small_change_fast_path.progress_control, 'final_deadline_and_actual_worktree_result');
      assert.equal(data.execution.small_change_fast_path.responsible_executors, 1);
      assert.equal(data.execution.small_change_fast_path.commits, 1);
      assert.deepEqual(data.execution.small_change_fast_path.excluded, ['architecture', 'sqlite_schema_or_migrations', 'business_logic', 'authorization', 'security', 'backup_restore', 'data_integrity', 'multi_module_scope', 'unclear_scope_or_approval', 'overlapping_dirty_worktree', 'head_or_context_mismatch', 'material_contradiction']);
      assert.equal(data.execution.risk_routing.classifier_must_use_actual_risk, true);
      assert.equal(data.execution.risk_routing.ui_text_css_narrow_fix_are_not_architecture_by_default, true);
      assert.equal(data.execution.risk_routing.fast_path_uses_fastest_available_compatible_approved_executor_model, true);
      assert.equal(data.execution.risk_routing.fast_path_model_owner_confirmation_required, false);
      assert.equal(data.execution.risk_routing.fast_path_model_unavailable_fallback, 'GPT-5.6 Terra / Medium');
      assert.equal(data.execution.risk_routing.standard_tasks_model, 'GPT-5.6 Terra / Medium');
      assert.equal(data.execution.risk_routing.owner_visible_strategy_model_automatically_changed, false);
      assert.deepEqual(data.execution.risk_routing.small.checks, ['targeted_tests', 'git_diff_check']);
      assert.deepEqual(data.execution.risk_routing.standard.checks, ['affected_module_tests', 'ui_e2e_when_ui_changes']);
      assert.deepEqual(data.execution.risk_routing.major.checks, ['full_startup_context', 'applicable_special_model_approval', 'full_regression', 'integrity_checks']);
      assert.deepEqual(data.execution.risk_routing.full_regression_required_for, ['major_change', 'high_risk_change', 'cross_module_change']);
      assert.equal(data.execution.risk_routing.full_regression_automatic_for_every_small_change, false);
      assert.equal(data.platform_boundary.managed_sandbox_is_external, true);
      assert.equal(data.platform_boundary.repository_can_grant_full_access_or_disable_approval, false);
      assert.equal(data.platform_boundary.repository_can_bypass_git_index_lock_denial, false);
      assert.deepEqual(data.platform_boundary.on_denial, ['report_exact_blocked_operation_immediately', 'identify_external_blocker', 'use_platform_approval_if_available', 'continue_same_executor_after_approval']);
      assert.deepEqual(data.platform_boundary.forbidden_reactions, ['spawn_replacement_executor', 'retry_loop', 'claim_git_database_or_server_failure_without_evidence']);
      assert.equal(data.implementation_authorization.owner_in_scope_request_is_standing_authorization, true);
      assert.deepEqual(data.implementation_authorization.includes, ['implementation', 'tests', 'ordinary_git_staging', 'one_commit']);
      assert.equal(data.implementation_authorization.redundant_intermediate_confirmation_required, false);
      assert.deepEqual(data.implementation_authorization.separate_owner_decision_required_for, ['deletion', 'force_operations', 'external_publication', 'spending', 'access_or_permission_changes', 'strategy_changes', 'memory_policy_changes', 'settings_or_global_system_changes', 'material_scope_expansion']);
      assert.equal(data.implementation_authorization.managed_sandbox_prompts_removable, false);
      assert.deepEqual(data.owner_gates_preserved, ['deletion', 'force_operations', 'access_changes', 'publication', 'spending', 'strategy_changes', 'memory_changes', 'settings_changes', 'other_dangerous_actions']);
      const operationsCandidates = db.prepare('SELECT status,data_json,content FROM memory_candidates WHERE semantic_key=?').all(first.operationsSemanticKey);
      assert.equal(operationsCandidates.length, 1);
      assert.equal(operationsCandidates[0].status, 'approved');
      const operations = JSON.parse(operationsCandidates[0].data_json);
      assert.equal(operations.revision, 17);
      assert.equal(operations.startup_surface.agents_is_compact_contract, true);
      assert.equal(operations.startup_surface.safety_gates_preserved, true);
      assert.deepEqual(operations.context_routing_target.hierarchy, ['core', 'project', 'subproject', 'task']);
      assert.deepEqual(operations.context_routing_plan.map((stage) => stage.priority), ['P0', 'P1', 'P2', 'P3', 'P4', 'P5']);
      assert.equal(operations.context_routing_implemented, true);
      assert.deepEqual(operations.context_routing_delivery.completed_stages, ['P0', 'P1', 'P2', 'P3', 'P4', 'P5']);
      assert.equal(operations.targeted_check_map.docs_only, 'git diff --check');
      assert.equal(operations.targeted_check_map.operator_panel_backend, '.\\.venv\\Scripts\\python.exe -m pytest tests_python\\test_operator_panel.py -q');
      assert.equal(operations.targeted_check_map.operator_panel_ui_e2e, '.\\.venv\\Scripts\\python.exe -m pytest tests_python\\test_operator_panel_e2e.py -q');
      assert.equal(operations.targeted_check_map.javascript_syntax, 'node --check src\\metrichit_os\\operator_panel_assets\\operator-panel.js');
      assert.equal(operations.environment_readiness.no_reinstall_restart_or_port_change_without_evidence, true);
      assert.equal(operations.executor_model_routing.owner_visible_strategy_model_automatically_changed, false);
      assert.equal(operations.executor_model_routing.sol_luna_owner_gates_preserved, true);
      assert.deepEqual(operations.task_brief_template, ['result', 'scope', 'first_check', 'forbidden_changes']);
      assert.deepEqual(operations.delivery.result, ['verified_clean_git_result', 'exact_technical_blocker']);
      assert.equal(operations.delivery.partial_output_is_delivery, false);
      assert.equal(operations.delivery.intermediate_message_absence_is_stop_criterion, false);
      assert.equal(operations.delivery.progress_control, 'final_deadline_and_actual_worktree_result');
      assert.equal(operations.scope_control.replacement_executor_chain_allowed, false);
      assert.equal(operations.scope_control.fast_path_maximum_modified_tracked_files, 3);
      assert.equal(operations.scope_control.fast_path_new_files_allowed, false);
      assert.equal(operations.scope_control.dirty_worktree_mutations_allowed, false);
      assert.equal(operations.scope_control.existing_fast_targeted_check_required, true);
      assert.equal(operations.scope_control.broad_regression_for_check_discovery_allowed, false);
      assert.equal(operations.scope_control.existing_workflows_only, true);
      assert.equal(operations.scope_control.vague_while_you_are_there_expansion_allowed, false);
      assert.deepEqual(operations.scope_control.unlisted_artifacts_forbidden, ['plans', 'reports', 'scripts', 'files', 'tasks', 'abstractions', 'auxiliary_workflows']);
      assert.equal(operations.scope_control.scope_expansion, 'new_direct_owner_approval_required');
      assert.equal(operations.canonical_sync.ordinary_technical_change_allowed, false);
      assert.deepEqual(operations.canonical_sync.allowed_for, ['direct_owner_request', 'genuinely_significant_approved_decision']);
      assert.equal(operations.strategy.owner_visible, true);
      assert.equal(operations.strategy.read_only, true);
      assert.equal(operations.repository_mutation.responsible_executors_per_change_set, 1);
      assert.equal(operations.repository_mutation.commits_per_change_set, 1);
      assert.equal(operations.repository_mutation.maximum_parallel_writers, 2);
      assert.equal(operations.repository_mutation.parallel_writers_allowed, true);
      assert.equal(operations.repository_mutation.resource_leases_required, true);
      assert.equal(operations.repository_mutation.integration_serialized, true);
      assert.deepEqual(operations.multi_agent_pilot.parallel_branches, { minimum: 2, maximum: 3 });
      assert.equal(operations.small_change_fast_path.repo_side_handoff_required, false);
      assert.equal(operations.risk_routing.fast_path_uses_fastest_available_compatible_approved_executor_model, true);
      assert.equal(operations.repository_mutation.in_scope_owner_request_is_authorization, true);
      assert.equal(operations.repository_mutation.redundant_intermediate_confirmation_required, false);
      assert.equal(operations.platform_boundary.managed_sandbox_is_external, true);
      assert.match(operationsCandidates[0].content, /managed sandbox/i);
      assert.equal(data.strategy.mode, 'read_only');
      assert.equal(data.strategy.role, 'human_facing_router');
      assert.equal(data.strategy.exact_scope_only, true);
      assert.equal(data.strategy.observable_reporting_only, true);
      assert.equal(data.strategy.repository_file_modifications_allowed, false);
      assert.deepEqual(data.strategy.executor_result, ['verified_clean_git_result', 'exact_technical_blocker']);
      assert.equal(data.strategy.recovery, 'new_explicit_owner_direction_only');
      assert.equal(data.handoff.create_command, 'handoff-create');
      assert.equal(data.handoff.next_command, 'handoff-next');
      assert.equal(data.handoff.claim_command, 'handoff-claim');
      assert.equal(data.handoff.integrate_command, 'handoff-integrate');
      assert.equal(data.handoff.complete_command, 'handoff-complete');
      assert.equal(data.handoff.atomic_decision_task_link, true);
      assert.equal(data.handoff.native_task_thread, 'internal_execution_mechanism');
      assert.equal(data.handoff.repo_side_role, 'decision_task_context_and_resource_lease_audit');
      assert.equal(data.handoff.repo_side_is_execution_queue, false);
      assert.equal(data.handoff.permanent_developer_chat_required, false);
      assert.equal(data.handoff.user_workflow_requires_lifecycle_commands, false);
      assert.deepEqual(data.handoff.lifecycle, ['ready', 'in_progress', 'completed']);
      assert.equal(data.handoff.claim_complete_idempotent, true);
      assert.equal(data.handoff.one_native_thread_per_user_engineering_decision, true);
      assert.equal(data.handoff.strategy_checks_existing_thread_by_user_turn_or_decision_before_create, true);
      assert.equal(data.handoff.repeated_user_turn_routing_is_idempotent, true);
      assert.equal(data.handoff.existing_thread_response_includes_id_and_status, true);
      assert.equal(data.handoff.existing_thread_prevents_second_creation, true);
      assert.equal(data.handoff.new_engineering_task_requires_new_native_thread, true);
      assert.equal(data.handoff.strategy_may_replace_existing_or_completed_thread_scope, false);
      assert.equal(data.handoff.active_engineering_thread_blocks_second_writer_thread, false);
      assert.equal(data.handoff.maximum_active_writer_executors, 2);
      assert.equal(data.handoff.resource_conflict_requires_wait, true);
      assert.equal(data.handoff.integration_is_serialized, true);
      assert.equal(data.handoff.maximum_parallel_read_only_branches, 3);
      assert.equal(data.handoff.active_writer_thread_requires_wait_or_owner_explicit_cancellation, false);
      assert.equal(data.handoff.thread_closed_after_commit_result_and_clean_git_status, true);
      assert.equal(data.handoff.completed_thread_reuse_allowed, false);
      assert.equal(data.revision, 30);
      assert.equal(db.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count, 0);
    } finally {
      db.close();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});

test('canonical workflow documents preserve the small-change fast path and sandbox boundary', () => {
  const agents = readFileSync(resolve('AGENTS.md'), 'utf8');
  const decision = readFileSync(resolve('knowledge/decisions/decision-governance-policy-2026-08-15.md'), 'utf8');
  const operating = readFileSync(resolve('documents/operating-context.md'), 'utf8');
  const roadmap = readFileSync(resolve('documents/roadmap.md'), 'utf8');
  const serverWorkflow = readFileSync(resolve('documents/server-workflow.md'), 'utf8');

  for (const document of [agents, decision, operating, roadmap]) assert.match(document, /executor/i);
  assert.match(agents, /Strategy[^\r\n]*read-only/i);
  assert.match(agents, /Стандартное изменение/);
  assert.match(decision, /human-facing router/i);
  assert.match(operating, /human-facing router/i);
  assert.match(decision, /owner-gates[^\r\n]*сохраняются/i);
  assert.match(agents, /постоянным разрешением на in-scope реализацию/);
  assert.match(decision, /standing authorization/i);
  assert.match(operating, /standing authorization/i);
  assert.match(serverWorkflow, /Executor/i);
  assert.doesNotMatch(operating, /режиме Full access \+ Never ask/);
  assert.doesNotMatch(roadmap, /режиме Full access \+ Never ask/);
  assert.match(operating, /Карта быстрых целевых проверок/);
  assert.match(operating, /test_operator_panel_e2e\.py/);
  assert.match(agents, /самую быструю доступную совместимую/);
  assert.match(agents, /owner-facing порт/);
  for (const document of [agents, decision, operating]) assert.match(document, /(?:multi-agent|read-only pilot|Контролируемый pilot)/i);
  assert.match(agents, /текущем чате с владельцем/);
});

test('decision governance workflow refuses a competing approved truth', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-decision-governance-conflict-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const sourceId = '10000000-0000-4000-a000-000000000001';
    const candidateId = '10000000-0000-4000-a000-000000000002';
    const seed = `
      import { DatabaseSync } from 'node:sqlite';
      const db = new DatabaseSync(process.argv[1]);
      db.prepare("INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Legacy', 'Legacy source', 'active', 'owner', 'internal')").run('${sourceId}');
      db.prepare("INSERT INTO memory_candidates (id,type,semantic_key,title,content,status,source_id,author,access_level) VALUES (?, 'decision', 'architecture.decision_governance_policy', 'Legacy', 'Different policy', 'pending', ?, 'owner', 'internal')").run('${candidateId}', '${sourceId}');
      db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-08-14T00:00:00.000Z' WHERE id=?").run('${candidateId}');
      db.close();
    `;
    execFileSync(process.execPath, ['--input-type=module', '--eval', seed, databasePath]);
    assert.throws(
      () => execFileSync(process.execPath, [resolve('scripts/apply-decision-governance-policy.mjs'), databasePath]),
      /explicit superseding revision/,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});

test('decision governance workflow refuses a pending semantic duplicate', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-decision-governance-pending-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const sourceId = '20000000-0000-4000-a000-000000000001';
    const candidateId = '20000000-0000-4000-a000-000000000002';
    const seed = `
      import { DatabaseSync } from 'node:sqlite';
      const db = new DatabaseSync(process.argv[1]);
      db.prepare("INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Pending source', 'Pending source', 'active', 'owner', 'internal')").run('${sourceId}');
      db.prepare("INSERT INTO memory_candidates (id,type,semantic_key,title,content,status,source_id,author,access_level) VALUES (?, 'decision', 'architecture.decision_governance_policy', 'Pending duplicate', 'Pending duplicate', 'pending', ?, 'owner', 'internal')").run('${candidateId}', '${sourceId}');
      db.close();
    `;
    execFileSync(process.execPath, ['--input-type=module', '--eval', seed, databasePath]);
    assert.throws(
      () => execFileSync(process.execPath, [resolve('scripts/apply-decision-governance-policy.mjs'), databasePath]),
      /explicit superseding revision/,
    );
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});

test('decision governance workflow accepts its approved task context evolution', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-decision-governance-task-context-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const prior = applyDecisionGovernancePolicy(databasePath);
    const sourceId = '30000000-0000-4000-a000-000000000001';
    const candidateId = '30000000-0000-4000-a000-000000000002';
    const data = JSON.stringify({ handoff_task_id: '30000000-0000-4000-a000-000000000003', supersedes_candidate_id: prior.candidateId });
    const seed = `
      import { DatabaseSync } from 'node:sqlite';
      const db = new DatabaseSync(process.argv[1]);
      db.prepare("INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Task context source', 'Task context source', 'active', 'owner', 'internal')").run('${sourceId}');
      db.prepare("INSERT INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,access_level) VALUES (?, 'decision', 'architecture.decision_governance_policy', 'Task context', 'Approved task context', ?, 'pending', ?, 'owner', 'internal')").run('${candidateId}', '${data.replaceAll("'", "''")}', '${sourceId}');
      db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-08-16T17:07:33.145Z' WHERE id=?").run('${candidateId}');
      db.close();
    `;
    execFileSync(process.execPath, ['--input-type=module', '--eval', seed, databasePath]);
    const reapplied = applyDecisionGovernancePolicy(databasePath);
    assert.deepEqual(reapplied.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});
