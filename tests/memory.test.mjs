import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { checkDatabase, requiredTables } from '../scripts/check-memory.mjs';
import { initializeDatabase } from '../scripts/init-memory.mjs';
import { importChatSummaries } from '../scripts/import-chat-summaries.mjs';
import { applyInitialMemoryDecision } from '../scripts/apply-initial-memory-decision.mjs';
import { applyModelRoutingPolicy } from '../scripts/apply-model-routing-policy.mjs';
import { applyServerPrimaryWorkspace } from '../scripts/apply-server-primary-workspace.mjs';
import { applyProductPositioningAndEditorialDirectness } from '../scripts/apply-product-positioning-and-editorial-directness.mjs';
import { applyMetricHitPricing } from '../scripts/apply-metrichit-pricing.mjs';
import { applyPublicPfPositiveFraming } from '../scripts/apply-public-pf-positive-framing.mjs';
import { applyEditorialPublicationPolicyAndTimewebDraft } from '../scripts/apply-editorial-publication-policy-and-timeweb-draft.mjs';
import { applySostavNakrutkaPfPublication } from '../scripts/apply-sostav-nakrutka-pf-publication.mjs';
import { applyPublicationLinksSostavOborot } from '../scripts/apply-publication-links-sostav-oborot-2026-08-29.mjs';
import { applyTenchatPublicationAndIndexationContinuity } from '../scripts/apply-tenchat-publication-and-indexation-continuity-2026-08-30.mjs';
import { readMemory } from '../scripts/memory-cli.mjs';
import { exportCurrentContext } from '../scripts/export-current-context.mjs';

function temporaryDatabase(t) {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-memory-'));
  return {
    databasePath: join(directory, 'memory.db'),
    remove: () => rmSync(directory, { recursive: true, force: true }),
  };
}

function seedSource(database) {
  database.prepare(`
    INSERT INTO sources (id, type, title, content, author)
    VALUES (?, 'manual', 'Test source', 'Non-client test fixture', 'test')
  `).run('00000000-0000-4000-8000-000000000001');
}

test('initialization is repeatable and creates the required schema', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  initializeDatabase(databasePath);
  initializeDatabase(databasePath);

  const result = checkDatabase(databasePath);
  assert.deepEqual(result.tables, [...requiredTables].sort());
  assert.equal(result.migrationCount, 12);
  assert.equal(result.integrity, 'ok');
});

test('candidate and memory item statuses are constrained', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  assert.throws(() => database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, status, source_id, author)
    VALUES (?, 'fact', 'test.key', 'Candidate', 'Value', 'invalid', ?, 'test')
  `).run('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001'));

  assert.throws(() => database.prepare(`
    INSERT INTO memory_items
      (id, type, semantic_key, title, content, status, source_id, author)
    VALUES (?, 'fact', 'test.key', 'Item', 'Value', 'invalid', ?, 'test')
  `).run('00000000-0000-4000-8000-000000000003', '00000000-0000-4000-8000-000000000001'));
});

test('candidate cannot be inserted directly as approved', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  assert.throws(() => database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, status, source_id, author, reviewed_by, reviewed_at)
    VALUES (?, 'fact', 'approval.direct', 'Candidate', 'Value', 'approved', ?, 'author', 'owner', ?)
  `).run(
    '00000000-0000-4000-8000-000000000007',
    '00000000-0000-4000-8000-000000000001',
    '2026-01-01T00:00:00.000Z',
  ), /pending status/);
});

test('candidate approval requires non-empty reviewer and review date', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const candidateId = '00000000-0000-4000-8000-000000000008';
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'approval.required', 'Candidate', 'Value', ?, 'author')
  `).run(candidateId, '00000000-0000-4000-8000-000000000001');

  const approve = database.prepare(`
    UPDATE memory_candidates
    SET status = 'approved', reviewed_by = ?, reviewed_at = ?, version = version + 1
    WHERE id = ?
  `);
  assert.throws(() => approve.run(null, '2026-01-01T00:00:00.000Z', candidateId), /reviewed_by/);
  assert.throws(() => approve.run('owner', null, candidateId), /reviewed_at/);
  assert.throws(() => approve.run('  ', '  ', candidateId), /reviewed_by and reviewed_at/);
  assert.equal(database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(candidateId).status, 'pending');
});

test('candidate rejection requires non-empty reviewer and review date', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const candidateId = '00000000-0000-4000-8000-000000000011';
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'rejection.required', 'Candidate', 'Value', ?, 'author')
  `).run(candidateId, '00000000-0000-4000-8000-000000000001');

  const reject = database.prepare(`
    UPDATE memory_candidates
    SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, version = version + 1
    WHERE id = ?
  `);
  assert.throws(() => reject.run(null, '2026-01-01T00:00:00.000Z', candidateId), /reviewed_by and reviewed_at/);
  assert.throws(() => reject.run('owner', null, candidateId), /reviewed_by and reviewed_at/);
  assert.throws(() => reject.run('  ', '  ', candidateId), /reviewed_by and reviewed_at/);
  assert.equal(database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(candidateId).status, 'pending');

  reject.run('owner', '2026-01-01T00:00:00.000Z', candidateId);
  const rejected = database.prepare(
    'SELECT status, reviewed_by, reviewed_at FROM memory_candidates WHERE id = ?',
  ).get(candidateId);
  assert.equal(rejected.status, 'rejected');
  assert.equal(rejected.reviewed_by, 'owner');
  assert.equal(rejected.reviewed_at, '2026-01-01T00:00:00.000Z');
});

