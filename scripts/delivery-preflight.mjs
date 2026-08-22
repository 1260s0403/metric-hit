import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { resolve, relative } from 'node:path';

function git(repo, args) {
  return execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim();
}

function listFiles(root) {
  if (!existsSync(root)) return [];
  const files = [];
  const visit = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (entry.isFile()) files.push(relative(root, path).replaceAll('\\', '/'));
    }
  };
  visit(root);
  return files.sort();
}

export function deliveryPreflight({ repo = process.cwd(), externalApprovalRequired = false } = {}) {
  const root = resolve(repo);
  const status = git(root, ['status', '--short']);
  const inboxFiles = listFiles(resolve(root, 'work', 'inbox'));
  return {
    schemaVersion: 1,
    readyForWork: status === '',
    git: { clean: status === '', branch: git(root, ['branch', '--show-current']), head: git(root, ['rev-parse', 'HEAD']) },
    inbox: { unprocessedFiles: inboxFiles, count: inboxFiles.length },
    externalApprovalRequired: Boolean(externalApprovalRequired),
  };
}

function parseArgs(args) {
  let externalApprovalRequired = false;
  let repo = process.cwd();
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === '--external-approval-required') externalApprovalRequired = true;
    else if (args[index] === '--repo' && args[index + 1]) repo = args[++index];
    else throw new Error('Usage: delivery-preflight [--external-approval-required] [--repo <path>]');
  }
  return { externalApprovalRequired, repo };
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].replaceAll('\\', '/'))) {
  const envelope = deliveryPreflight(parseArgs(process.argv.slice(2)));
  console.log(JSON.stringify(envelope));
  process.exitCode = envelope.readyForWork ? 0 : 2;
}
