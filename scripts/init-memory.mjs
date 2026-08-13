import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const migrationsPath = join(repositoryRoot, 'data', 'database', 'migrations');

function appliedVersions(database) {
  const table = database.prepare(
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'",
  ).get();
  if (!table) return new Map();

  return new Map(
    database.prepare('SELECT version, checksum FROM schema_migrations').all()
      .map(({ version, checksum }) => [version, checksum]),
  );
}

export function initializeDatabase(databasePath = defaultDatabasePath) {
  mkdirSync(dirname(databasePath), { recursive: true });
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;');

  try {
    const applied = appliedVersions(database);
    const migrations = readdirSync(migrationsPath)
      .filter((name) => /^\d+_[a-z0-9_-]+\.sql$/i.test(name))
      .sort();

    for (const name of migrations) {
      const version = Number.parseInt(name.split('_', 1)[0], 10);
      const sql = readFileSync(join(migrationsPath, name), 'utf8');
      const checksum = createHash('sha256').update(sql).digest('hex');

      if (applied.has(version)) {
        if (applied.get(version) !== checksum) {
          throw new Error(`Migration ${name} was modified after being applied`);
        }
        continue;
      }

      database.exec('BEGIN IMMEDIATE');
      try {
        database.exec(sql);
        database.prepare(
          'INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)',
        ).run(version, name, checksum);
        database.exec('COMMIT');
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    }

    return {
      databasePath,
      applied: database.prepare(
        'SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version',
      ).all(),
    };
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const databasePath = process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath;
  const result = initializeDatabase(databasePath);
  console.log(`Memory database initialized: ${result.databasePath}`);
  console.log(`Migrations applied: ${result.applied.map(({ version }) => version).join(', ')}`);
}

