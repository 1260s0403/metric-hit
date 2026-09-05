import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import {
  createEditorialMediaStaging, editorialContractPin, editorialRevisionCardIdentity,
  finishEditorialScope, migrateEditorialCardToLatest, promoteEditorialAssets, stageEditorialAsset,
} from '../scripts/editorial-lifecycle.mjs';
import { compileContextPack, migrateContextPackEditorialContract } from '../scripts/structured-memory.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'editorial-p1-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const active = join(root, 'active'); mkdirSync(active);
  const source = join(root, 'generated.png'); writeFileSync(source, 'selected-media');
  return { active, source };
}

test('media remains outside the active worktree until computed P0 artifact QA passes', (t) => {
  const { active, source } = fixture(t);
  const staging = createEditorialMediaStaging(active, 'article-a');
  const asset = stageEditorialAsset(staging, source, 'work/articles/assets/selected.png');
  assert.equal(existsSync(join(active, asset.target)), false);
  assert.throws(() => promoteEditorialAssets(staging, [asset], () => ({ computed: true, passed: false })),
    /artifact_qa/);
  assert.equal(existsSync(join(active, asset.target)), false);
  const promoted = promoteEditorialAssets(staging, [asset], () => ({ computed: true, passed: true }));
  assert.equal(promoted.status, 'promoted_after_qa');
  assert.equal(readFileSync(join(active, asset.target), 'utf8'), 'selected-media');
});

test('revision-card identity is stable for article/action/parent result and distinct otherwise', () => {
  const identity = editorialRevisionCardIdentity({ article: 'work/articles/drafts/a.md', action: 'revision', parent_result: 'pack-1' });
  assert.equal(identity, editorialRevisionCardIdentity({ article: 'work/articles/drafts/a.md', action: 'revision', parent_result: 'pack-1' }));
  assert.notEqual(identity, editorialRevisionCardIdentity({ article: 'work/articles/drafts/b.md', action: 'revision', parent_result: 'pack-1' }));
});

test('retry reuses one open article card with its exact contract pin', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'editorial-card-p1-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const database = join(root, 'memory.sqlite');
  const initialized = spawnSync(process.execPath, ['scripts/init-memory.mjs', database], { encoding: 'utf8' });
  assert.equal(initialized.status, 0, initialized.stderr);
  const request = { text: 'Реализовать статью MetricHit', explicitScopeId: 'scope:subproject:editorial', taskType: 'code',
    taskBrief: { result: 'Одна статья', scope: ['work/articles/drafts/retry-article.md'], firstCheck: 'node --test',
      acceptance: ['одна card'], forbiddenChanges: ['не публиковать'], parentResult: 'owner-result-1' } };
  const first = compileContextPack(database, request);
  const retry = compileContextPack(database, request);
  assert.equal(retry.pack.id, first.pack.id);
  assert.equal(retry.pack.reused, true);
  assert.deepEqual(first.pack.payload.execution_card.editorial_lifecycle.contract_pin, editorialContractPin());
});

test('one-step stored-card migration preserves the article commit and content', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'editorial-migrate-p1-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const database = join(root, 'memory.sqlite');
  const initialized = spawnSync(process.execPath, ['scripts/init-memory.mjs', database], { encoding: 'utf8' });
  assert.equal(initialized.status, 0, initialized.stderr);
  const article = 'work/articles/drafts/2026-08-29-timeweb-cloud-pf-service-selection.md';
  const contentHash = createHash('sha256').update(readFileSync(article)).digest('hex');
  const commit = 'a'.repeat(40);
  const compiled = compileContextPack(database, { text: 'Реализовать статью MetricHit',
    explicitScopeId: 'scope:subproject:editorial', taskType: 'code', taskBrief: { result: 'Одна статья',
      scope: [article], firstCheck: 'node --test', acceptance: ['migrated'], forbiddenChanges: ['не публиковать'],
      parentResult: 'owner-result-migrate', articleCommit: commit } });
  const migrated = migrateContextPackEditorialContract(database, compiled.pack.id, {
    article_path: article, article_commit: commit, article_content_sha256: contentHash,
  });
  assert.equal(migrated.status, 'open');
  assert.equal(migrated.contract_pin.revision, editorialContractPin().revision);
});

test('contract migration changes only the pin when article commit and content are unchanged', () => {
  const pin = editorialContractPin({ id: 'contract', revision: 1 });
  const card = { result: 'article', editorial_lifecycle: { contract_pin: pin, article_path: 'work/articles/drafts/a.md',
    article_commit: 'abc1234', article_content_sha256: 'content-hash' } };
  const migrated = migrateEditorialCardToLatest(card, { article_path: 'work/articles/drafts/a.md', article_commit: 'abc1234',
    article_content_sha256: 'content-hash', latest_contract: { id: 'contract', revision: 2 } });
  assert.equal(migrated.result, card.result);
  assert.equal(migrated.editorial_lifecycle.contract_pin.revision, 2);
  assert.equal(migrated.editorial_lifecycle.contract_snapshot.revision, 2);
  assert.equal(migrated.editorial_lifecycle.migrated_from_revision, 1);
  assert.throws(() => migrateEditorialCardToLatest(card, { article_path: 'work/articles/drafts/a.md', article_commit: 'different',
    article_content_sha256: 'content-hash', latest_contract: { id: 'contract', revision: 2 } }), /article_changed_since_pin/);
});

test('exact owner finish runs the atomic order and returns one concrete blocker', async () => {
  const calls = [];
  const operation = (name) => async () => { calls.push(name); return { passed: true, stage: name }; };
  const delivered = await finishEditorialScope({ owner_command: 'Заверши задачу.', validate: operation('validate'),
    commit: operation('commit'), integrate: operation('integrate'), reconcile: operation('reconcile'),
    close: operation('close'), checkpoint: operation('checkpoint') });
  assert.equal(delivered.status, 'delivered');
  assert.deepEqual(calls, ['validate', 'commit', 'integrate', 'reconcile', 'close', 'checkpoint']);
  const blocked = await finishEditorialScope({ owner_command: 'Заверши задачу.', validate: operation('validate-2'),
    commit: async () => { throw new Error('dirty worktree'); }, integrate: operation('never'),
    reconcile: operation('never'), close: operation('never'), checkpoint: operation('never') });
  assert.deepEqual(blocked.blocker, { stage: 'commit', message: 'dirty worktree' });
});
