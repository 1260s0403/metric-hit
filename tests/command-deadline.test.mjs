import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import test from 'node:test';

const cli = resolve('scripts/command-deadline.mjs');
const run = (seconds, delay) => spawnSync(process.execPath, [cli, String(seconds), '--', process.execPath, '--eval', `setTimeout(() => {}, ${delay})`], { timeout: 5000 });
test('command deadline allows a short command', () => assert.equal(run(1, 20).status, 0));
test('command deadline returns 124 after timeout', () => assert.equal(run(0.05, 500).status, 124));
