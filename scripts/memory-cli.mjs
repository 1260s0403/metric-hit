import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const approvedWhere = "status = 'approved'";

function openReadOnly(databasePath) {
  if (!existsSync(databasePath)) throw new Error(`Database does not exist: ${databasePath}`);
  return new DatabaseSync(databasePath, { readOnly: true });
}

function renderRows(rows) {
  if (!rows.length) return 'Нет записей.';
  return rows.map((row) => {
    const key = row.semantic_key ? ` ${String.fromCharCode(96)}${row.semantic_key}${String.fromCharCode(96)}` : '';
    const detail = row.content ? ` — ${row.content}` : '';
    return `- **${row.title ?? row.name ?? row.id}**${key}${detail}`;
  }).join('\n');
}

export function readMemory(command, query = '', databasePath = defaultDatabasePath) {
  const database = openReadOnly(databasePath);
  try {
    const listApproved = (types) => {
      const excludedEditorialRules = types.includes('editorial_rule')
        ? `AND semantic_key NOT IN (
          SELECT value
          FROM memory_candidates AS policies, json_each(policies.data_json, '$.supersedes_editorial_rules')
          WHERE policies.status = 'approved' AND policies.semantic_key = 'content.editorial_directness_policy'
        )`
        : '';
      return database.prepare(`
      SELECT type, semantic_key, title, content
      FROM memory_candidates
      WHERE ${approvedWhere} AND type IN (${types.map(() => '?').join(', ')})
      ${excludedEditorialRules}
      ORDER BY semantic_key
      `).all(...types);
    };
    switch (command) {
      case 'summary': {
        const candidates = database.prepare(
          'SELECT status, count(*) AS count FROM memory_candidates GROUP BY status ORDER BY status',
        ).all();
        const taskCount = database.prepare(
          "SELECT count(*) AS count FROM tasks WHERE status IN ('pending', 'in_progress')",
        ).get().count;
        const sourceCount = database.prepare('SELECT count(*) AS count FROM sources').get().count;
        const conflictCount = database.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status = 'open'").get().count;
        return [
          '# MetricHit memory summary',
          `- Approved candidates: ${candidates.find((row) => row.status === 'approved')?.count ?? 0}`,
          `- Pending candidates: ${candidates.find((row) => row.status === 'pending')?.count ?? 0}`,
          `- Rejected candidates: ${candidates.find((row) => row.status === 'rejected')?.count ?? 0}`,
          `- Open tasks: ${taskCount}`,
          `- Registered sources: ${sourceCount}`,
          `- Open conflicts: ${conflictCount}`,
        ].join('\n');
      }
      case 'facts': return `# Approved facts\n\n${renderRows(listApproved(['product_fact', 'commercial_terms', 'official_resource', 'official_channel', 'publication_state']))}`;
      case 'decisions': return `# Approved decisions\n\n${renderRows(listApproved(['decision', 'ai_policy']))}`;
      case 'rules': return `# Active rules\n\n${renderRows(listApproved(['editorial_rule']))}`;
      case 'tasks': {
        const rows = database.prepare(`
          SELECT type, title, content FROM tasks
          WHERE status IN ('pending', 'in_progress') ORDER BY created_at, title
        `).all();
        return `# Open tasks\n\n${renderRows(rows)}`;
      }
      case 'sources': {
        const rows = database.prepare('SELECT id, title, content FROM sources ORDER BY created_at, title').all();
        return `# Registered sources\n\n${renderRows(rows)}`;
      }
      case 'pending': {
        const rows = database.prepare(`
          SELECT type, semantic_key, title, content FROM memory_candidates
          WHERE status = 'pending' ORDER BY semantic_key
        `).all();
        return `# Pending candidates\n\n${renderRows(rows)}`;
      }
      case 'conflicts': {
        const rows = database.prepare(`
          SELECT id, title, content FROM memory_conflicts
          WHERE status = 'open' ORDER BY created_at
        `).all();
        return `# Open conflicts\n\n${renderRows(rows)}`;
      }
      case 'search': {
        if (!query.trim()) throw new Error('search requires text');
        const escaped = `%${query.trim().replaceAll('\\', '\\\\').replaceAll('%', '\\%').replaceAll('_', '\\_')}%`;
        const rows = database.prepare(`
          SELECT type, semantic_key, title, content FROM memory_candidates
          WHERE ${approvedWhere} AND (
            title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR semantic_key LIKE ? ESCAPE '\\'
          ) ORDER BY semantic_key
        `).all(escaped, escaped, escaped);
        return `# Search: ${query.trim()}\n\n${renderRows(rows)}`;
      }
      default: throw new Error(`Unknown command: ${command}`);
    }
  } finally {
    database.close();
  }
}

function parseArguments(argumentsList) {
  const values = [...argumentsList];
  const dbIndex = values.indexOf('--db');
  const databasePath = dbIndex === -1 ? defaultDatabasePath : resolve(values[dbIndex + 1]);
  if (dbIndex !== -1) values.splice(dbIndex, 2);
  return { command: values[0], query: values.slice(1).join(' '), databasePath };
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  try {
    const { command, query, databasePath } = parseArguments(process.argv.slice(2));
    if (!command) throw new Error('Usage: memory-cli.mjs <summary|facts|decisions|rules|tasks|sources|search|pending|conflicts> [text]');
    console.log(readMemory(command, query, databasePath));
  } catch (error) {
    console.error(`memory-cli: ${error.message}`);
    process.exitCode = 1;
  }
}