test('verified memory changes are audited and deletion is blocked', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const itemId = '00000000-0000-4000-8000-000000000004';
  database.prepare(`
    INSERT INTO memory_items
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'company.rule', 'Rule', 'First value', ?, 'owner')
  `).run(itemId, '00000000-0000-4000-8000-000000000001');
  database.prepare(`
    UPDATE memory_items
    SET content = 'Second value', version = 2,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = ?
  `).run(itemId);

  const audit = database.prepare(
    'SELECT action FROM audit_log WHERE entity_id = ? ORDER BY rowid',
  ).all(itemId);
  assert.deepEqual(audit.map(({ action }) => action), ['create', 'update']);
  const snapshot = JSON.parse(database.prepare(
    "SELECT data_json FROM audit_log WHERE entity_id = ? AND action = 'update'",
  ).get(itemId).data_json);
  assert.equal(snapshot.old.content, 'First value');
  assert.equal(snapshot.new.content, 'Second value');
  assert.equal(snapshot.old.title, 'Rule');
  assert.equal(snapshot.new.semantic_key, 'company.rule');
  assert.equal(snapshot.new.source_id, '00000000-0000-4000-8000-000000000001');
  assert.throws(() => database.prepare('DELETE FROM memory_items WHERE id = ?').run(itemId));
  assert.throws(() => database.prepare('UPDATE audit_log SET title = title').run());
});

test('approval of contradictory candidate creates conflict without changing memory', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const itemId = '00000000-0000-4000-8000-000000000005';
  const candidateId = '00000000-0000-4000-8000-000000000006';
  database.prepare(`
    INSERT INTO memory_items
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'company.value', 'Current value', 'Original', ?, 'owner')
  `).run(itemId, sourceId);
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, target_memory_item_id, author)
    VALUES (?, 'fact', 'company.value', 'Proposed value', 'Contradiction', ?, ?, 'author')
  `).run(candidateId, sourceId, itemId);
  database.prepare(`
    UPDATE memory_candidates
    SET status = 'approved', reviewed_by = 'owner',
        reviewed_at = '2026-01-01T00:00:00.000Z', version = 2,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = ?
  `).run(candidateId);

  assert.equal(database.prepare('SELECT content FROM memory_items WHERE id = ?').get(itemId).content, 'Original');
  const conflict = database.prepare(
    'SELECT status, existing_memory_item_id FROM memory_conflicts WHERE candidate_id = ?',
  ).get(candidateId);
  assert.equal(conflict.status, 'open');
  assert.equal(conflict.existing_memory_item_id, itemId);
});

test('service-only update of an approved candidate preserves one existing conflict', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const itemId = '00000000-0000-4000-8000-000000000009';
  const candidateId = '00000000-0000-4000-8000-000000000010';
  database.prepare(`
    INSERT INTO memory_items
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'company.reapproval', 'Current value', 'Original', ?, 'owner')
  `).run(itemId, sourceId);
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, target_memory_item_id, author)
    VALUES (?, 'fact', 'company.reapproval', 'Proposed value', 'First contradiction', ?, ?, 'author')
  `).run(candidateId, sourceId, itemId);

  database.prepare(`
    UPDATE memory_candidates
    SET status = 'approved', reviewed_by = 'owner', reviewed_at = ?,
        version = version + 1, updated_at = ?
    WHERE id = ?
  `).run('2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z', candidateId);
  const firstConflict = database.prepare(`
    SELECT id, version FROM memory_conflicts
    WHERE candidate_id = ? AND existing_memory_item_id = ?
  `).get(candidateId, itemId);

  database.prepare(`
    UPDATE memory_candidates
    SET version = version + 1,
        updated_at = '2026-01-02T00:00:00.000Z'
    WHERE id = ?
  `).run(candidateId);

  const conflicts = database.prepare(`
    SELECT id, status, version
    FROM memory_conflicts
    WHERE candidate_id = ? AND existing_memory_item_id = ?
  `).all(candidateId, itemId);
  assert.equal(conflicts.length, 1);
  assert.equal(conflicts[0].id, firstConflict.id);
  assert.equal(conflicts[0].status, 'open');
  assert.equal(conflicts[0].version, firstConflict.version);
  assert.equal(database.prepare('SELECT content FROM memory_items WHERE id = ?').get(itemId).content, 'Original');
});

