import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import test from 'node:test';
import { deflateSync } from 'node:zlib';
import { DatabaseSync } from 'node:sqlite';
import {
  createEditorialMediaStaging, editorialContractPin, editorialRevisionCardIdentity,
  finishEditorialScope, migrateEditorialCardToLatest, promoteEditorialAssets, stageEditorialAsset,
} from '../scripts/editorial-lifecycle.mjs';
import { compileContextPack, migrateContextPackEditorialContract } from '../scripts/structured-memory.mjs';
import { EDITORIAL_CONTRACT, validateEditorialArtifact } from '../scripts/editorial-contract.mjs';

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

test('normal lifecycle CLI stages and promotes assets but rejects supplied finish evidence', (t) => {
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
  const finished = spawnSync(process.execPath, ['scripts/editorial-lifecycle.mjs', 'finish',
    '--staging', staged.staging.root, '--owner-command', 'Заверши задачу.', '--evidence', JSON.stringify(evidence)], {
    cwd: process.cwd(), encoding: 'utf8',
  });
  assert.notEqual(finished.status, 0);
  assert.match(finished.stderr, /finish_evidence_is_not_accepted/);
  const manifest = JSON.parse(readFileSync(join(staged.staging.root, '.editorial-lifecycle.json'), 'utf8'));
  assert.equal(manifest.status, 'promoted_after_qa');
  assert.equal(manifest.finish, undefined);
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

test('real editorial finish blocks stale artifact QA before commit and retries without duplicates', (t) => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'editorial-finish-e2e-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const canonical = join(root, 'canonical'); const worktreeRoot = join(root, 'worktrees');
  const worktree = join(worktreeRoot, 'writer'); mkdirSync(canonical); mkdirSync(worktreeRoot);
  execFileSync('git', ['init', canonical]);
  writeFileSync(join(canonical, 'seed.txt'), 'base\n');
  execFileSync('git', ['-C', canonical, 'add', 'seed.txt']);
  execFileSync('git', ['-C', canonical, '-c', 'user.name=MetricHit Test', '-c', 'user.email=test@local.invalid',
    'commit', '-m', 'base']);
  const base = execFileSync('git', ['-C', canonical, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  const branch = 'codex/test/editorial-finish';
  execFileSync('git', ['-C', canonical, 'worktree', 'add', '-b', branch, worktree, base]);

  const databasePath = join(root, 'memory.sqlite');
  execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
  const article = 'work/articles/drafts/article.md';
  const preview = 'work/articles/assets/preview.png'; const inline = 'work/articles/assets/inline.png';
  const spec = {
    status: 'valid', pre_generation_gate: 'passed', contract_id: EDITORIAL_CONTRACT.id,
    contract_revision: EDITORIAL_CONTRACT.revision, contract_snapshot: structuredClone(EDITORIAL_CONTRACT),
    content_source_format: EDITORIAL_CONTRACT.content_source.format, selected_h1: 'Накрутка ПФ',
    character_range: { minimum: 1, maximum: 1000 }, primary_query: 'Накрутка ПФ', secondary_queries: [],
    lsi: [], links: [], image_package: {
      preview: [{ path: '../assets/preview.png', aspect_ratio: '1:1' }],
      inline: [{ path: '../assets/inline.png', aspect_ratio: '3:2', section_anchor: 'Проверка' }],
    },
  };
  const acceptance = ['real bundle validated', 'retry idempotent']; const firstCheck = 'node --version';
  const compiled = compileContextPack(databasePath, {
    text: 'Исправь завершение реального комплекта', explicitScopeId: 'scope:subproject:editorial', taskType: 'code',
    taskBrief: { result: 'Комплект завершён', scope: [article, preview, inline], firstCheck,
      acceptance, forbiddenChanges: ['publication'], editorialSpec: spec, parentResult: 'owner-e2e' },
  });

  const commonGitDirectory = execFileSync('git', ['rev-parse', '--git-common-dir'], { encoding: 'utf8' }).trim();
  const repository = dirname(resolve(commonGitDirectory));
  const python = join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const pythonEnvironment = { ...process.env, PYTHONPATH: resolve('src') };
  const handoffPayload = {
    idempotency_key: 'editorial-finish-e2e', semantic_key: 'test.editorial.finish-e2e',
    goal: 'Finish one real editorial bundle', scope: [article, preview, inline], constraints: ['no publication'],
    acceptance, source: 'owner test fixture', approved_by: 'owner', execution_resources: {
      canonical_worktree: canonical, worktree, branch, base_head: base,
      paths: [article, preview, inline], sqlite: [], shared: ['editorial_finish_e2e'],
    },
  };
  const handoff = JSON.parse(execFileSync(python, ['-m', 'metrichit_os', 'handoff-create', '--db', databasePath,
    '--data', JSON.stringify(handoffPayload)], { encoding: 'utf8', env: pythonEnvironment }));
  assert.equal(handoff.execution_resources.branch, branch);

  const crc32 = (bytes) => {
    let crc = 0xffffffff;
    for (const byte of bytes) { crc ^= byte; for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0); }
    return (crc ^ 0xffffffff) >>> 0;
  };
  const png = (width, height, pixel = 0) => {
    const chunk = (type, data) => { const header = Buffer.alloc(8); header.writeUInt32BE(data.length, 0); header.write(type, 4);
      const checksum = Buffer.alloc(4); checksum.writeUInt32BE(crc32(Buffer.concat([Buffer.from(type), data])));
      return Buffer.concat([header, data, checksum]); };
    const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
    const rows = Buffer.alloc(height * (1 + width * 3));
    for (let row = 0; row < height; row += 1) { rows[row * (1 + width * 3)] = 0; rows[row * (1 + width * 3) + 1] = pixel; }
    return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
      chunk('IHDR', ihdr), chunk('IDAT', deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
  };
  const articlePath = join(worktree, article); const previewPath = join(worktree, preview); const inlinePath = join(worktree, inline);
  mkdirSync(join(worktree, 'work/articles/drafts'), { recursive: true });
  mkdirSync(join(worktree, 'work/articles/assets'), { recursive: true });
  writeFileSync(articlePath, '# Накрутка ПФ\n![preview](../assets/preview.png)\nПроверка комплекта.\n![inline](../assets/inline.png)\n');
  const previewBytes = png(10, 10); const inlineBytes = png(15, 10);
  writeFileSync(previewPath, previewBytes); writeFileSync(inlinePath, inlineBytes);
  const visualReview = { performed: true, passed: true, reviewer: 'visual-reviewer', result: 'Both current images inspected.',
    assets: [{ path: '../assets/preview.png', sha256: createHash('sha256').update(previewBytes).digest('hex'), passed: true },
      { path: '../assets/inline.png', sha256: createHash('sha256').update(inlineBytes).digest('hex'), passed: true }] };
  const artifactQa = validateEditorialArtifact(spec, { article_path: articlePath, visual_review: visualReview });
  const staging = createEditorialMediaStaging(worktree, 'finish-e2e');
  const staged = [stageEditorialAsset(staging, previewPath, preview), stageEditorialAsset(staging, inlinePath, inline)];
  promoteEditorialAssets(staging, staged, () => artifactQa);

  const state = join(root, 'finish-state.json');
  const finishArgs = ['scripts/editorial-lifecycle.mjs', 'finish', '--staging', staging.root,
    '--owner-command', 'Заверши задачу.', '--worktree', handoff.execution_resources.worktree,
    '--canonical-worktree', handoff.execution_resources.canonical_worktree,
    '--db', databasePath, '--context-pack', compiled.pack.id, '--handoff-id', handoff.handoff_id,
    '--developer', 'editorial-e2e-writer', '--python', python, '--check-argv', JSON.stringify(['node', '--version']),
    '--scope-label', 'Редакция', '--task', 'Editorial finish E2E', '--state', state,
    '--commit-message', 'test: deliver editorial bundle'];
  writeFileSync(inlinePath, png(15, 10, 1));
  const blocked = spawnSync(process.execPath, finishArgs, { cwd: process.cwd(), encoding: 'utf8', env: pythonEnvironment });
  assert.notEqual(blocked.status, 0);
  assert.equal(JSON.parse(readFileSync(state, 'utf8')).blocker.stage, 'artifact_validation');
  assert.equal(execFileSync('git', ['-C', worktree, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), base);
  assert.equal(execFileSync('git', ['-C', canonical, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), base);
  let database = new DatabaseSync(databasePath, { readOnly: true });
  assert.equal(database.prepare('SELECT status FROM context_packs WHERE id=?').get(compiled.pack.id).status, 'open');
  database.close();

  writeFileSync(inlinePath, inlineBytes);
  const delivered = spawnSync(process.execPath, finishArgs, { cwd: process.cwd(), encoding: 'utf8', env: pythonEnvironment });
  assert.equal(delivered.status, 0, delivered.stderr);
  const result = JSON.parse(delivered.stdout); assert.equal(result.status, 'delivered');
  assert.equal(execFileSync('git', ['-C', canonical, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), result.commit);
  const replay = spawnSync(process.execPath, finishArgs, { cwd: process.cwd(), encoding: 'utf8', env: pythonEnvironment });
  assert.equal(replay.status, 0, replay.stderr); assert.equal(JSON.parse(replay.stdout).replayed, true);
  database = new DatabaseSync(databasePath, { readOnly: true });
  assert.equal(database.prepare('SELECT status FROM context_packs WHERE id=?').get(compiled.pack.id).status, 'closed');
  assert.equal(database.prepare("SELECT count(*) count FROM audit_log WHERE type='chat_transition_checkpoint' AND json_extract(data_json,'$.context_pack_id')=?")
    .get(compiled.pack.id).count, 1);
  database.close();
  assert.equal(execFileSync('git', ['-C', canonical, 'rev-list', '--count', `${base}..HEAD`], { encoding: 'utf8' }).trim(), '1');
});
