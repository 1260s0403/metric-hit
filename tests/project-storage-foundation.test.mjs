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
    assert.deepEqual(first.created, { sources: 2, documents: 1, versions: 1, candidates: 3, audits: 3 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0, audits: 0 });
    const database = new DatabaseSync(databasePath, { readOnly: true });
    try {
      const row = database.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(first.candidateId);
      const data = JSON.parse(row.data_json);
      assert.equal(row.status, 'approved');
      assert.equal(data.root, 'data/projects');
      assert.equal(data.path_traversal_allowed, false);
      assert.equal(data.runtime_connected, false);
      assert.equal(data.migrated_existing_data, false);
      const materialized = database.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(first.materializationCandidateId);
      const materializedData = JSON.parse(materialized.data_json);
      assert.equal(materialized.status, 'approved');
      assert.deepEqual(materializedData.records, { primary: 326, dependency: 4, schema_migrations: 10, total: 340 });
      assert.equal(materializedData.cutover, false);
      assert.equal(materializedData.target_sha256, '69e0ec3841ee43568aa90685c74b30c2f05f0292110f191f36e547cbd20da08d');
      const runtime = database.prepare('SELECT status,data_json FROM memory_candidates WHERE id=?').get(first.runtimeCutoverCandidateId);
      const runtimeData = JSON.parse(runtime.data_json);
      assert.equal(runtime.status, 'approved');
      assert.deepEqual(runtimeData.guarded_replacement, { applied: 1, replacedExisting: 1, cutover: true });
      assert.deepEqual(runtimeData.records, { primary: 328, dependency: 4, schema_migrations: 10, total: 342 });
      assert.equal(runtimeData.commit, '0150db784e6795f9d08e36e0f70f786594247cee');
      assert.equal(runtimeData.source_sha256_at_cutover, '2b0e6b27826d580d355eb2dabd2ce6c7dcec20db65b951d6177aba3635c486bb');
      assert.equal(runtimeData.target_sha256, 'd9cb1d4635b0c917e9c61eca86cdc182e9db42471637711dae62a1f82a49fea6');
      assert.equal(runtimeData.central_database_role, 'control_plane');
      const scopeAudit = database.prepare('SELECT type,data_json FROM audit_log WHERE id=?').get(first.materializationScopeAuditId);
      assert.equal(scopeAudit.type, 'project_scope_metadata_correction');
      assert.equal(JSON.parse(scopeAudit.data_json).corrections[0].newValue, null);
      const sourceScopeAudit = database.prepare('SELECT type,data_json FROM audit_log WHERE id=?').get(first.runtimeCutoverSourceScopeAuditId);
      assert.equal(sourceScopeAudit.type, 'project_scope_assignment');
      assert.equal(JSON.parse(sourceScopeAudit.data_json).project_id, '00000000-0000-4000-a000-000000000101');
      const runtimeScopeAudit = database.prepare('SELECT type,data_json FROM audit_log WHERE id=?').get(first.runtimeCutoverCandidateScopeAuditId);
      assert.equal(runtimeScopeAudit.type, 'project_scope_metadata_correction');
      assert.equal(JSON.parse(runtimeScopeAudit.data_json).corrections[0].newValue, null);
      assert.equal(database.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count, 0);
    } finally {
      database.close();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});
