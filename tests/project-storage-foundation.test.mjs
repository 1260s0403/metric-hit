import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyProjectStorageFoundation } from '../scripts/apply-project-storage-foundation.mjs';

test('project storage decision workflow is exact and idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-project-storage-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const first = applyProjectStorageFoundation(databasePath);
    const second = applyProjectStorageFoundation(databasePath);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const database = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const row = database.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(first.candidateId);
      const data = JSON.parse(row.data_json);
      assert.equal(row.status, 'approved');
      assert.equal(data.root, 'data/projects');
      assert.equal(data.path_traversal_allowed, false);
      assert.equal(data.runtime_connected, false);
      assert.equal(data.migrated_existing_data, false);
      assert.equal(database.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count, 0);
    } finally {
      database.close();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});
