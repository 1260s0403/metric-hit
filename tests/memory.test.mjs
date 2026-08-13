import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { checkDatabase, requiredTables } from '../scripts/check-memory.mjs';
import { initializeDatabase } from '../scripts/init-memory.mjs';

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
  assert.equal(result.migrationCount, 8);
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
