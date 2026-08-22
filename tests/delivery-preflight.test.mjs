import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import test from 'node:test';

const cli = resolve('scripts/delivery-preflight.mjs');

function repository() {
  const root = mkdtempSync(resolve(tmpdir(), 'delivery-preflight-'));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' });
  git('init', '--quiet'); git('config', 'user.name', 'Delivery Test'); git('config', 'user.email', 'delivery@test.invalid');
  writeFileSync(resolve(root, 'README.md'), 'ready\n'); git('add', 'README.md'); git('commit', '--quiet', '-m', 'initial');
  return root;
}

function run(root, args = []) {
  const result = spawnSync(process.execPath, [cli, '--repo', root, ...args], { encoding: 'utf8', timeout: 5000 });
  return { ...result, data: JSON.parse(result.stdout) };
}

test('preflight reports a clean repository and explicit approval need', () => {
  const result = run(repository(), ['--external-approval-required']);
  assert.equal(result.status, 0); assert.equal(result.data.readyForWork, true); assert.equal(result.data.git.clean, true); assert.equal(result.data.externalApprovalRequired, true);
});

test('preflight blocks a dirty repository and lists inbox files', () => {
  const root = repository(); writeFileSync(resolve(root, 'README.md'), 'dirty\n'); mkdirSync(resolve(root, 'work', 'inbox'), { recursive: true }); writeFileSync(resolve(root, 'work', 'inbox', 'request.txt'), 'incoming\n');
  const result = run(root);
  assert.equal(result.status, 2); assert.equal(result.data.readyForWork, false); assert.equal(result.data.git.clean, false); assert.deepEqual(result.data.inbox.unprocessedFiles, ['request.txt']); assert.equal(result.data.externalApprovalRequired, false);
});
