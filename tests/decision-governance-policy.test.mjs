import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
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
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
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
      assert.equal(data.execution.separate_llm_call_required, false);
      assert.equal(data.execution.target_overhead, 'few_percent_or_less');
      assert.equal(data.execution.implementation, 'native_codex_task_thread');
      assert.deepEqual(data.execution.canonical_path, ['strategy', 'native_codex_task_thread', 'commit_result']);
      assert.equal(data.strategy.mode, 'read_only');
      assert.deepEqual(data.strategy.permitted_actions, ['discuss', 'analyze', 'read_approved_memory', 'read_git', 'read_documents', 'create_native_task_thread']);
      assert.equal(data.strategy.repository_file_modifications_allowed, false);
      assert.deepEqual(data.strategy.repository_file_modification_scope, ['memory', 'docs', 'config', 'code', 'tests']);
      assert.equal(data.strategy.repository_file_modification_size_exception, false);
      assert.equal(data.strategy.repository_file_modifications_require, 'separate_native_task_thread');
      assert.equal(data.handoff.create_command, 'handoff-create');
      assert.equal(data.handoff.next_command, 'handoff-next');
      assert.equal(data.handoff.claim_command, 'handoff-claim');
      assert.equal(data.handoff.complete_command, 'handoff-complete');
      assert.equal(data.handoff.atomic_decision_task_link, true);
      assert.equal(data.handoff.native_task_thread, 'execution_mechanism');
      assert.equal(data.handoff.repo_side_role, 'decision_task_context_and_result_audit');
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
      assert.equal(data.handoff.active_engineering_thread_blocks_second_thread, true);
      assert.equal(data.handoff.active_thread_requires_wait_or_owner_explicit_cancellation, true);
      assert.equal(data.handoff.thread_closed_after_commit_result_and_clean_git_status, true);
      assert.equal(data.revision, 11);
      assert.equal(db.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count, 0);
    } finally {
      db.close();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
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
