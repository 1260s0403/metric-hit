import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyOperatingContext } from '../scripts/apply-operating-context.mjs';
import { applyYadroMetricHitProjectBoundary } from '../scripts/apply-yadro-metrichit-project-boundary.mjs';

test('Yadro–MetricHit boundary explicitly evolves the core decision and is idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-yadro-boundary-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    applyOperatingContext(databasePath);
    const first = applyYadroMetricHitProjectBoundary(databasePath);
    const second = applyYadroMetricHitProjectBoundary(databasePath);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const db = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const row = db.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(first.candidateId);
      assert.equal(row.status, 'approved');
      const data = JSON.parse(row.data_json);
      assert.equal(data.core_product, 'yadro');
      assert.equal(data.first_managed_project, 'MetricHit');
      assert.equal(data.metrichit_role, 'independent_project_managed_by_yadro');
      assert.equal(data.metrichit_is_department, false);
      assert.equal(data.metrichit_is_internal_technical_module, false);
      assert.equal(data.metrichit_is_child_project_in_hierarchy, false);
      assert.deepEqual(data.implementation_excluded, ['project_hierarchy', 'schema_change', 'ui_change', 'product_behavior_change', 'package_rename', 'data_migration']);
    } finally { db.close(); }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});
