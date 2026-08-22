import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyCoreProjectBackupPolicy } from '../scripts/apply-core-project-backup-policy.mjs';

test('core and project backup policy is exact and idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-backup-policy-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const first = applyCoreProjectBackupPolicy(databasePath);
    const second = applyCoreProjectBackupPolicy(databasePath);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const database = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const row = database.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(first.candidateId);
      const data = JSON.parse(row.data_json);
      assert.equal(row.status, 'approved');
      assert.deepEqual(data.scope, ['core', 'all_existing_managed_project_storages']);
      assert.equal(data.sqlite_copy_method, 'online_backup');
      assert.equal(data.raw_live_database_copy_allowed, false);
      assert.equal(data.git_history_scope, 'all_reachable_objects_in_all_refs');
      assert.equal(data.secret_policy_reduced, false);
      assert.equal(data.migrates_data, false);
      assert.equal(database.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count, 0);
    } finally {
      database.close();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});