test('terminal candidate states enforce review metadata and cannot transition', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const approvedId = '00000000-0000-4000-8000-000000000015';
  const rejectedId = '00000000-0000-4000-8000-000000000016';
  const insertPending = database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', ?, 'Candidate', 'Value', ?, 'author')
  `);
  insertPending.run(approvedId, 'invariant.approved', sourceId);
  insertPending.run(rejectedId, 'invariant.rejected', sourceId);

  const review = database.prepare(`
    UPDATE memory_candidates
    SET status = ?, reviewed_by = 'owner', reviewed_at = '2026-01-01T00:00:00.000Z',
        version = version + 1
    WHERE id = ?
  `);
  review.run('approved', approvedId);
  review.run('rejected', rejectedId);

  assert.throws(
    () => database.prepare('UPDATE memory_candidates SET reviewed_by = NULL WHERE id = ?').run(approvedId),
    /terminal memory_candidates are immutable/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET reviewed_by = '   ' WHERE id = ?").run(approvedId),
    /terminal memory_candidates are immutable/,
  );
  assert.throws(
    () => database.prepare('UPDATE memory_candidates SET reviewed_at = NULL WHERE id = ?').run(rejectedId),
    /terminal memory_candidates are immutable/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET status = 'rejected' WHERE id = ?").run(approvedId),
    /terminal memory_candidates are immutable|invalid memory_candidates status transition/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET status = 'approved' WHERE id = ?").run(rejectedId),
    /terminal memory_candidates are immutable|invalid memory_candidates status transition/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET status = 'pending' WHERE id = ?").run(approvedId),
    /terminal memory_candidates are immutable|invalid memory_candidates status transition/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET status = 'pending' WHERE id = ?").run(rejectedId),
    /terminal memory_candidates are immutable|invalid memory_candidates status transition/,
  );

  database.prepare('UPDATE memory_candidates SET version = version + 1 WHERE id = ?').run(approvedId);
  assert.equal(
    database.prepare('SELECT version FROM memory_candidates WHERE id = ?').get(approvedId).version,
    3,
  );
});

test('approved and rejected candidates are immutable except service fields', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);
  database.prepare(`
    INSERT INTO sources (id, type, title, content, author)
    VALUES (?, 'manual', 'Second test source', 'Non-client test fixture', 'test')
  `).run('00000000-0000-4000-8000-000000000020');

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const approvedId = '00000000-0000-4000-8000-000000000021';
  const rejectedId = '00000000-0000-4000-8000-000000000022';
  const insertPending = database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, data_json, source_id, author, review_note)
    VALUES (?, 'fact', ?, 'Candidate', 'Original', '{"value":1}', ?, 'author', 'Original note')
  `);
  insertPending.run(approvedId, 'immutable.approved', sourceId);
  insertPending.run(rejectedId, 'immutable.rejected', sourceId);
  const review = database.prepare(`
    UPDATE memory_candidates
    SET status = ?, reviewed_by = 'owner', reviewed_at = '2026-01-01T00:00:00.000Z',
        version = version + 1
    WHERE id = ?
  `);
  review.run('approved', approvedId);
  review.run('rejected', rejectedId);

  const immutableError = /terminal memory_candidates are immutable/;
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET content = 'Changed' WHERE id = ?").run(approvedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET data_json = '{\"value\":2}' WHERE id = ?").run(rejectedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET reviewed_by = 'other' WHERE id = ?").run(approvedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET reviewed_at = '2026-02-01T00:00:00.000Z' WHERE id = ?").run(rejectedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare('UPDATE memory_candidates SET source_id = ? WHERE id = ?')
      .run('00000000-0000-4000-8000-000000000020', approvedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET author = 'other' WHERE id = ?").run(rejectedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET title = 'Changed' WHERE id = ?").run(approvedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_candidates SET review_note = 'Changed' WHERE id = ?").run(rejectedId),
    immutableError,
  );
  assert.throws(
    () => database.prepare('DELETE FROM memory_candidates WHERE id = ?').run(approvedId),
    /terminal memory_candidates cannot be deleted/,
  );

  database.prepare(`
    UPDATE memory_candidates
    SET updated_at = '2026-02-01T00:00:00.000Z', version = version + 1
    WHERE id = ?
  `).run(approvedId);
  const approved = database.prepare(`
    SELECT content, data_json, reviewed_by, reviewed_at, author, version, updated_at
    FROM memory_candidates WHERE id = ?
  `).get(approvedId);
  assert.equal(approved.content, 'Original');
  assert.equal(approved.data_json, '{"value":1}');
  assert.equal(approved.reviewed_by, 'owner');
  assert.equal(approved.reviewed_at, '2026-01-01T00:00:00.000Z');
  assert.equal(approved.author, 'author');
  assert.equal(approved.version, 3);
  assert.equal(approved.updated_at, '2026-02-01T00:00:00.000Z');
});

test('new pending candidates and standard review transitions remain allowed', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const pendingId = '00000000-0000-4000-8000-000000000017';
  const approvedId = '00000000-0000-4000-8000-000000000018';
  const rejectedId = '00000000-0000-4000-8000-000000000019';
  const insertPending = database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', ?, 'Candidate', 'Value', ?, 'author')
  `);
  insertPending.run(pendingId, 'standard.pending', sourceId);
  insertPending.run(approvedId, 'standard.approved', sourceId);
  insertPending.run(rejectedId, 'standard.rejected', sourceId);
  assert.equal(database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(pendingId).status, 'pending');

  const review = database.prepare(`
    UPDATE memory_candidates
    SET status = ?, reviewed_by = 'owner', reviewed_at = '2026-01-01T00:00:00.000Z',
        version = version + 1
    WHERE id = ?
  `);
  review.run('approved', approvedId);
  review.run('rejected', rejectedId);
  assert.equal(database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(approvedId).status, 'approved');
  assert.equal(database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(rejectedId).status, 'rejected');
});

test('document version history is append-only while new versions are allowed', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');

  const documentId = '00000000-0000-4000-8000-000000000012';
  const firstVersionId = '00000000-0000-4000-8000-000000000013';
  const secondVersionId = '00000000-0000-4000-8000-000000000014';
  database.prepare(`
    INSERT INTO documents (id, type, title, content, author)
    VALUES (?, 'policy', 'Test document', 'Current content', 'owner')
  `).run(documentId);
  const insertVersion = database.prepare(`
    INSERT INTO document_versions
      (id, document_id, type, title, content, author, version)
    VALUES (?, ?, 'policy', ?, ?, 'owner', ?)
  `);
  insertVersion.run(firstVersionId, documentId, 'Test document v1', 'Version one', 1);

  assert.throws(
    () => database.prepare('UPDATE document_versions SET content = ? WHERE id = ?')
      .run('Rewritten', firstVersionId),
    /append-only; add a new version instead/,
  );
  assert.throws(
    () => database.prepare('DELETE FROM document_versions WHERE id = ?').run(firstVersionId),
    /append-only; versions cannot be deleted/,
  );

  insertVersion.run(secondVersionId, documentId, 'Test document v2', 'Version two', 2);
  const versions = database.prepare(`
    SELECT version, content FROM document_versions
    WHERE document_id = ? ORDER BY version
  `).all(documentId);
  assert.equal(versions.length, 2);
  assert.equal(versions[0].content, 'Version one');
  assert.equal(versions[1].content, 'Version two');
});

test('inactive target cannot bypass conflict with active semantic-key item', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const archivedId = '00000000-0000-4000-8000-000000000023';
  const activeId = '00000000-0000-4000-8000-000000000024';
  const candidateId = '00000000-0000-4000-8000-000000000025';
  const insertItem = database.prepare(`
    INSERT INTO memory_items
      (id, type, semantic_key, title, content, status, source_id, author)
    VALUES (?, 'fact', 'conflict.bypass', ?, ?, ?, ?, 'owner')
  `);
  insertItem.run(archivedId, 'Archived', 'Old', 'archived', sourceId);
  insertItem.run(activeId, 'Active', 'Current', 'active', sourceId);
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, target_memory_item_id, author)
    VALUES (?, 'fact', 'conflict.bypass', 'Candidate', 'Contradiction', ?, ?, 'author')
  `).run(candidateId, sourceId, archivedId);
  database.prepare(`
    UPDATE memory_candidates
    SET status = 'approved', reviewed_by = 'owner',
        reviewed_at = '2026-01-01T00:00:00.000Z', version = version + 1
    WHERE id = ?
  `).run(candidateId);

  const conflicts = database.prepare(
    'SELECT existing_memory_item_id, status FROM memory_conflicts WHERE candidate_id = ?',
  ).all(candidateId);
  assert.equal(conflicts.length, 1);
  assert.equal(conflicts[0].existing_memory_item_id, activeId);
  assert.equal(conflicts[0].status, 'open');
  assert.equal(database.prepare('SELECT content FROM memory_items WHERE id = ?').get(activeId).content, 'Current');
});

