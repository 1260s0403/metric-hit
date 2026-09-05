import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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

test('normal lifecycle CLI persists resumable stage, promotion, and finish evidence', (t) => {
  const { active, source } = fixture(t);
  const invoke = (...args) => {
    const result = spawnSync(process.execPath, ['scripts/editorial-lifecycle.mjs', ...args], {
      cwd: process.cwd(), encoding: 'utf8',
    });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  };
  const staged = invoke('stage', '--worktree', active, '--key', 'cli-article', '--source', source,
    '--target', 'work/articles/assets/cli.png');
  const promoted = invoke('promote', '--staging', staged.staging.root,
    '--assets', JSON.stringify([{ target: staged.asset.target, sha256: staged.asset.sha256 }]),
    '--artifact-qa', JSON.stringify({ computed: true, passed: true }));
  assert.equal(promoted.status, 'promoted_after_qa');
  const evidence = Object.fromEntries([
    'artifact_validation', 'commit', 'serialized_integration', 'domain_reconciliation', 'close_card', 'clean_checkpoint',
  ].map((stage) => [stage, { passed: true, stage }]));
  const finished = invoke('finish', '--staging', staged.staging.root, '--owner-command', 'Заверши задачу.',
    '--evidence', JSON.stringify(evidence));
  assert.equal(finished.status, 'delivered');
  const manifest = JSON.parse(readFileSync(join(staged.staging.root, '.editorial-lifecycle.json'), 'utf8'));
  assert.equal(manifest.finish.status, 'delivered');
  assert.equal(manifest.finish.evidence.clean_checkpoint.passed, true);
});

test('asset promotion recovers after an interrupted pending rename without duplicating the asset', (t) => {
  const { active, source } = fixture(t);
  const staging = createEditorialMediaStaging(active, 'recoverable-article');
  const asset = stageEditorialAsset(staging, source, 'work/articles/assets/recoverable.png');
  const finalPath = join(active, asset.target);
  mkdirSync(join(active, 'work/articles/assets'), { recursive: true });
  copyFileSync(asset.staged_path, `${finalPath}.editorial-pending`);
  const recovered = promoteEditorialAssets(staging, [asset], () => ({ computed: true, passed: true }));
  assert.equal(recovered.assets[0].reused, false);
  assert.equal(existsSync(finalPath), true);
  assert.equal(existsSync(`${finalPath}.editorial-pending`), false);
  const replay = promoteEditorialAssets(staging, [asset], () => ({ computed: true, passed: true }));
  assert.equal(replay.assets[0].reused, true);
  assert.equal(readFileSync(finalPath, 'utf8'), 'selected-media');
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
  const retry = compileContextPack(database, { ...request, projectDatabasePath: join(root, 'missing-project.sqlite') });
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
    article_commit: 'abc1234', article_content_sha256: 'content-hash' }, editorial_spec: {
    contract_id: 'contract', contract_revision: 1, contract_snapshot: { id: 'contract', revision: 1 },
    preserved_article_text: 'The article body is not a migration input.' } };
  const migrated = migrateEditorialCardToLatest(card, { article_path: 'work/articles/drafts/a.md', article_commit: 'abc1234',
    article_content_sha256: 'content-hash', latest_contract: { id: 'contract', revision: 2 } });
  assert.equal(migrated.result, card.result);
  assert.equal(migrated.editorial_lifecycle.contract_pin.revision, 2);
  assert.equal(migrated.editorial_lifecycle.contract_snapshot.revision, 2);
  assert.deepEqual(migrated.editorial_lifecycle.contract_migration.from, pin);
  assert.equal(migrated.editorial_lifecycle.contract_migration.to.revision, 2);
  assert.equal(migrated.editorial_spec.contract_revision, 2);
  assert.equal(migrated.editorial_spec.contract_snapshot.revision, 2);
  assert.equal(migrated.editorial_spec.preserved_article_text, card.editorial_spec.preserved_article_text);
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
