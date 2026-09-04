import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

import { checkEditorialDatabase, requiredTables } from '../scripts/check-editorial.mjs';
import { initializeEditorialDatabase, migrationsFrom, updateEditorialInfrastructure } from '../scripts/init-editorial.mjs';
import { initializeDatabase as initializeMemoryDatabase } from '../scripts/init-memory.mjs';

const repositoryRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const migrationsPath = join(repositoryRoot, 'data', 'editorial', 'migrations');
const pendingMigrationsPath = join(repositoryRoot, 'data', 'editorial', 'pending-migrations');
const hash = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');
const uuid = (value) => `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const sha = 'a'.repeat(64);

function temporaryEditorialDatabase(t) {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-editorial-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return { directory, databasePath: join(directory, 'editorial.sqlite') };
}

function temporaryProjectDatabase(t) {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-editorial-project-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const databasePath = join(directory, 'project.sqlite');
  initializeMemoryDatabase(databasePath);
  const database = new DatabaseSync(databasePath);
  database.exec(`CREATE TABLE project_storage_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    project_id TEXT NOT NULL,
    storage_format INTEGER NOT NULL
  ) STRICT;`);
  database.prepare('INSERT INTO project_storage_metadata VALUES (1,?,1)')
    .run('00000000-0000-4000-a000-000000000102');
  database.close();
  return { directory, databasePath };
}

test('absent editorial database is an explicit paused state', (t) => {
  const { databasePath } = temporaryEditorialDatabase(t);
  assert.deepEqual(checkEditorialDatabase(databasePath), {
    databasePath,
    exists: false,
    state: 'paused',
    migrations: 0,
    tables: 0,
    integrity: 'not_applicable',
  });
});

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

  const pending = migrationsFrom(pendingMigrationsPath)[0];
  const writable = new DatabaseSync(databasePath);
  writable.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  writable.exec(pending.sql);
  writable.prepare('INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)')
    .run(pending.version, pending.name, pending.checksum);
  writable.exec('COMMIT');
  writable.close();
  assert.equal(checkEditorialDatabase(databasePath).migrations, 2);
});

test('update-infrastructure mode registers the five-profile sequential project pipeline idempotently', (t) => {
  const { databasePath } = temporaryProjectDatabase(t);
  const first = updateEditorialInfrastructure(databasePath);
  const second = updateEditorialInfrastructure(databasePath);
  assert.deepEqual(first.appliedNow, [1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(second.appliedNow, []);
  assert.equal(second.pipelineId, 'metrichit.editorial.pipeline.v1');
  assert.deepEqual(second.profiles.map(({ profile_id, stage_order, capability, profile_kind }) =>
    [profile_id, stage_order, capability, profile_kind]), [
    ['metrichit.editorial.planner.v1', 1, 'content-strategy', 'subagent'],
    ['metrichit.editorial.architect.v1', 2, 'seo-strategy', 'subagent'],
    ['metrichit.editorial.writer.v1', 3, 'copywriting', 'subagent'],
    ['metrichit.editorial.designer.v1', 4, 'image', 'subagent'],
    ['metrichit.editorial.validator.v1', 5, 'compliance-qa', 'internal_filter'],
  ]);
  for (const profile of second.profiles) {
    const policy = JSON.parse(profile.policy_json);
    assert.equal(policy.semantic_core.keyword_count, 302);
    assert.deepEqual(policy.zonal_distribution.applies_only_to, ['new_articles', 'new_longreads']);
    assert.deepEqual(policy.zonal_distribution.lsi.allowed_zones, ['h3', 'unordered_lists']);
    assert.equal(policy.zonal_distribution.lsi.role, 'non_targeted_professional_lexicon');
    assert.equal(policy.geo_gate.keyword_count, 37);
    assert.equal(policy.geo_gate.required_execution_card_flag, 'geo_demand_owner_confirmed');
  }
});

test('hotfix mode applies the empty-topic directive to each isolated profile', (t) => {
  const { databasePath } = temporaryProjectDatabase(t);
  const result = updateEditorialInfrastructure(databasePath, { hotfix: true });
  assert.equal(result.profiles.length, 5);
  assert.ok(result.profiles.every((profile) => profile.hotfix?.id === 'editorial.empty_topic.autoplanning.v1'));
  assert.equal(result.profiles.find((profile) => profile.profile_id === 'metrichit.editorial.planner.v1').hotfix.planner_execution_required, true);
  assert.equal(result.profiles.filter((profile) => profile.profile_id !== 'metrichit.editorial.planner.v1').every((profile) => profile.hotfix.downstream_input === 'consume_owner_approved_structure_only'), true);
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
  const { directory, databasePath } = temporaryEditorialDatabase(t);
  const memoryDatabasePath = join(directory, 'memory.sqlite');
  const historicalMaterialPath = join(directory, 'historical-material.html');
  writeFileSync(memoryDatabasePath, 'approved-memory-sentinel', 'utf8');
  writeFileSync(historicalMaterialPath, '<p>historical material sentinel</p>', 'utf8');
  const memoryBefore = hash(memoryDatabasePath);
  const materialBefore = hash(historicalMaterialPath);
  initializeEditorialDatabase(databasePath);
  checkEditorialDatabase(databasePath);
  assert.equal(hash(memoryDatabasePath), memoryBefore);
  assert.equal(hash(historicalMaterialPath), materialBefore);
});
