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
      assert.equal(data.execution.implementation, 'repo_side_cli');
      assert.equal(data.handoff.create_command, 'handoff-create');
      assert.equal(data.handoff.next_command, 'handoff-next');
      assert.equal(data.handoff.atomic_decision_task_link, true);
      assert.equal(data.revision, 3);
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
