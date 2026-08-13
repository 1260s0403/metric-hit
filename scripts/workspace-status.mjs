import { DatabaseSync } from 'node:sqlite';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { checkDatabase } from './check-memory.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const contours = [
  'inbox', 'landing', 'articles', 'articles/drafts', 'articles/published', 'articles/research',
  'articles/assets', 'social', 'social/telegram', 'social/telegram/drafts',
  'social/telegram/published', 'social/telegram/assets', 'social/vk', 'social/vk/drafts',
  'social/vk/published', 'social/vk/assets', 'brand', 'analytics', 'reports', 'archive',
];

function countMaterials(path) {
  if (!existsSync(path)) return 0;
  return readdirSync(path, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.toLowerCase() !== 'readme.md').length;
}

function gitOutput(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
  if (result.status !== 0) throw new Error(result.stderr.trim() || `git ${args.join(' ')} failed`);
  return result.stdout.trim();
}

export function collectWorkspaceStatus(root = repositoryRoot) {
  const databasePath = join(root, 'data', 'database', 'metrichit.db');
  const memoryCheck = checkDatabase(databasePath);
  const database = new DatabaseSync(databasePath, { readOnly: true });
  let memory;
  try {
    database.exec('PRAGMA query_only = ON');
    memory = {
      pendingCandidates: database.prepare("SELECT count(*) AS count FROM memory_candidates WHERE status = 'pending'").get().count,
      openConflicts: database.prepare("SELECT count(*) AS count FROM memory_conflicts WHERE status = 'open'").get().count,
      openTasks: database.prepare("SELECT count(*) AS count FROM tasks WHERE status NOT IN ('completed', 'cancelled', 'archived')").get().count,
    };
  } finally {
    database.close();
  }

  const backupDirectory = join(dirname(root), 'external-backups');
  const backups = existsSync(backupDirectory)
    ? readdirSync(backupDirectory).filter((name) => /^MetricHit-backup-\d{8}T\d{6}Z\.zip$/.test(name))
      .map((name) => ({ name, modified: statSync(join(backupDirectory, name)).mtime.toISOString() }))
      .sort((left, right) => right.name.localeCompare(left.name))
    : [];

  return {
    git: { clean: gitOutput(root, ['status', '--porcelain']).length === 0 },
    contours: Object.fromEntries(contours.map((contour) => [contour, countMaterials(join(root, 'work', contour))])),
    memory: { valid: memoryCheck.integrity === 'ok', ...memory },
    latestLocalBackup: backups[0] ?? null,
    inboxUnprocessed: countMaterials(join(root, 'work', 'inbox')),
  };
}

export function formatWorkspaceStatus(status) {
  const lines = [
    `Git: ${status.git.clean ? 'clean' : 'changes present'}`,
    'Work materials:',
    ...Object.entries(status.contours).map(([name, count]) => `  ${name}: ${count}`),
    `Memory: ${status.memory.valid ? 'valid' : 'invalid'}; pending candidates: ${status.memory.pendingCandidates}; open conflicts: ${status.memory.openConflicts}; open tasks: ${status.memory.openTasks}`,
    `Latest local backup: ${status.latestLocalBackup ? `${status.latestLocalBackup.name} (${status.latestLocalBackup.modified})` : 'none'}`,
    `Unprocessed work/inbox files: ${status.inboxUnprocessed}`,
  ];
  return lines.join('\n');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(formatWorkspaceStatus(collectWorkspaceStatus()));
}
