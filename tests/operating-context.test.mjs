import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyOperatingContext } from '../scripts/apply-operating-context.mjs';

test('operating context workflow is exact and idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-operating-context-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const first = applyOperatingContext(databasePath);
    const second = applyOperatingContext(databasePath);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 2 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const db = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const rows = db.prepare(`SELECT semantic_key,status,count(*) AS count FROM memory_candidates WHERE semantic_key IN (?,?) GROUP BY semantic_key,status ORDER BY semantic_key`).all(...first.keys);
      assert.deepEqual(rows.map(row => [row.semantic_key, row.status, Number(row.count)]), [
        ['architecture.operating_core_and_departments', 'approved', 1],
        ['product.management_and_commercial_purpose', 'approved', 1],
      ]);
      assert.equal(db.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count, 0);
    } finally { db.close(); }
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
