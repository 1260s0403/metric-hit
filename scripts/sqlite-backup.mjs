import { DatabaseSync, backup } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const [sourceArgument, destinationArgument] = process.argv.slice(2);

if (!sourceArgument || !destinationArgument) {
  console.error('Usage: node scripts/sqlite-backup.mjs <source.db> <destination.db>');
  process.exitCode = 1;
} else {
  const sourcePath = resolve(sourceArgument);
  const destinationPath = resolve(destinationArgument);
  mkdirSync(dirname(destinationPath), { recursive: true });

  const source = new DatabaseSync(sourcePath, { readOnly: true });
  try {
    await backup(source, destinationPath);
    console.log(`SQLite online backup created: ${destinationPath}`);
  } finally {
    source.close();
  }
}
