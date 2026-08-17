import assert from 'node:assert/strict';
import test from 'node:test';
import { collectWorkspaceStatus, formatWorkspaceStatus } from '../scripts/workspace-status.mjs';

test('workspace status reports the local work contours without file contents', () => {
  const status = collectWorkspaceStatus();
  const output = formatWorkspaceStatus(status);
  assert.equal(typeof status.git.clean, 'boolean');
  assert.equal(status.inboxUnprocessed, 0);
  assert.equal(status.memory.valid, true);
  assert.equal(status.memory.pendingCandidates, 0);
  assert.equal(status.memory.openConflicts, 0);
  assert.equal(status.memory.openTasks, 14);
  assert.equal(typeof status.contours['articles/drafts'], 'number');
  assert.ok(status.contours['articles/drafts'] >= 1, 'editorial drafts are allowed');
  assert.match(output, /Work materials:/);
  assert.match(output, /Unprocessed work\/inbox files: 0/);
  assert.doesNotMatch(output, /MetricHit OS — правила работы/);
});
