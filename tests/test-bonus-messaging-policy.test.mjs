import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { initializeDatabase } from '../scripts/init-memory.mjs';
import { applyTestBonusMessaging } from '../scripts/apply-test-bonus-messaging.mjs';

test('test bonus messaging policy is approved and idempotent', (t) => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-test-bonus-messaging-'));
  const databasePath = join(directory, 'memory.db');
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  initializeDatabase(databasePath);

  const setup = new DatabaseSync(databasePath);
  try {
    const sourceId = '11111111-1111-4111-a111-111111111111';
    setup.prepare(`
      INSERT INTO sources (id, type, title, content, data_json, status, author)
      VALUES (?, 'fixture', 'Base bonus source', 'Fixture', '{}', 'active', 'test')
    `).run(sourceId);
    setup.prepare(`
      INSERT INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author)
      VALUES (?, 'product_fact', 'bonus.new_user_test_clicks', 'Base bonus', ?, '{}', 'pending', ?, 'test')
    `).run('22222222-2222-4222-a222-222222222222', 'Original base bonus fact', sourceId);
  } finally {
    setup.close();
  }

  const first = applyTestBonusMessaging(databasePath);
  const second = applyTestBonusMessaging(databasePath);
  assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

  const database = new DatabaseSync(databasePath, { readOnly: true });
  try {
    const rule = database.prepare(`
      SELECT semantic_key, status, content FROM memory_candidates WHERE id = ?
    `).get(first.candidateId);
    assert.equal(rule.semantic_key, 'content.test_bonus_messaging');
    assert.equal(rule.status, 'approved');
    assert.match(rule.content, /без пополнения баланса/);
    const baseFact = database.prepare(`
      SELECT content, status FROM memory_candidates WHERE semantic_key = 'bonus.new_user_test_clicks'
    `).get();
    assert.equal(baseFact.content, 'Original base bonus fact');
    assert.equal(baseFact.status, 'pending');
  } finally {
    database.close();
  }
});
