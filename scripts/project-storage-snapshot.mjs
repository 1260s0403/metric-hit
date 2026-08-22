import { createHash } from 'node:crypto';
import {
  existsSync, lstatSync, mkdirSync, readdirSync, realpathSync, readFileSync,
} from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { DatabaseSync, backup } from 'node:sqlite';

const PROJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DATABASE_FILENAME = 'project.sqlite';

function inside(root, candidate) {
  const rel = relative(root, candidate);
  return rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel);
}

function hash(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function validateDatabase(path, expectedProjectId) {
  const database = new DatabaseSync(path, { readOnly: true });
  try {
    database.exec('PRAGMA query_only=ON;');
    const integrity = database.prepare('PRAGMA integrity_check').all();
    if (integrity.length !== 1 || integrity[0].integrity_check !== 'ok') {
      throw new Error(`Project storage integrity check failed: ${expectedProjectId}`);
    }
    const rows = database.prepare(
      'SELECT singleton, project_id, storage_format FROM project_storage_metadata',
    ).all();
    if (rows.length !== 1 || rows[0].singleton !== 1 || rows[0].project_id !== expectedProjectId || rows[0].storage_format !== 1) {
      throw new Error(`Project storage identity mismatch: ${expectedProjectId}`);
    }
  } finally {
    database.close();
  }
}

function enumerate(root) {
  if (!existsSync(root)) return [];
  if (!lstatSync(root).isDirectory() || lstatSync(root).isSymbolicLink()) {
    throw new Error('Project storage root must be a real directory.');
  }
  const canonicalRoot = realpathSync(root);
  return readdirSync(root, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).map((entry) => {
    if (!PROJECT_ID.test(entry.name) || !entry.isDirectory() || entry.isSymbolicLink()) {
      throw new Error(`Unexpected entry in project storage root: ${entry.name}`);
    }
    const directory = join(root, entry.name);
    const canonicalDirectory = realpathSync(directory);
    if (!inside(canonicalRoot, canonicalDirectory) || canonicalDirectory !== resolve(directory)) {
      throw new Error(`Project storage path escapes or redirects outside its root: ${entry.name}`);
    }
    const entries = readdirSync(directory, { withFileTypes: true });
    if (entries.length !== 1 || entries[0].name !== DATABASE_FILENAME || !entries[0].isFile() || entries[0].isSymbolicLink()) {
      throw new Error(`Project storage directory has an invalid layout: ${entry.name}`);
    }
    const database = join(directory, DATABASE_FILENAME);
    const canonicalDatabase = realpathSync(database);
    if (!inside(canonicalDirectory, canonicalDatabase) || canonicalDatabase !== resolve(database)) {
      throw new Error(`Project database path escapes or redirects outside its project: ${entry.name}`);
    }
    validateDatabase(database, entry.name);
    return { projectId: entry.name, database };
  });
}

export async function snapshotProjectStorages(sourceArgument, destinationArgument) {
  const sourceRoot = resolve(sourceArgument);
  const destinationRoot = resolve(destinationArgument);
  const before = enumerate(sourceRoot);
  mkdirSync(destinationRoot, { recursive: true });
  const inventory = [];
  for (const item of before) {
    const destination = join(destinationRoot, item.projectId, DATABASE_FILENAME);
    mkdirSync(dirname(destination), { recursive: true });
    const source = new DatabaseSync(item.database, { readOnly: true });
    try {
      await backup(source, destination);
    } finally {
      source.close();
    }
    validateDatabase(destination, item.projectId);
    inventory.push({
      projectId: item.projectId,
      path: `data/projects/${item.projectId}/${DATABASE_FILENAME}`,
      size: lstatSync(destination).size,
      sha256: hash(destination),
      storageFormat: 1,
      integrity: 'ok',
    });
  }
  const after = enumerate(sourceRoot).map(({ projectId }) => projectId);
  const expected = before.map(({ projectId }) => projectId);
  if (JSON.stringify(after) !== JSON.stringify(expected)) {
    throw new Error('Project storage set changed during online backup.');
  }
  return inventory;
}

export function verifyProjectStorages(rootArgument, expectedInventory) {
  const root = resolve(rootArgument);
  const actual = enumerate(root).map(({ projectId, database }) => ({
    projectId,
    path: `data/projects/${projectId}/${DATABASE_FILENAME}`,
    size: lstatSync(database).size,
    sha256: hash(database),
    storageFormat: 1,
    integrity: 'ok',
  }));
  if (JSON.stringify(actual) !== JSON.stringify(expectedInventory)) {
    throw new Error('Project storage inventory does not match the manifest.');
  }
  return actual;
}

async function main() {
  const [mode, root, target] = process.argv.slice(2);
  if (mode === 'snapshot' && root && target) {
    console.log(JSON.stringify(await snapshotProjectStorages(root, target)));
    return;
  }
  if (mode === 'verify' && root && target) {
    const inventoryJson = readFileSync(resolve(target), 'utf8').replace(/^\uFEFF/, '');
    console.log(JSON.stringify(verifyProjectStorages(root, JSON.parse(inventoryJson))));
    return;
  }
  throw new Error('Usage: project-storage-snapshot.mjs <snapshot sourceRoot destinationRoot|verify root inventory.json>');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
