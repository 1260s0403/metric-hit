import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

import { checkEditorialDatabase, requiredTables } from '../scripts/check-editorial.mjs';
import { initializeEditorialDatabase } from '../scripts/init-editorial.mjs';

const repositoryRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const memoryDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const historicalMaterialPath = join(repositoryRoot, 'work', 'landing', 'index.html');
const migrationsPath = join(repositoryRoot, 'data', 'editorial', 'migrations');
const hash = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');
const uuid = (value) => `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const sha = 'a'.repeat(64);

function temporaryEditorialDatabase(t) {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-editorial-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return { directory, databasePath: join(directory, 'editorial.sqlite') };
}

test('editorial database initializes repeatably with the required schema', (t) => {
  const { databasePath } = temporaryEditorialDatabase(t);
  const first = initializeEditorialDatabase(databasePath);
  const second = initializeEditorialDatabase(databasePath);
  assert.equal(first.applied.length, 1);
  assert.deepEqual(second.applied, first.applied);
  assert.equal(checkEditorialDatabase(databasePath).integrity, 'ok');

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const tables = database.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").all()
    .map(({ name }) => name);
  database.close();
  for (const table of requiredTables) assert.ok(tables.includes(table), `missing ${table}`);
});

test('editorial status, foreign-key, path, and hash constraints are enforced', (t) => {
  const { databasePath } = temporaryEditorialDatabase(t);
  initializeEditorialDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON');
  assert.throws(() => database.prepare(`
    INSERT INTO editorial_runs (id, business_date, timezone, mode, status, config_sha256)
    VALUES (?, '2026-08-14', 'Asia/Yekaterinburg', 'simulation', 'invalid', ?)
  `).run(uuid(1), sha));
  assert.throws(() => database.prepare(`
    INSERT INTO research_items (id, source_id, canonical_url, content_sha256, received_at, expires_at, source_class, reliability)
    VALUES (?, ?, 'https://example.test/a', ?, '2026-08-14T00:00:00.000Z', '2026-08-15T00:00:00.000Z', 'official', 'high')
  `).run(uuid(2), uuid(999), sha));
  database.prepare(`
    INSERT INTO research_sources (id, host, source_class, reliability) VALUES (?, 'example.test', 'official', 'high')
  `).run(uuid(3));
  assert.throws(() => database.prepare(`
    INSERT INTO research_items (id, source_id, canonical_url, content_sha256, received_at, expires_at, source_class, reliability, relative_path)
    VALUES (?, ?, 'https://example.test/a', ?, '2026-08-14T00:00:00.000Z', '2026-08-15T00:00:00.000Z', 'official', 'high', 'C:\\private.txt')
  `).run(uuid(4), uuid(3), sha));
  database.close();
});

test('audit events are append-only while inserts remain possible', (t) => {
  const { databasePath } = temporaryEditorialDatabase(t);
  initializeEditorialDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  const eventId = uuid(5);
  database.prepare(`
    INSERT INTO audit_events (id, actor_type, actor_id, event_type, entity_type, entity_id, data_json, event_hash)
    VALUES (?, 'system', 'test', 'created', 'fixture', 'fixture-1', '{}', ?)
  `).run(eventId, sha);
  assert.throws(() => database.prepare('UPDATE audit_events SET event_type = ? WHERE id = ?').run('changed', eventId));
  assert.throws(() => database.prepare('DELETE FROM audit_events WHERE id = ?').run(eventId));
  assert.equal(database.prepare('SELECT count(*) AS count FROM audit_events').get().count, 1);
  database.close();
});

test('modified applied migrations are detected without changing the canonical migration', (t) => {
  const { directory, databasePath } = temporaryEditorialDatabase(t);
  const copiedMigrations = join(directory, 'migrations');
  cpSync(migrationsPath, copiedMigrations, { recursive: true });
  initializeEditorialDatabase(databasePath, { migrationsPath: copiedMigrations });
  const migration = join(copiedMigrations, '001_editorial_foundation.sql');
  writeFileSync(migration, `${readFileSync(migration, 'utf8')}\n-- altered fixture\n`, 'utf8');
  assert.throws(() => initializeEditorialDatabase(databasePath, { migrationsPath: copiedMigrations }), /modified after being applied/);
  assert.throws(() => checkEditorialDatabase(databasePath, { migrationsPath: copiedMigrations }), /Applied migrations do not match/);
});

test('editorial checker rejects a modified protective audit trigger', (t) => {
  const { databasePath } = temporaryEditorialDatabase(t);
  initializeEditorialDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  database.exec(`
    DROP TRIGGER audit_events_prevent_update;
    CREATE TRIGGER audit_events_prevent_update
    BEFORE UPDATE ON audit_events BEGIN SELECT 1; END;
  `);
  database.close();
  assert.throws(() => checkEditorialDatabase(databasePath), /Protective trigger is invalid/);
});

test('temporary editorial work leaves memory and historical materials unchanged', (t) => {
  const { databasePath } = temporaryEditorialDatabase(t);
  const memoryBefore = hash(memoryDatabasePath);
  const materialBefore = hash(historicalMaterialPath);
  initializeEditorialDatabase(databasePath);
  checkEditorialDatabase(databasePath);
  assert.equal(hash(memoryDatabasePath), memoryBefore);
  assert.equal(hash(historicalMaterialPath), materialBefore);
});
