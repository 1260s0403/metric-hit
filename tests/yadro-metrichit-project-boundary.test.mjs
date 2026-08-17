import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyOperatingContext } from '../scripts/apply-operating-context.mjs';
import { applyYadroMetricHitProjectBoundary } from '../scripts/apply-yadro-metrichit-project-boundary.mjs';
import { buildCurrentContext } from '../scripts/export-current-context.mjs';

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
      assert.equal(data.internal_core_project, 'Развитие Ядра');
      assert.deepEqual(data.hierarchy, { max_subproject_depth: 1, cross_project_children_allowed: false });
      assert.deepEqual(data.required_scope_for_new, ['task', 'artem_recommendation', 'owner_idea']);
      assert.equal(data.default_project, 'MetricHit');
      assert.equal(data.legacy_records_mass_reassigned, false);
      const context = buildCurrentContext(databasePath, '2026-08-17T00:00:00.000Z');
      assert.match(context, /«Развитие Ядра» — независимый внутренний проект/);
      assert.doesNotMatch(context, /не реализует иерархию/);
    } finally { db.close(); }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});
