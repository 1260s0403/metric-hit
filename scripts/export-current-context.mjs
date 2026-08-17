import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const defaultOutputPath = join(repositoryRoot, 'knowledge', 'approved', 'current-context.md');

function section(database, heading, types) {
  const excludedEditorialRules = types.includes('editorial_rule')
    ? `AND semantic_key NOT IN (
      SELECT value
      FROM memory_candidates AS policies, json_each(policies.data_json, '$.supersedes_editorial_rules')
      WHERE policies.status = 'approved' AND policies.semantic_key = 'content.editorial_directness_policy'
    )`
    : '';
  const rows = database.prepare(`
    SELECT title, content FROM (
      SELECT title, content, semantic_key,
             ROW_NUMBER() OVER (
               PARTITION BY semantic_key
               ORDER BY coalesce(json_extract(data_json, '$.revision'), 0) DESC,
                        reviewed_at DESC, updated_at DESC, id DESC
             ) AS revision_rank
      FROM memory_candidates
      WHERE status = 'approved' AND type IN (${types.map(() => '?').join(', ')})
      AND NOT EXISTS (
        SELECT 1 FROM memory_conflicts
        WHERE memory_conflicts.candidate_id = memory_candidates.id
          AND memory_conflicts.status IN ('open', 'dismissed')
      )
      ${excludedEditorialRules}
    ) WHERE revision_rank = 1
    ORDER BY semantic_key
  `).all(...types);
  const body = rows.length
    ? rows.map(({ title, content }) => `- **${title}:** ${content}`).join('\n')
    : '- Нет утверждённых записей.';
  return `## ${heading}\n\n${body}`;
}

export function buildCurrentContext(databasePath = defaultDatabasePath, generatedAt = new Date().toISOString()) {
  const database = new DatabaseSync(databasePath, { readOnly: true });
  try {
    const openTasks = database.prepare(`
      SELECT title, content FROM tasks WHERE status IN ('pending', 'in_progress') ORDER BY created_at, title
    `).all();
    const tasks = openTasks.length
      ? openTasks.map(({ title, content }) => `- **${title}:** ${content}`).join('\n')
      : '- Нет открытых задач.';
    return [
      '# MetricHit — текущий рабочий контекст',
      '',
      `Сформировано: ${generatedAt}. Этот файл содержит только утверждённую память. Задачи и планы вынесены в отдельный раздел и не являются реализованными фактами.`,
      '',
      section(database, 'Основные факты о продукте', ['product_fact']),
      '',
      section(database, 'Коммерческие условия', ['commercial_terms']),
      '',
      section(database, 'Официальные ресурсы и каналы', ['official_resource', 'official_channel']),
      '',
      section(database, 'Действующие решения', ['decision', 'ai_policy']),
      '',
      section(database, 'Редакционные правила', ['editorial_rule']),
      '',
      section(database, 'Подтверждённые публикации и площадки', ['publication_state']),
      '',
      '## Открытые задачи и планы',
      '',
      tasks,
      '',
    ].join('\n');
  } finally {
    database.close();
  }
}

export function exportCurrentContext(databasePath = defaultDatabasePath, outputPath = defaultOutputPath, generatedAt) {
  const content = buildCurrentContext(databasePath, generatedAt);
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, content, 'utf8');
  return { outputPath, content };
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const databasePath = process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath;
  const result = exportCurrentContext(databasePath);
  console.log(`Current context exported: ${result.outputPath}`);
}
