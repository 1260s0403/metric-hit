import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const migrationsPath = join(repositoryRoot, 'data', 'database', 'migrations');

export const requiredTables = [
  'audit_log',
  'decisions',
  'document_versions',
  'documents',
  'memory_candidates',
  'memory_conflicts',
  'memory_items',
  'context_packs',
  'scope_passports',
  'scope_routing_audit',
  'scoped_memory_records',
  'schema_migrations',
  'sources',
  'tasks',
  'unresolved_memory_queue',
];

export const requiredTriggers = [
  'audit_log_prevent_delete', 'audit_log_prevent_update',
  'document_versions_prevent_delete', 'document_versions_prevent_update',
  'memory_candidates_conflict_on_approval', 'memory_candidates_protect_terminal_delete',
  'memory_candidates_protect_terminal_update', 'memory_candidates_require_pending_insert',
  'memory_candidates_validate_review_metadata_insert',
  'memory_candidates_validate_review_metadata_update',
  'memory_candidates_validate_status_transition', 'memory_items_audit_insert',
  'memory_items_audit_update', 'memory_conflicts_prevent_delete',
  'memory_conflicts_protect_closed_decision', 'memory_conflicts_protect_history',
  'memory_conflicts_validate_insert', 'memory_conflicts_validate_update',
  'memory_items_prevent_delete',
  'memory_items_validate_update',
  'scope_passports_validate_hierarchy_insert',
  'scoped_memory_prevent_delete',
  'scoped_memory_protect_core_prohibition_insert',
  'scoped_memory_validate_supersedes_insert',
  'scope_routing_audit_prevent_delete', 'scope_routing_audit_prevent_update',
];

function expectedMigrations() {
  return readdirSync(migrationsPath)
    .filter((name) => /^\d+_[a-z0-9_-]+\.sql$/i.test(name))
    .sort()
    .map((name) => ({
      version: Number.parseInt(name.split('_', 1)[0], 10),
      name,
      checksum: createHash('sha256').update(readFileSync(join(migrationsPath, name))).digest('hex'),
    }));
}

function normalizeSql(sql) {
  return sql.replace(/\s+/g, ' ').trim().replace(/;$/, '');
}

function expectedTriggerDefinitions() {
  const database = new DatabaseSync(':memory:');
  try {
    for (const migration of expectedMigrations()) {
      database.exec(readFileSync(join(migrationsPath, migration.name), 'utf8'));
    }
    return new Map(database.prepare(
      "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name",
    ).all().map(({ name, sql }) => [name, normalizeSql(sql)]));
  } finally {
    database.close();
  }
}

export function checkDatabase(databasePath = defaultDatabasePath) {
  if (!existsSync(databasePath)) {
    throw new Error(`Database does not exist: ${databasePath}`);
  }

  const database = new DatabaseSync(databasePath, { readOnly: true });
  try {
    database.exec('PRAGMA query_only = ON; PRAGMA foreign_keys = ON;');
    const integrity = database.prepare('PRAGMA integrity_check').all();
    const foreignKeyErrors = database.prepare('PRAGMA foreign_key_check').all();
    const tables = database.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).all().map(({ name }) => name);
    const missingTables = requiredTables.filter((name) => !tables.includes(name));
    const migrations = database.prepare(
      'SELECT version, name, checksum FROM schema_migrations ORDER BY version',
    ).all().map(({ version, name, checksum }) => ({ version, name, checksum }));
    const triggerRows = database.prepare(
      "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name",
    ).all();
    const triggers = triggerRows.map(({ name }) => name);
    const missingTriggers = requiredTriggers.filter((name) => !triggers.includes(name));
    const structure = Object.fromEntries(tables.map((name) => [
      name,
      database.prepare(`PRAGMA table_info(${name})`).all().map(({ name: column }) => column),
    ]));

    if (integrity.length !== 1 || integrity[0].integrity_check !== 'ok') {
      throw new Error(`Integrity check failed: ${JSON.stringify(integrity)}`);
    }
    if (foreignKeyErrors.length) {
      throw new Error(`Foreign key check failed: ${JSON.stringify(foreignKeyErrors)}`);
    }
    if (missingTables.length) {
      throw new Error(`Missing tables: ${missingTables.join(', ')}`);
    }
    if (JSON.stringify(migrations) !== JSON.stringify(expectedMigrations())) {
      throw new Error('Applied migrations do not match migration files');
    }
    if (missingTriggers.length) {
      throw new Error(`Missing protective triggers: ${missingTriggers.join(', ')}`);
    }
    const expectedTriggers = expectedTriggerDefinitions();
    const unexpectedTriggers = triggers.filter((name) => !expectedTriggers.has(name));
    if (unexpectedTriggers.length) {
      throw new Error(`Unexpected triggers: ${unexpectedTriggers.join(', ')}`);
    }
    const absentExpectedTriggers = [...expectedTriggers.keys()].filter((name) => !triggers.includes(name));
    if (absentExpectedTriggers.length) {
      throw new Error(`Missing expected triggers: ${absentExpectedTriggers.join(', ')}`);
    }
    const alteredTriggers = [...expectedTriggers.keys()].filter((name) => {
      const live = triggerRows.find((trigger) => trigger.name === name);
      return live && normalizeSql(live.sql) !== expectedTriggers.get(name);
    });
    if (alteredTriggers.length) {
      throw new Error(`Altered protective triggers: ${alteredTriggers.join(', ')}`);
    }

    return { databasePath, tables, structure, migrationCount: migrations.length, integrity: 'ok' };
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const databasePath = process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath;
  const result = checkDatabase(databasePath);
  console.log(`Memory database is valid and read-only check passed: ${result.databasePath}`);
  console.log(`Tables (${result.tables.length}): ${result.tables.join(', ')}`);
  for (const [table, columns] of Object.entries(result.structure)) {
    console.log(`  ${table}: ${columns.join(', ')}`);
  }
  console.log(`Migrations: ${result.migrationCount}; integrity: ${result.integrity}`);
}
