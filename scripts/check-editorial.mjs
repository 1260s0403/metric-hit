import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

import { migrationsFrom } from './init-editorial.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'editorial', 'editorial.sqlite');
const defaultMigrationsPath = join(repositoryRoot, 'data', 'editorial', 'migrations');
const defaultPendingMigrationsPath = join(repositoryRoot, 'data', 'editorial', 'pending-migrations');

export const requiredTables = [
  'schema_migrations', 'editorial_runs', 'research_sources', 'research_items', 'topic_proposals',
  'daily_plans', 'plan_items', 'materials', 'material_versions', 'approvals', 'publication_jobs',
  'audit_events', 'idempotency_keys',
];
export const requiredTriggers = ['audit_events_prevent_update', 'audit_events_prevent_delete'];

function normalizedSql(sql) {
  return sql.replace(/\s+/g, ' ').trim().replace(/;$/, '');
}

function expectedProtectiveTriggers(migrations) {
  const database = new DatabaseSync(':memory:');
  try {
    for (const { sql } of migrations) database.exec(sql);
    return new Map(database.prepare(`
      SELECT name, sql FROM sqlite_master
      WHERE type = 'trigger' AND name IN (${requiredTriggers.map(() => '?').join(', ')})
    `).all(...requiredTriggers).map(({ name, sql }) => [name, normalizedSql(sql)]));
  } finally {
    database.close();
  }
}

export function checkEditorialDatabase(databasePath = defaultDatabasePath, options = {}) {
  const migrationsPath = options.migrationsPath ?? defaultMigrationsPath;
  if (!existsSync(databasePath)) throw new Error(`Editorial database does not exist: ${databasePath}`);
  const database = new DatabaseSync(databasePath, { readOnly: true });
  try {
    database.exec('PRAGMA query_only = ON; PRAGMA foreign_keys = ON;');
    const integrity = database.prepare('PRAGMA integrity_check').all();
    const foreignKeyErrors = database.prepare('PRAGMA foreign_key_check').all();
    const applied = database.prepare('SELECT version, name, checksum FROM schema_migrations ORDER BY version').all();
    const canonicalMigrations = migrationsFrom(migrationsPath);
    const pendingMigrationsPath = options.pendingMigrationsPath
      ?? (options.migrationsPath ? null : defaultPendingMigrationsPath);
    const pendingMigrations = pendingMigrationsPath && existsSync(pendingMigrationsPath)
      ? migrationsFrom(pendingMigrationsPath)
      : [];
    const appliedVersions = new Set(applied.map(({ version }) => version));
    const migrations = [
      ...canonicalMigrations,
      ...pendingMigrations.filter(({ version }) => appliedVersions.has(version)),
    ].sort((left, right) => left.version - right.version);
    const expected = migrations.map(({ version, name, checksum }) => ({ version, name, checksum }));
    const expectedTriggers = expectedProtectiveTriggers(migrations);
    const tables = database.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).all().map(({ name }) => name);
    const triggerRows = database.prepare("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name").all();
    const missingTables = requiredTables.filter((name) => !tables.includes(name));
    const missingTriggers = requiredTriggers.filter((name) => !triggerRows.some((row) => row.name === name));
    if (integrity.length !== 1 || integrity[0].integrity_check !== 'ok') {
      throw new Error(`Integrity check failed: ${JSON.stringify(integrity)}`);
    }
    if (foreignKeyErrors.length) throw new Error(`Foreign key check failed: ${JSON.stringify(foreignKeyErrors)}`);
    if (JSON.stringify(applied) !== JSON.stringify(expected)) throw new Error('Applied migrations do not match migration files');
    if (missingTables.length) throw new Error(`Missing tables: ${missingTables.join(', ')}`);
    if (missingTriggers.length) throw new Error(`Missing protective triggers: ${missingTriggers.join(', ')}`);
    for (const name of requiredTriggers) {
      const trigger = triggerRows.find((row) => row.name === name);
      if (normalizedSql(trigger.sql) !== expectedTriggers.get(name)) {
        throw new Error(`Protective trigger is invalid: ${name}`);
      }
    }
    return { databasePath, migrations: applied.length, tables: tables.length, integrity: 'ok' };
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  try {
    const result = checkEditorialDatabase(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
    console.log(`Editorial database is valid and read-only check passed: ${result.databasePath}`);
    console.log(`Migrations: ${result.migrations}; tables: ${result.tables}; integrity: ${result.integrity}`);
  } catch (error) {
    console.error(`check-editorial: ${error.message}`);
    process.exitCode = 1;
  }
}