test('read-only check rejects a database missing a protective trigger', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  database.exec('DROP TRIGGER memory_candidates_protect_terminal_update');
  database.close();
  t.after(remove);

  assert.throws(() => checkDatabase(databasePath), /Missing protective triggers/);
});

test('conflict history cannot be deleted or closed without a resolution', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const itemId = '00000000-0000-4000-8000-000000000026';
  const candidateId = '00000000-0000-4000-8000-000000000027';
  database.prepare(`
    INSERT INTO memory_items (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'conflict.history', 'Current', 'Original', ?, 'owner')
  `).run(itemId, sourceId);
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, target_memory_item_id, author)
    VALUES (?, 'fact', 'conflict.history', 'Candidate', 'Changed', ?, ?, 'author')
  `).run(candidateId, sourceId, itemId);
  database.prepare(`
    UPDATE memory_candidates
    SET status = 'approved', reviewed_by = 'owner',
        reviewed_at = '2026-01-01T00:00:00.000Z', version = version + 1
    WHERE id = ?
  `).run(candidateId);
  const conflictId = database.prepare(
    'SELECT id FROM memory_conflicts WHERE candidate_id = ?',
  ).get(candidateId).id;

  assert.throws(
    () => database.prepare('DELETE FROM memory_conflicts WHERE id = ?').run(conflictId),
    /cannot be deleted/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_conflicts SET status = 'resolved' WHERE id = ?").run(conflictId),
    /closing requires a non-empty resolution/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_conflicts SET status = 'dismissed', resolution = '  ' WHERE id = ?").run(conflictId),
    /closing requires a non-empty resolution/,
  );
  database.prepare(`
    UPDATE memory_conflicts
    SET status = 'resolved', resolution = 'Owner decision', version = version + 1
    WHERE id = ?
  `).run(conflictId);
  assert.throws(
    () => database.prepare("UPDATE memory_conflicts SET status = 'open' WHERE id = ?").run(conflictId),
    /closed memory_conflicts decisions are immutable|invalid conflict state/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_conflicts SET resolution = 'Rewritten' WHERE id = ?").run(conflictId),
    /closed memory_conflicts decisions are immutable/,
  );
  assert.throws(
    () => database.prepare("UPDATE memory_conflicts SET content = 'Rewritten' WHERE id = ?").run(conflictId),
    /history and attribution are immutable/,
  );
});

test('current context excludes open and dismissed conflict candidates', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => { database.close(); remove(); });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);
  const sourceId = '00000000-0000-4000-8000-000000000001';
  const itemId = '00000000-0000-4000-8000-000000000034';
  const candidateId = '00000000-0000-4000-8000-000000000035';
  database.prepare(`
    INSERT INTO memory_items (id,type,semantic_key,title,content,source_id,author)
    VALUES (?,'product_fact','context.conflict','Current','Current value',?,'owner')
  `).run(itemId, sourceId);
  database.prepare(`
    INSERT INTO memory_candidates (id,type,semantic_key,title,content,source_id,author)
    VALUES (?,'product_fact','context.conflict','Candidate hidden while conflicted','Candidate value',?,'owner')
  `).run(candidateId, sourceId);
  database.prepare(`
    UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?,version=version+1 WHERE id=?
  `).run('2026-08-16T00:00:00.000Z', candidateId);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  exportCurrentContext(databasePath, outputPath, '2026-08-16T00:00:00.000Z');
  assert.doesNotMatch(readFileSync(outputPath, 'utf8'), /Candidate hidden while conflicted/);
  const conflictId = database.prepare('SELECT id FROM memory_conflicts WHERE candidate_id=?').get(candidateId).id;
  database.prepare(`
    UPDATE memory_conflicts SET status='dismissed',resolution='Keep current',version=version+1 WHERE id=?
  `).run(conflictId);
  exportCurrentContext(databasePath, outputPath, '2026-08-16T00:00:00.000Z');
  assert.doesNotMatch(readFileSync(outputPath, 'utf8'), /Candidate hidden while conflicted/);
});

test('read-only check rejects a same-name no-op protective trigger', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  database.exec(`
    DROP TRIGGER memory_candidates_protect_terminal_update;
    CREATE TRIGGER memory_candidates_protect_terminal_update
    BEFORE UPDATE ON memory_candidates BEGIN SELECT 1; END;
  `);
  database.close();
  t.after(remove);

  assert.throws(() => checkDatabase(databasePath), /Altered protective triggers/);
});

test('conflict inserts enforce resolution and immutable attribution', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  t.after(() => {
    database.close();
    remove();
  });
  database.exec('PRAGMA foreign_keys = ON');
  seedSource(database);

  const sourceId = '00000000-0000-4000-8000-000000000001';
  const itemId = '00000000-0000-4000-8000-000000000028';
  const candidateId = '00000000-0000-4000-8000-000000000029';
  database.prepare(`
    INSERT INTO memory_items (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'conflict.insert', 'Current', 'Original', ?, 'owner')
  `).run(itemId, sourceId);
  database.prepare(`
    INSERT INTO memory_candidates
      (id, type, semantic_key, title, content, source_id, author)
    VALUES (?, 'fact', 'conflict.insert', 'Candidate', 'Changed', ?, 'author')
  `).run(candidateId, sourceId);
  const insertConflict = database.prepare(`
    INSERT INTO memory_conflicts
      (id, type, title, content, status, resolution, candidate_id,
       existing_memory_item_id, source_id, author)
    VALUES (?, 'manual_conflict', 'Conflict', 'Changed', ?, ?, ?, ?, ?, 'owner')
  `);
  assert.throws(
    () => insertConflict.run(
      '00000000-0000-4000-8000-000000000030', 'resolved', null,
      candidateId, itemId, sourceId,
    ),
    /closed conflicts require a resolution/,
  );
  assert.throws(
    () => insertConflict.run(
      '00000000-0000-4000-8000-000000000031', 'open', 'Stale',
      candidateId, itemId, sourceId,
    ),
    /open conflicts must not have one/,
  );
});

test('read-only check preserves string-literal case in trigger fingerprint', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  const original = database.prepare(
    "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'memory_conflicts_validate_insert'",
  ).get().sql;
  database.exec('DROP TRIGGER memory_conflicts_validate_insert');
  database.exec(original.replace("'resolved', 'dismissed'", "'RESOLVED', 'DISMISSED'"));
  database.close();
  t.after(remove);

  assert.throws(() => checkDatabase(databasePath), /Altered protective triggers/);
});

test('read-only check rejects unexpected triggers', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  initializeDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  database.exec(`
    CREATE TRIGGER unexpected_memory_mutation
    AFTER UPDATE OF status ON memory_candidates
    WHEN NEW.status = 'approved' AND NEW.target_memory_item_id IS NOT NULL
    BEGIN
      UPDATE memory_items
      SET title = 'Unexpected mutation', version = version + 1
      WHERE id = NEW.target_memory_item_id;
    END;
  `);
  database.close();
  t.after(remove);

  assert.throws(() => checkDatabase(databasePath), /Unexpected triggers/);
});

test('chat summary import is repeatable and keeps candidates pending', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);

  const first = importChatSummaries(databasePath);
  const second = importChatSummaries(databasePath);
  assert.deepEqual(first.created, { sources: 3, documents: 3, versions: 3, candidates: 25 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
  assert.deepEqual(second.totals, { sources: 3, documents: 5, versions: 3, candidates: 25 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const statuses = database.prepare(
    'SELECT status, count(*) AS count FROM memory_candidates GROUP BY status',
  ).all();
  const duplicates = database.prepare(`
    SELECT semantic_key FROM memory_candidates
    GROUP BY semantic_key HAVING count(*) > 1
  `).all();
  database.close();
  assert.deepEqual(statuses.map(({ status, count }) => ({ status, count })), [{ status: 'pending', count: 25 }]);
  assert.deepEqual(duplicates, []);
});

test('initial owner decision is repeatable and preserves terminal records', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  importChatSummaries(databasePath);

  const first = applyInitialMemoryDecision(databasePath);
  const second = applyInitialMemoryDecision(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1, tasks: 1 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0, tasks: 0 });
  assert.deepEqual(second.counts, { approved: 24, rejected: 2 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const analytics = database.prepare(
    "SELECT status, review_note FROM memory_candidates WHERE semantic_key = 'analytics.utm_registration_click'",
  ).get();
  const oldAvito = database.prepare(
    "SELECT status FROM memory_candidates WHERE semantic_key = 'publication.avito_saint_petersburg'",
  ).get();
  const correctedAvito = database.prepare(
    "SELECT status, content, data_json FROM memory_candidates WHERE semantic_key = 'publication.avito_active_ads_2026_08_13'",
  ).get();
  const task = database.prepare('SELECT status, content, data_json FROM tasks').get();
  const terminalVersions = database.prepare(`
    SELECT min(version) AS minimum, max(version) AS maximum
    FROM memory_candidates WHERE status IN ('approved', 'rejected')
  `).get();
  database.close();

  assert.equal(analytics.status, 'rejected');
  assert.match(analytics.review_note, /Функциональность не реализована/);
  assert.equal(oldAvito.status, 'rejected');
  assert.equal(correctedAvito.status, 'approved');
  assert.deepEqual(JSON.parse(correctedAvito.data_json).cities, [
    'Новосибирск', 'Пермь', 'Екатеринбург', 'Санкт-Петербург', 'Москва',
  ]);
  assert.equal(task.status, 'pending');
  assert.match(task.content, /не изменяя mtrhit\.ru/);
  assert.equal(JSON.parse(task.data_json).due_at, 'unknown');
  assert.equal(terminalVersions.minimum, 2);
  assert.equal(terminalVersions.maximum, 2);
});

test('model routing decision is repeatable and creates an approved policy', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  initializeDatabase(databasePath);

  const first = applyModelRoutingPolicy(databasePath);
  const second = applyModelRoutingPolicy(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const policy = database.prepare(`
    SELECT status, reviewed_by, reviewed_at, data_json
    FROM memory_candidates WHERE semantic_key = 'ai.model_routing_policy'
  `).get();
  database.close();
  assert.equal(policy.status, 'approved');
  assert.equal(policy.reviewed_by, 'owner');
  assert.equal(policy.reviewed_at, '2026-08-26T00:00:00.000Z');
  assert.equal(JSON.parse(policy.data_json).default_model, 'GPT-5.6 Terra');
  assert.deepEqual(JSON.parse(policy.data_json).spark_for, [
    'isolated_ui_fixes', 'css', 'interface_copy', 'narrow_fixes', 'documentation', 'short_test_cycles',
  ]);
  assert.equal(JSON.parse(policy.data_json).fast_path_model, 'fastest_available_compatible_approved');
  assert.equal(JSON.parse(policy.data_json).fast_path_owner_confirmation_required, false);
  assert.equal(JSON.parse(policy.data_json).fast_path_unavailable_blocks, false);
  assert.equal(JSON.parse(policy.data_json).owner_visible_strategy_model_changes_automatically, false);
  assert.equal(JSON.parse(policy.data_json).reclassify_before_each_new_task, true);
  assert.equal(JSON.parse(policy.data_json).special_model_approval_carries_to_next_task, false);
  assert.equal(JSON.parse(policy.data_json).engineering_task_thread_must_verify_actual_model_on_start, true);
  assert.equal(JSON.parse(policy.data_json).special_model_mismatch_blocks_critical_actions, true);
  assert.equal(JSON.parse(policy.data_json).special_model_mismatch_action, 'pause_and_request_owner_model_switch');
  assert.equal(JSON.parse(policy.data_json).after_special_model_switch, 'continue_current_state_without_rollback_new_thread_or_restart');
});

test('server primary workspace decision is repeatable and records approved context', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  initializeDatabase(databasePath);
  const first = applyServerPrimaryWorkspace(databasePath);
  const second = applyServerPrimaryWorkspace(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 2 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
  const database = new DatabaseSync(databasePath, { readOnly: true });
  const server = database.prepare("SELECT status, data_json FROM memory_candidates WHERE semantic_key='infrastructure.server_context'").get();
  const migration = database.prepare("SELECT status, data_json FROM memory_candidates WHERE semantic_key='migration.server_primary_workspace'").get();
  database.close();
  assert.equal(server.status, 'approved');
  assert.equal(JSON.parse(server.data_json).hostname, 'SERVER');
  assert.equal(JSON.parse(server.data_json).python, '3.13.14');
  assert.equal(migration.status, 'approved');
  assert.equal(JSON.parse(migration.data_json).migration_status, 'authorized_not_started');
  assert.equal(JSON.parse(migration.data_json).migration_completed, false);
});

test('MetricHit pricing evolution is repeatable and supersedes the exported tariff grid', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  t.after(remove);
  importChatSummaries(databasePath);
  applyInitialMemoryDecision(databasePath);

  const first = applyMetricHitPricing(databasePath);
  const second = applyMetricHitPricing(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const revisions = database.prepare(`
    SELECT content, data_json, status FROM memory_candidates
    WHERE semantic_key = 'pricing.current_tiers'
    ORDER BY coalesce(json_extract(data_json, '$.revision'), 0)
  `).all();
  database.close();
  assert.equal(revisions.length, 2);
  assert.equal(revisions[1].status, 'approved');
  assert.deepEqual(JSON.parse(revisions[1].data_json).tiers, [
    [1000, 0.5], [10000, 0.4], [50000, 0.3],
    [100000, 0.25], [150000, 0.2], [200000, 0.15],
  ]);

  const exported = exportCurrentContext(databasePath, outputPath, '2026-08-29T09:00:00.000Z').content;
  assert.match(exported, /от 1 000 ₽ — 0,50 ₽/);
  assert.match(exported, /от 200 000 ₽ — 0,15 ₽/);
  assert.doesNotMatch(exported, /от 1 000 ₽ — 1,50 ₽/);
});

test('product positioning and editorial directness decision is repeatable and supersedes conflicting rules', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  importChatSummaries(databasePath);
  applyInitialMemoryDecision(databasePath);

  const first = applyProductPositioningAndEditorialDirectness(databasePath);
  const second = applyProductPositioningAndEditorialDirectness(databasePath);
  assert.deepEqual(first.created, { sources: 3, documents: 2, versions: 2, decisions: 2, candidates: 4, conflictsResolved: 0 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, decisions: 0, candidates: 0, conflictsResolved: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const positioning = database.prepare(`
    SELECT status, reviewed_by, reviewed_at, content
    FROM memory_candidates WHERE semantic_key = 'product.positioning'
  `).get();
  const policy = database.prepare(`
    SELECT status, reviewed_by, reviewed_at, data_json
    FROM memory_candidates WHERE semantic_key = 'content.editorial_directness_policy'
  `).get();
  const editorialScope = database.prepare(`
    SELECT status, reviewed_by, reviewed_at, content
    FROM memory_candidates WHERE semantic_key = 'content.editorial_search_result_scope'
  `).get();
  database.close();
  assert.equal(positioning.status, 'approved');
  assert.equal(positioning.reviewed_by, 'owner');
  assert.equal(positioning.reviewed_at, '2026-08-14T00:00:00.000Z');
  assert.match(positioning.content, /накрутки и улучшения поведенческих факторов/);
  assert.equal(policy.status, 'approved');
  assert.deepEqual(JSON.parse(policy.data_json).supersedes_editorial_rules, [
    'editorial.no_guarantees', 'editorial.no_fabricated_metrics', 'editorial.no_antifraud_details',
  ]);
  assert.equal(editorialScope.status, 'approved');
  assert.equal(editorialScope.reviewed_by, 'owner');
  assert.equal(editorialScope.reviewed_at, '2026-08-29T00:00:00.000Z');
  assert.match(editorialScope.content, /фокусируются на поисковой выдаче/);
  assert.doesNotMatch(readMemory('rules', '', databasePath), /Не давать недоказуемых гарантий/);
  assert.match(readMemory('decisions', '', databasePath), /Прямая редакционная политика MetricHit/);
});

test('public PF positive framing rule is repeatable and preserves internal product facts', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  importChatSummaries(databasePath);
  applyInitialMemoryDecision(databasePath);
  applyProductPositioningAndEditorialDirectness(databasePath);

  const first = applyPublicPfPositiveFraming(databasePath);
  const second = applyPublicPfPositiveFraming(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const rule = database.prepare(`SELECT status, reviewed_by, reviewed_at, content, data_json FROM memory_candidates WHERE semantic_key='content.public_pf_positive_framing'`).get();
  const positioning = database.prepare(`SELECT content FROM memory_candidates WHERE semantic_key='product.positioning'`).get();
  database.close();
  assert.equal(rule.status, 'approved');
  assert.equal(rule.reviewed_by, 'owner');
  assert.equal(rule.reviewed_at, '2026-08-29T00:00:00.000Z');
  assert.match(rule.content, /не поднимать темы рисков/);
  assert.deepEqual(JSON.parse(rule.data_json).required_positive_focus, ['query_selection', 'landing_page_preparation', 'region', 'daily_limits', 'budget', 'completed_volume_control', 'dynamics_evaluation', 'campaign_scaling']);
  assert.match(positioning.content, /не является гарантией роста позиций/);
  assert.match(readMemory('rules', '', databasePath), /Позитивная подача ПФ/);
});

test('editorial article policy and Timeweb draft are repeatable approved records', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  t.after(remove);
  initializeDatabase(databasePath);

  const first = applyEditorialPublicationPolicyAndTimewebDraft(databasePath);
  const second = applyEditorialPublicationPolicyAndTimewebDraft(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 4 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const policy = database.prepare("SELECT status, content, data_json FROM memory_candidates WHERE semantic_key='content.editorial_article_preparation_policy'").get();
  const draft = database.prepare("SELECT status, content, data_json FROM memory_candidates WHERE semantic_key='publication.timeweb_cloud_draft_2026_08_29'").get();
  const registry = database.prepare("SELECT status, content, data_json FROM memory_candidates WHERE semantic_key='editorial.registry_current_state'").get();
  const contour = database.prepare("SELECT status, content, data_json FROM memory_candidates WHERE semantic_key='editorial.metrichit_contour_and_research_mvp' ORDER BY coalesce(json_extract(data_json, '$.revision'), 0) DESC").get();
  database.close();
  assert.equal(policy.status, 'approved');
  assert.match(policy.content, /не менее 9 000 знаков/);
  assert.deepEqual(JSON.parse(policy.data_json).landing_link_distribution, ['beginning', 'body_1', 'body_2', 'final_cta']);
  assert.equal(draft.status, 'approved');
  assert.match(draft.content, /draft\/unpublished/);
  assert.deepEqual(JSON.parse(draft.data_json), {
    channel: 'articles', platform: 'Timeweb Cloud', publication_status: 'draft', public_url: null,
    final_article_path: 'work/articles/drafts/2026-08-29-timeweb-cloud-pf-service-selection.md',
    evidence: { path: 'knowledge/decisions/editorial-publication-policy-and-timeweb-draft-2026-08-29.md' },
  });
  assert.equal(registry.status, 'approved');
  assert.match(registry.content, /зарегистрирован один article-материал/);
  assert.deepEqual(JSON.parse(registry.data_json), { articles_materials: 1, articles_drafts: 1, articles_publications: 0, articles_results: 0, evidence: { path: 'knowledge/decisions/editorial-publication-policy-and-timeweb-draft-2026-08-29.md' } });
  assert.equal(contour.status, 'approved');
  assert.match(contour.content, /один article-материал для Timeweb Cloud со статусом draft/);
  assert.deepEqual(JSON.parse(contour.data_json).content_registry, { articles_materials: 1, articles_drafts: 1, articles_publications: 0, articles_results: 0 });
  const exported = exportCurrentContext(databasePath, outputPath, '2026-08-29T16:00:00.000Z').content;
  assert.match(exported, /Правила подготовки статей MetricHit/);
  assert.match(exported, /Черновик Timeweb Cloud/);
  assert.match(exported, /публичный URL отсутствует/);
  assert.match(exported, /один article-материал для Timeweb Cloud со статусом draft/);
});

test('Sostav Nakrutka PF publication confirmation is repeatable and preserves owner-confirmed URL state', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  t.after(remove);
  initializeDatabase(databasePath);

  const first = applySostavNakrutkaPfPublication(databasePath);
  const second = applySostavNakrutkaPfPublication(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const publication = database.prepare(`SELECT status, reviewed_by, reviewed_at, content, data_json FROM memory_candidates WHERE semantic_key = 'publication.sostav_nakrutka_pf_2026_08_29'`).get();
  database.close();
  assert.equal(publication.status, 'approved');
  assert.equal(publication.reviewed_by, 'owner');
  assert.equal(publication.reviewed_at, '2026-08-29T00:00:00.000Z');
  assert.match(publication.content, /Sostav \/ SBlogs/);
  assert.deepEqual(JSON.parse(publication.data_json), {
    platform: 'Sostav / SBlogs', publication_date: '2026-08-29', publication_status: 'confirmed', confirmation_basis: 'owner_confirmation', public_url: 'unknown/not_provided', final_article_path: 'work/articles/published/2026-08-29-sostav-nakrutka-pf.md', evidence: { path: 'knowledge/decisions/sostav-nakrutka-pf-publication-2026-08-29.md' },
  });
  const exported = exportCurrentContext(databasePath, outputPath, '2026-08-29T00:00:00.000Z').content;
  assert.match(exported, /Публикация «Накрутка ПФ» на Sostav \/ SBlogs/);
  assert.match(exported, /unknown \/ not_provided/);
});

test('publication link confirmations evolve Sostav URL and add Oborot publication repeatably', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  t.after(remove);
  initializeDatabase(databasePath);
  applySostavNakrutkaPfPublication(databasePath);

  const first = applyPublicationLinksSostavOborot(databasePath);
  const second = applyPublicationLinksSostavOborot(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 2 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const facts = readMemory('facts', '', databasePath);
  assert.match(facts, /https:\/\/www\.sostav\.ru\/blogs\/293151\/104675/);
  assert.match(facts, /https:\/\/oborot\.ru\/blogs\/nakrutka-pf-i277755\.html/);
  assert.doesNotMatch(facts, /unknown \/ not_provided/);
  const exported = exportCurrentContext(databasePath, outputPath, '2026-08-29T15:00:00.000Z').content;
  assert.match(exported, /https:\/\/www\.sostav\.ru\/blogs\/293151\/104675/);
  assert.match(exported, /https:\/\/oborot\.ru\/blogs\/nakrutka-pf-i277755\.html/);
  assert.doesNotMatch(exported, /unknown \/ not_provided/);
});

test('TenChat publication continuity and indexation checks evolve memory repeatably', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  t.after(remove);
  initializeDatabase(databasePath);
  applySostavNakrutkaPfPublication(databasePath);
  applyPublicationLinksSostavOborot(databasePath);

  const first = applyTenchatPublicationAndIndexationContinuity(databasePath);
  const second = applyTenchatPublicationAndIndexationContinuity(databasePath);
  assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 3, tasks: 1 });
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0, tasks: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const tenchat = database.prepare("SELECT status, content, data_json FROM memory_candidates WHERE semantic_key='publication.tenchat_first_post_2026_08_30'").get();
  const sostav = database.prepare("SELECT content, data_json FROM memory_candidates WHERE semantic_key='publication.sostav_nakrutka_pf_2026_08_29' ORDER BY json_extract(data_json, '$.revision') DESC LIMIT 1").get();
  const oborot = database.prepare("SELECT content, data_json FROM memory_candidates WHERE semantic_key='publication.oborot_nakrutka_pf_business_2026_08_29' ORDER BY json_extract(data_json, '$.revision') DESC LIMIT 1").get();
  const task = database.prepare("SELECT status, content, data_json FROM tasks WHERE id=?").get(first.taskId);
  database.close();

  assert.equal(tenchat.status, 'approved');
  assert.match(tenchat.content, /Накрутка ПФ в Яндексе/);
  assert.equal(JSON.parse(tenchat.data_json).asset_format.aspect_ratio, '4:5');
  assert.equal(JSON.parse(sostav.data_json).yandex_indexation.status, 'confirmed');
  assert.match(sostav.content, /Индексация Google не подтверждена/);
  assert.equal(JSON.parse(oborot.data_json).yandex_indexation.status, 'not_confirmed');
  assert.match(oborot.content, /не подтвердила индексацию Яндексом/);
  assert.equal(task.status, 'pending');
  assert.equal(JSON.parse(task.data_json).requires_separate_owner_command, true);
  assert.match(task.content, /Кампания ещё не запускалась/);

  const exported = exportCurrentContext(databasePath, outputPath, '2026-08-30T09:00:00.000Z').content;
  assert.match(exported, /Первая публикация MetricHit в TenChat/);
  assert.match(exported, /6013324-nakrutka-pf-v-yandekse/);
  assert.match(exported, /точным url:-запросом/);
  assert.match(exported, /Индексация Google также не подтверждена/);
  assert.match(exported, /Настроить ПФ-продвижение опубликованной TenChat-страницы/);
});

test('memory CLI reads approved memory without modifying the database', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  importChatSummaries(databasePath);
  applyInitialMemoryDecision(databasePath);
  applyModelRoutingPolicy(databasePath);
  applyProductPositioningAndEditorialDirectness(databasePath);

  const beforeDatabase = new DatabaseSync(databasePath, { readOnly: true });
  const before = beforeDatabase.prepare('SELECT count(*) AS count FROM memory_candidates').get().count;
  beforeDatabase.close();
  const summary = readMemory('summary', '', databasePath);
  const avito = readMemory('search', 'Avito', databasePath);
  const tasks = readMemory('tasks', '', databasePath);
  const facts = readMemory('facts', '', databasePath);
  const decisions = readMemory('decisions', '', databasePath);
  const rules = readMemory('rules', '', databasePath);
  const sources = readMemory('sources', '', databasePath);
  const pending = readMemory('pending', '', databasePath);
  const conflicts = readMemory('conflicts', '', databasePath);
  const afterDatabase = new DatabaseSync(databasePath, { readOnly: true });
  const after = afterDatabase.prepare('SELECT count(*) AS count FROM memory_candidates').get().count;
  afterDatabase.close();

  assert.match(summary, /Approved candidates: 29/);
  assert.match(avito, /Пять активных объявлений Avito/);
  assert.match(tasks, /registration_click/);
  assert.match(facts, /Действующая тарифная сетка/);
  assert.match(decisions, /Политика выбора модели Codex/);
  assert.doesNotMatch(rules, /Не давать недоказуемых гарантий/);
  assert.match(facts, /Назначение MetricHit/);
  assert.match(decisions, /Прямая редакционная политика MetricHit/);
  assert.match(decisions, /Фокус публичных материалов MetricHit на поисковой выдаче/);
  assert.match(sources, /Решение владельца по первоначальным кандидатам памяти/);
  assert.match(pending, /Нет записей/);
  assert.match(conflicts, /Нет записей/);
  assert.equal(after, before);
});

test('memory search returns only the current semantic revision unless history is requested', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  t.after(remove);
  initializeDatabase(databasePath);
  applySostavNakrutkaPfPublication(databasePath);
  applyPublicationLinksSostavOborot(databasePath);

  const current = readMemory('search', 'Sostav', databasePath);
  const history = readMemory('search-history', 'Sostav', databasePath);

  assert.equal((current.match(/Публикация «Накрутка ПФ» на Sostav/g) ?? []).length, 1);
  assert.match(current, /Публичный URL, переданный владельцем/);
  assert.equal((history.match(/Публикация «Накрутка ПФ» на Sostav/g) ?? []).length, 2);
  assert.match(history, /ревизия 2/);
  assert.match(history, /ревизия 0/);
});

test('current context export separates approved memory from open tasks', (t) => {
  const { databasePath, remove } = temporaryDatabase(t);
  const outputPath = join(dirname(databasePath), 'current-context.md');
  t.after(remove);
  importChatSummaries(databasePath);
  applyInitialMemoryDecision(databasePath);
  applyModelRoutingPolicy(databasePath);
  applyProductPositioningAndEditorialDirectness(databasePath);

  const result = exportCurrentContext(databasePath, outputPath, '2026-08-13T12:00:00.000Z');
  assert.match(result.content, /# MetricHit — текущий рабочий контекст/);
  assert.match(result.content, /GPT-5\.6 Terra/);
  assert.match(result.content, /накрутки и улучшения поведенческих факторов/);
  assert.doesNotMatch(result.content, /Не давать недоказуемых гарантий/);
  assert.match(result.content, /## Открытые задачи и планы/);
  assert.match(result.content, /registration_click/);
  assert.doesNotMatch(result.content, /analytics\.utm_registration_click/);
  assert.doesNotMatch(result.content, /workspace\/scratch|libfile/i);
});
