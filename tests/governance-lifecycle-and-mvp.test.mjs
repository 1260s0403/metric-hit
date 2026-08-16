import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyModelRoutingPolicy } from '../scripts/apply-model-routing-policy.mjs';
import { applyMvpSpeedPrinciple } from '../scripts/apply-mvp-speed-principle.mjs';

test('model lifecycle and MVP speed policies are approved, exact and idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-governance-lifecycle-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const modelFirst = applyModelRoutingPolicy(databasePath);
    const modelSecond = applyModelRoutingPolicy(databasePath);
    const mvpFirst = applyMvpSpeedPrinciple(databasePath);
    const mvpSecond = applyMvpSpeedPrinciple(databasePath);
    assert.deepEqual(modelFirst.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(modelSecond.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    assert.deepEqual(mvpFirst.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(mvpSecond.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const db = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const model = db.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(modelFirst.candidateId);
      const mvp = db.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(mvpFirst.candidateId);
      assert.equal(model.status, 'approved');
      assert.equal(mvp.status, 'approved');
      assert.equal(JSON.parse(model.data_json).reclassify_before_each_new_task, true);
      assert.equal(JSON.parse(model.data_json).special_model_approval_carries_to_next_task, false);
      assert.equal(JSON.parse(model.data_json).engineering_task_thread_must_verify_actual_model_on_start, true);
      assert.equal(JSON.parse(model.data_json).special_model_mismatch_blocks_critical_actions, true);
      assert.equal(JSON.parse(model.data_json).special_model_mismatch_action, 'pause_and_request_owner_model_switch');
      assert.equal(JSON.parse(model.data_json).after_special_model_switch, 'continue_current_state_without_rollback_new_thread_or_restart');
      assert.equal(JSON.parse(mvp.data_json).delivery, 'minimal_complete_user_scenario');
      assert.equal(JSON.parse(mvp.data_json).incomplete_is_mvp, false);
      assert.equal(db.prepare('SELECT count(*) AS count FROM memory_conflicts WHERE status=\'open\'').get().count, 0);
    } finally { db.close(); }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('model lifecycle workflow rejects a pending semantic duplicate', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-model-lifecycle-duplicate-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const sourceId = '70000000-0000-4000-a000-000000000001';
    const candidateId = '70000000-0000-4000-a000-000000000002';
    const seed = `import { DatabaseSync } from 'node:sqlite'; const db = new DatabaseSync(process.argv[1]); db.prepare("INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Pending', 'Pending', 'active', 'owner', 'internal')").run('${sourceId}'); db.prepare("INSERT INTO memory_candidates (id,type,semantic_key,title,content,status,source_id,author,access_level) VALUES (?, 'ai_policy', 'ai.model_routing_policy', 'Pending', 'Pending', 'pending', ?, 'owner', 'internal')").run('${candidateId}', '${sourceId}'); db.close();`;
    execFileSync(process.execPath, ['--input-type=module', '--eval', seed, databasePath]);
    assert.throws(() => applyModelRoutingPolicy(databasePath), /Semantic duplicate or evolution/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('MVP speed workflow rejects a pending semantic duplicate', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-mvp-speed-duplicate-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const sourceId = '71000000-0000-4000-a000-000000000001';
    const candidateId = '71000000-0000-4000-a000-000000000002';
    const seed = `import { DatabaseSync } from 'node:sqlite'; const db = new DatabaseSync(process.argv[1]); db.prepare("INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Pending', 'Pending', 'active', 'owner', 'internal')").run('${sourceId}'); db.prepare("INSERT INTO memory_candidates (id,type,semantic_key,title,content,status,source_id,author,access_level) VALUES (?, 'decision', 'engineering.mvp_speed_principle', 'Pending', 'Pending', 'pending', ?, 'owner', 'internal')").run('${candidateId}', '${sourceId}'); db.close();`;
    execFileSync(process.execPath, ['--input-type=module', '--eval', seed, databasePath]);
    assert.throws(() => applyMvpSpeedPrinciple(databasePath), /Semantic duplicate or evolution/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});
