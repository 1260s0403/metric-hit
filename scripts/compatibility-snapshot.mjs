import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

import { checkDatabase } from './check-memory.mjs';
import { checkEditorialDatabase } from './check-editorial.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function statusCounts(database, table) {
  return Object.fromEntries(database.prepare(
    `SELECT status, count(*) AS count FROM ${table} GROUP BY status ORDER BY status`,
  ).all().map(({ status, count }) => [status, count]));
}

function memorySnapshot() {
  const path = join(repositoryRoot, 'data', 'database', 'metrichit.db');
  const checked = checkDatabase(path);
  const database = new DatabaseSync(path, { readOnly: true });
  try {
    database.exec('PRAGMA query_only = ON; PRAGMA foreign_keys = ON;');
    return {
      integrity: checked.integrity,
      migration_count: checked.migrationCount,
      tables: checked.tables,
      candidate_statuses: statusCounts(database, 'memory_candidates'),
      open_conflicts: database.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status='open'").get().count,
      open_tasks: database.prepare("SELECT count(*) AS count FROM tasks WHERE status IN ('pending','in_progress')").get().count,
      source_count: database.prepare('SELECT count(*) AS count FROM sources').get().count,
    };
  } finally {
    database.close();
  }
}

function editorialSnapshot() {
  const path = join(repositoryRoot, 'data', 'editorial', 'editorial.sqlite');
  const checked = checkEditorialDatabase(path);
  const database = new DatabaseSync(path, { readOnly: true });
  const entities = {};
  try {
    database.exec('PRAGMA query_only = ON; PRAGMA foreign_keys = ON;');
    for (const table of ['editorial_runs', 'daily_plans', 'materials', 'approvals', 'publication_jobs']) {
      entities[table] = {
        count: database.prepare(`SELECT count(*) AS count FROM ${table}`).get().count,
        statuses: statusCounts(database, table),
      };
    }
    return {
      integrity: checked.integrity,
      migration_count: checked.migrations,
      tables: database.prepare(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
      ).all().map(({ name }) => name),
      entities,
    };
  } finally {
    database.close();
  }
}

function contextSnapshot() {
  const content = readFileSync(join(repositoryRoot, 'knowledge', 'approved', 'current-context.md'), 'utf8');
  return {
    exists: true,
    sha256: createHash('sha256').update(content).digest('hex'),
    content,
  };
}

console.log(JSON.stringify({ memory: memorySnapshot(), editorial: editorialSnapshot(), context: contextSnapshot() }));
