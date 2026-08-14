import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'editorial', 'editorial.sqlite');
const defaultMigrationsPath = join(repositoryRoot, 'data', 'editorial', 'migrations');

export function migrationsFrom(migrationsPath = defaultMigrationsPath) {
  return readdirSync(migrationsPath)
    .filter((name) => /^\d+_[a-z0-9_-]+\.sql$/i.test(name))
    .sort()
    .map((name) => {
      const version = Number.parseInt(name.split('_', 1)[0], 10);
      const sql = readFileSync(join(migrationsPath, name), 'utf8');
      return { version, name, sql, checksum: createHash('sha256').update(sql).digest('hex') };
    });
}

function appliedMigrations(database) {
  const exists = database.prepare(
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'",
  ).get();
  if (!exists) return new Map();
  return new Map(database.prepare('SELECT version, name, checksum FROM schema_migrations').all()
    .map(({ version, name, checksum }) => [version, { name, checksum }]));
}

export function initializeEditorialDatabase(databasePath = defaultDatabasePath, options = {}) {
  const migrationsPath = options.migrationsPath ?? defaultMigrationsPath;
  mkdirSync(dirname(databasePath), { recursive: true });
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;');
  try {
    const applied = appliedMigrations(database);
    const migrations = migrationsFrom(migrationsPath);
    if (!migrations.length) throw new Error('No editorial migrations found');
    const seen = new Set();
    for (const migration of migrations) {
      if (seen.has(migration.version)) throw new Error(`Duplicate migration version: ${migration.version}`);
      seen.add(migration.version);
      const recorded = applied.get(migration.version);
      if (recorded) {
        if (recorded.name !== migration.name || recorded.checksum !== migration.checksum) {
          throw new Error(`Migration ${migration.name} was modified after being applied`);
        }
        continue;
      }
      database.exec('BEGIN IMMEDIATE');
      try {
        database.exec(migration.sql);
        database.prepare('INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)')
          .run(migration.version, migration.name, migration.checksum);
        database.exec('COMMIT');
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    }
    return {
      databasePath,
      applied: database.prepare('SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version').all(),
    };
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  try {
    const result = initializeEditorialDatabase(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
    console.log(`Editorial database initialized: ${result.databasePath}`);
    console.log(`Migrations applied: ${result.applied.map(({ version }) => version).join(', ')}`);
  } catch (error) {
    console.error(`init-editorial: ${error.message}`);
    process.exitCode = 1;
  }
}
