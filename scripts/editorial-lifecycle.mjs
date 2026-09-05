import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { EDITORIAL_CONTRACT } from './editorial-contract.mjs';

const canonical = (value) => JSON.stringify(value);
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const nonEmpty = (value, field) => {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`editorial_lifecycle_invalid:${field}`);
  return value.trim();
};
const manifestName = '.editorial-lifecycle.json';

function manifestPath(staging) { return join(staging.root, manifestName); }
function readManifest(staging) {
  if (!staging?.root || !existsSync(manifestPath(staging))) throw new Error('editorial_lifecycle_invalid:staging_manifest');
  try { return JSON.parse(readFileSync(manifestPath(staging), 'utf8')); }
  catch { throw new Error('editorial_lifecycle_invalid:staging_manifest'); }
}
function writeManifest(staging, manifest) {
  writeFileSync(manifestPath(staging), JSON.stringify(manifest));
  return manifest;
}

function stagingFromRoot(root) {
  const stagingRoot = resolve(nonEmpty(root, 'staging'));
  const manifest = readManifest({ root: stagingRoot });
  return { root: stagingRoot, active_worktree: manifest.active_worktree, status: manifest.status };
}

export function editorialContractPin(contract = EDITORIAL_CONTRACT) {
  return Object.freeze({ id: contract.id, revision: contract.revision, sha256: sha256(canonical(contract)) });
}

export function editorialRevisionCardIdentity({ article, action, parent_result }) {
  return sha256(canonical({
    article: nonEmpty(article, 'article'),
    action: nonEmpty(action, 'action'),
    parent_result: nonEmpty(parent_result, 'parent_result'),
  }));
}

function safeRelative(path, field) {
  const value = nonEmpty(path, field).replaceAll('\\', '/');
  if (isAbsolute(value) || value.split('/').some((part) => !part || part === '.' || part === '..')) {
    throw new Error(`editorial_lifecycle_invalid:${field}`);
  }
  return value;
}

export function createEditorialMediaStaging(activeWorktree, key = 'asset') {
  const active = resolve(nonEmpty(activeWorktree, 'active_worktree'));
  const root = mkdtempSync(join(tmpdir(), `metrichit-editorial-${sha256(key).slice(0, 10)}-`));
  if (!relative(active, root).startsWith('..')) throw new Error('editorial_lifecycle_invalid:staging_inside_active_worktree');
  const staging = { root, active_worktree: active, status: 'staging' };
  writeManifest(staging, { schema_version: 1, active_worktree: active, key: String(key), status: 'staging', assets: [] });
  return Object.freeze(staging);
}

export function stageEditorialAsset(staging, sourcePath, targetPath) {
  if (!staging?.root || !existsSync(sourcePath)) throw new Error('editorial_lifecycle_invalid:staged_source');
  const target = safeRelative(targetPath, 'asset_target');
  const stagedPath = resolve(staging.root, target);
  mkdirSync(dirname(stagedPath), { recursive: true });
  copyFileSync(sourcePath, stagedPath);
  const asset = { target, staged_path: stagedPath, sha256: sha256(readFileSync(stagedPath)) };
  const manifest = readManifest(staging);
  const previous = manifest.assets.findIndex((item) => item.target === target);
  if (previous >= 0 && manifest.assets[previous].sha256 !== asset.sha256) throw new Error(`editorial_lifecycle_blocked:asset_target_changed:${target}`);
  if (previous < 0) manifest.assets.push({ target, sha256: asset.sha256, status: 'staged' });
  writeManifest(staging, manifest);
  return asset;
}

export function promoteEditorialAssets(staging, selectedAssets, artifactQa) {
  if (!staging?.root || !Array.isArray(selectedAssets) || !selectedAssets.length) {
    throw new Error('editorial_lifecycle_invalid:selected_assets');
  }
  const qa = artifactQa?.();
  if (!qa?.computed || !qa?.passed) throw new Error('editorial_lifecycle_blocked:artifact_qa');
  const manifest = readManifest(staging);
  const prepared = selectedAssets.map((asset) => {
    const target = safeRelative(asset.target, 'asset_target');
    const source = resolve(staging.root, target);
    const recorded = manifest.assets.find((item) => item.target === target);
    if (!recorded || recorded.sha256 !== asset.sha256) throw new Error(`editorial_lifecycle_invalid:staged_asset_manifest:${target}`);
    if (!existsSync(source)) throw new Error(`editorial_lifecycle_invalid:staged_asset_missing:${target}`);
    const finalPath = resolve(staging.active_worktree, target);
    const pendingPath = `${finalPath}.editorial-pending`;
    return { target, source, finalPath, pendingPath, sha256: asset.sha256, recorded };
  });
  const promoted = [];
  try {
    for (const asset of prepared) {
      if (existsSync(asset.finalPath)) {
        if (sha256(readFileSync(asset.finalPath)) !== asset.sha256) throw new Error(`editorial_lifecycle_blocked:asset_target_changed:${asset.target}`);
        asset.recorded.status = 'promoted';
        promoted.push({ path: asset.target, sha256: asset.sha256, reused: true });
        continue;
      }
      mkdirSync(dirname(asset.finalPath), { recursive: true });
      if (existsSync(asset.pendingPath) && sha256(readFileSync(asset.pendingPath)) !== asset.sha256) {
        throw new Error(`editorial_lifecycle_blocked:asset_pending_changed:${asset.target}`);
      }
      if (!existsSync(asset.pendingPath)) copyFileSync(asset.source, asset.pendingPath);
      asset.recorded.status = 'pending';
      writeManifest(staging, manifest);
    }
    for (const asset of prepared) {
      if (existsSync(asset.finalPath)) continue;
      renameSync(asset.pendingPath, asset.finalPath);
      asset.recorded.status = 'promoted';
      promoted.push({ path: asset.target, sha256: asset.sha256, reused: false });
      writeManifest(staging, manifest);
    }
  } catch (error) {
    writeManifest(staging, manifest);
    throw error;
  }
  manifest.status = 'promoted_after_qa'; writeManifest(staging, manifest);
  return { status: 'promoted_after_qa', assets: promoted, artifact_qa: qa, staging_manifest: manifestPath(staging) };
}

export function migrateEditorialCardToLatest(card, {
  article_path, article_commit, article_content_sha256, latest_contract = EDITORIAL_CONTRACT,
}) {
  if (!card?.editorial_lifecycle?.contract_pin) throw new Error('editorial_lifecycle_invalid:contract_pin_missing');
  const lifecycle = card.editorial_lifecycle;
  if (lifecycle.article_path !== article_path || lifecycle.article_commit !== article_commit
    || lifecycle.article_content_sha256 !== article_content_sha256) {
    throw new Error('editorial_lifecycle_blocked:article_changed_since_pin');
  }
  const nextPin = editorialContractPin(latest_contract);
  const priorPin = lifecycle.contract_pin;
  const nextSpec = card.editorial_spec ? { ...card.editorial_spec, contract_id: nextPin.id,
    contract_revision: nextPin.revision, contract_snapshot: structuredClone(latest_contract) } : null;
  return { ...card, ...(nextSpec ? { editorial_spec: nextSpec } : {}), editorial_lifecycle: { ...lifecycle,
    contract_pin: nextPin, contract_snapshot: structuredClone(latest_contract),
    contract_migration: { from: priorPin, to: nextPin, article_path, article_commit, article_content_sha256 } } };
}

export async function finishEditorialScope({ owner_command, validate, commit, integrate, reconcile, close, checkpoint,
  staging = null }) {
  if (owner_command !== 'Заверши задачу.') throw new Error('editorial_finish_blocked:owner_command');
  if (staging && readManifest(staging).status !== 'promoted_after_qa') {
    const blocker = { stage: 'artifact_validation', message: 'editorial_lifecycle_blocked:assets_not_promoted' };
    const manifest = readManifest(staging);
    manifest.finish = { owner_command, status: 'blocked', blocker, evidence: {} };
    writeManifest(staging, manifest);
    return { status: 'blocked', blocker, evidence: {} };
  }
  const steps = [
    ['artifact_validation', validate], ['commit', commit], ['serialized_integration', integrate],
    ['domain_reconciliation', reconcile], ['close_card', close], ['clean_checkpoint', checkpoint],
  ];
  const evidence = staging ? { ...(readManifest(staging).finish?.evidence ?? {}) } : {};
  for (const [stage, operation] of steps) {
    try {
      const result = evidence[stage] ?? await operation(evidence);
      if (!result || result.passed === false || result.status === 'blocked') throw new Error(result?.blocker ?? 'stage_failed');
      evidence[stage] = result;
      if (staging) {
        const manifest = readManifest(staging);
        manifest.finish = { owner_command, status: 'in_progress', evidence };
        writeManifest(staging, manifest);
      }
    } catch (error) {
      if (staging) {
        const manifest = readManifest(staging);
        manifest.finish = { owner_command, status: 'blocked', blocker: { stage, message: error.message }, evidence };
        writeManifest(staging, manifest);
      }
      return { status: 'blocked', blocker: { stage, message: error.message }, evidence };
    }
  }
  if (staging) {
    const manifest = readManifest(staging);
    manifest.finish = { owner_command, status: 'delivered', evidence };
    writeManifest(staging, manifest);
  }
  return { status: 'delivered', order: steps.map(([stage]) => stage), evidence };
}

function run(command, args, cwd) {
  return execFileSync(command, args, { cwd, encoding: 'utf8', windowsHide: true }).trim();
}
function runJson(command, args, cwd) {
  const output = run(command, args, cwd);
  try { return JSON.parse(output); } catch { throw new Error(`editorial_lifecycle_invalid:non_json_operation:${command}`); }
}
function git(cwd, ...args) { return run('git', args, cwd); }
function jsonArray(value, field) {
  try {
    const parsed = JSON.parse(nonEmpty(value, field));
    if (!Array.isArray(parsed) || !parsed.length || parsed.some((item) => typeof item !== 'string' || !item.trim())) throw new Error();
    return parsed.map((item) => item.trim());
  } catch { throw new Error(`editorial_lifecycle_invalid:${field}`); }
}
function stateFor(path, identity) {
  if (!existsSync(path)) return { schema_version: 1, ...identity, status: 'in_progress', evidence: {} };
  let state;
  try { state = JSON.parse(readFileSync(path, 'utf8')); } catch { throw new Error('editorial_lifecycle_invalid:finish_state'); }
  if (state.schema_version !== 1 || Object.entries(identity).some(([key, value]) => state[key] !== value)
    || !state.evidence || typeof state.evidence !== 'object') throw new Error('editorial_lifecycle_invalid:finish_state_identity');
  return state;
}
function persistState(path, state) {
  mkdirSync(dirname(path), { recursive: true });
  const pending = `${path}.pending`;
  writeFileSync(pending, JSON.stringify(state)); renameSync(pending, path);
}
function changedPaths(worktree) {
  const tracked = git(worktree, 'diff', '--name-only').split(/\r?\n/u).filter(Boolean);
  const staged = git(worktree, 'diff', '--cached', '--name-only').split(/\r?\n/u).filter(Boolean);
  const untracked = git(worktree, 'ls-files', '--others', '--exclude-standard').split(/\r?\n/u).filter(Boolean);
  return [...new Set([...tracked, ...staged, ...untracked].map((path) => path.replaceAll('\\', '/')))].sort();
}
async function storedExecutionCard(databasePath, packId) {
  const { DatabaseSync } = await import('node:sqlite');
  const database = new DatabaseSync(resolve(databasePath), { readOnly: true });
  try {
    const row = database.prepare('SELECT status,payload_json FROM context_packs WHERE id=?').get(packId);
    if (!row) throw new Error('editorial_lifecycle_invalid:context_pack');
    const payload = JSON.parse(row.payload_json); const card = payload.execution_card;
    if (!card?.result || !Array.isArray(card.scope) || !card.first_check || !Array.isArray(card.acceptance)) {
      throw new Error('editorial_lifecycle_invalid:execution_card');
    }
    return { status: row.status, terminal_outcome: payload.terminal_outcome ?? null, card };
  } finally { database.close(); }
}
async function storedCheckpoint(databasePath, expected) {
  const { DatabaseSync } = await import('node:sqlite');
  const database = new DatabaseSync(resolve(databasePath), { readOnly: true });
  try {
    const rows = database.prepare(`SELECT data_json FROM audit_log
      WHERE type='chat_transition_checkpoint' AND json_extract(data_json,'$.context_pack_id')=?
        AND json_extract(data_json,'$.branch')=? AND json_extract(data_json,'$.canonical_worktree')=?
        AND json_extract(data_json,'$.execution_worktree')=? AND json_extract(data_json,'$.head')=?
      ORDER BY created_at DESC,id DESC`).all(expected.context_pack_id, expected.branch,
      expected.canonical_worktree, expected.execution_worktree, expected.head);
    return rows.length ? { ...JSON.parse(rows[0].data_json), matching_records: rows.length } : null;
  } finally { database.close(); }
}

async function finishEditorialCli(args) {
  if (args.evidence !== undefined) throw new Error('editorial_lifecycle_invalid:finish_evidence_is_not_accepted');
  if (args['owner-command'] !== 'Заверши задачу.') throw new Error('editorial_finish_blocked:owner_command');
  const worktree = resolve(nonEmpty(args.worktree, 'worktree'));
  const canonicalWorktree = resolve(nonEmpty(args['canonical-worktree'], 'canonical_worktree'));
  const databasePath = resolve(nonEmpty(args.db, 'db'));
  const packId = nonEmpty(args['context-pack'], 'context_pack');
  const handoffId = nonEmpty(args['handoff-id'], 'handoff_id');
  const developer = nonEmpty(args.developer, 'developer');
  const python = resolve(nonEmpty(args.python, 'python'));
  const checkArgv = jsonArray(args['check-argv'], 'check_argv');
  const scopeLabel = nonEmpty(args['scope-label'], 'scope_label');
  const task = nonEmpty(args.task, 'task');
  const statePath = resolve(args.state ?? join(tmpdir(), `metrichit-editorial-finish-${handoffId}.json`));
  if (!relative(worktree, statePath).startsWith('..') || !relative(canonicalWorktree, statePath).startsWith('..')) {
    throw new Error('editorial_lifecycle_invalid:finish_state_inside_worktree');
  }
  if (args.staging && readManifest(stagingFromRoot(args.staging)).status !== 'promoted_after_qa') {
    throw new Error('editorial_lifecycle_blocked:assets_not_promoted');
  }
  const identity = { handoff_id: handoffId, context_pack_id: packId, worktree, canonical_worktree: canonicalWorktree };
  const state = stateFor(statePath, identity);
  const wasDelivered = state.status === 'delivered';
  const stored = await storedExecutionCard(databasePath, packId);
  let declared = state.execution_resources;
  if (!state.evidence.commit) {
    const handoff = runJson(python, ['-m', 'metrichit_os', 'handoff-claim', '--db', databasePath,
      '--id', handoffId, '--developer', developer], worktree);
    if (!handoff || handoff.handoff_id !== handoffId || handoff.lifecycle?.claimed_by !== developer
      || handoff.status !== 'in_progress') throw new Error('editorial_lifecycle_blocked:claimed_handoff_not_active');
    declared = handoff.execution_resources;
    if (!declared || resolve(declared.worktree) !== worktree || resolve(declared.canonical_worktree) !== canonicalWorktree
      || declared.branch !== git(worktree, 'branch', '--show-current')) throw new Error('editorial_lifecycle_blocked:handoff_resource_mismatch');
    state.execution_resources = declared;
    persistState(statePath, state);
  } else if (!declared) {
    throw new Error('editorial_lifecycle_invalid:finish_state_resources');
  }
  if (resolve(declared.worktree) !== worktree || resolve(declared.canonical_worktree) !== canonicalWorktree
    || declared.branch !== git(worktree, 'branch', '--show-current')) {
    throw new Error('editorial_lifecycle_blocked:finish_state_resource_mismatch');
  }
  const perform = async (stage, operation, verify = null) => {
    if (state.evidence[stage]) {
      if (verify) await verify(state.evidence[stage]);
      return state.evidence[stage];
    }
    try {
      const evidence = await operation();
      if (!evidence || evidence.passed === false || evidence.status === 'blocked') throw new Error(evidence?.blocker ?? 'stage_failed');
      state.evidence[stage] = evidence; state.status = 'in_progress'; delete state.blocker; persistState(statePath, state);
      return evidence;
    } catch (error) {
      state.status = 'blocked'; state.blocker = { stage, message: error.message }; persistState(statePath, state); throw error;
    }
  };
  const runFirstCheck = async () => {
    if (checkArgv.join(' ') !== stored.card.first_check) throw new Error('editorial_lifecycle_blocked:first_check_mismatch');
    run(checkArgv[0], checkArgv.slice(1), worktree);
    return { passed: true, command: stored.card.first_check };
  };
  await perform('artifact_validation', runFirstCheck, runFirstCheck);
  const verifyCommit = async (evidence) => {
    if (!evidence || !/^[0-9a-f]{40,64}$/u.test(evidence.commit)) throw new Error('editorial_lifecycle_invalid:commit_evidence');
    if (git(worktree, 'rev-parse', 'HEAD') !== evidence.commit || git(worktree, 'status', '--short')) {
      throw new Error('editorial_lifecycle_blocked:commit_state_mismatch');
    }
    if (git(worktree, 'rev-parse', `${evidence.commit}^`) !== declared.base_head) {
      throw new Error('editorial_lifecycle_blocked:commit_parent_mismatch');
    }
    const actualPaths = git(worktree, 'diff-tree', '--no-commit-id', '--name-only', '-r', evidence.commit)
      .split(/\r?\n/u).filter(Boolean).map((path) => path.replaceAll('\\', '/')).sort();
    const allowed = new Set(stored.card.scope.map((path) => path.replaceAll('\\', '/')));
    if (!actualPaths.length || actualPaths.some((path) => !allowed.has(path))
      || JSON.stringify(actualPaths) !== JSON.stringify([...(evidence.paths ?? [])].sort())) {
      throw new Error('editorial_lifecycle_blocked:commit_scope_mismatch');
    }
  };
  const commitEvidence = await perform('commit', async () => {
    const paths = changedPaths(worktree); const allowed = new Set(stored.card.scope.map((path) => path.replaceAll('\\', '/')));
    if (!paths.length) throw new Error('editorial_lifecycle_blocked:no_changes_to_commit');
    const outside = paths.filter((path) => !allowed.has(path));
    if (outside.length) throw new Error(`editorial_lifecycle_blocked:scope_drift:${outside.join(',')}`);
    git(worktree, 'add', '--', ...paths); git(worktree, 'diff', '--cached', '--check');
    run('git', ['-c', 'user.name=MetricHit Automation', '-c', 'user.email=metrichit@local.invalid',
      'commit', '-m', nonEmpty(args['commit-message'], 'commit_message')], worktree);
    const commit = git(worktree, 'rev-parse', 'HEAD');
    if (git(worktree, 'status', '--short')) throw new Error('editorial_lifecycle_blocked:worktree_not_clean_after_commit');
    return { passed: true, commit, paths };
  }, verifyCommit);
  const completeHandoff = () => runJson(python, ['-m', 'metrichit_os', 'handoff-complete', '--db', databasePath,
    '--id', handoffId, '--developer', developer, '--commit', commitEvidence.commit], worktree);
  const verifyIntegration = async () => {
    if (git(canonicalWorktree, 'rev-parse', 'HEAD') !== commitEvidence.commit) {
      throw new Error('editorial_lifecycle_blocked:integration_head');
    }
    const handoff = completeHandoff();
    if (handoff.status !== 'completed' || handoff.lifecycle?.commit_hash !== commitEvidence.commit) {
      throw new Error('editorial_lifecycle_blocked:handoff_not_completed');
    }
  };
  await perform('serialized_integration', async () => {
    const currentBase = git(canonicalWorktree, 'rev-parse', 'HEAD');
    if (currentBase !== commitEvidence.commit && currentBase !== declared.base_head) {
      throw new Error(`editorial_lifecycle_blocked:stale_base:${currentBase}`);
    }
    if (currentBase !== commitEvidence.commit) {
      runJson(python, ['-m', 'metrichit_os', 'handoff-integrate', '--db', databasePath, '--id', handoffId,
        '--developer', developer, '--expected-base', declared.base_head, '--current-base', currentBase, '--conflict-free'], worktree);
      git(canonicalWorktree, 'merge', '--ff-only', commitEvidence.commit);
    }
    await verifyIntegration();
    return { passed: true, commit: commitEvidence.commit, mode: currentBase === commitEvidence.commit ? 'already_integrated' : 'fast_forward' };
  }, verifyIntegration);
  await perform('domain_reconciliation', async () => ({ passed: true, status: 'not_applicable_to_code_delivery' }));
  const verifyClosedCard = async () => {
    const current = await storedExecutionCard(databasePath, packId);
    if (current.status !== 'closed' || current.terminal_outcome !== 'delivered') {
      throw new Error('editorial_lifecycle_blocked:context_pack_not_delivered');
    }
  };
  await perform('close_card', async () => {
    const { closeContextPack } = await import('./structured-memory.mjs');
    const closed = closeContextPack(databasePath, packId, { result: stored.card.result, checks: [stored.card.first_check],
      satisfiedAcceptance: stored.card.acceptance, scopeCompliance: true, forbiddenChangesObserved: [] });
    if (closed.status !== 'closed' || closed.terminal_outcome !== 'delivered') throw new Error('editorial_lifecycle_blocked:context_pack_not_delivered');
    return { passed: true, id: packId, changed: closed.changed, terminal_outcome: closed.terminal_outcome };
  }, verifyClosedCard);
  const checkpointIdentity = { context_pack_id: packId, branch: declared.branch, canonical_worktree: canonicalWorktree,
    execution_worktree: worktree, head: commitEvidence.commit };
  const verifyCheckpoint = async () => {
    const existing = await storedCheckpoint(databasePath, checkpointIdentity);
    if (!existing || existing.matching_records !== 1) throw new Error('editorial_lifecycle_blocked:checkpoint_evidence');
    return existing;
  };
  const checkpoint = await perform('clean_checkpoint', async () => {
    const existing = await storedCheckpoint(databasePath, checkpointIdentity);
    if (existing) return { passed: true, status: 'ready_for_new_chat', copy_command: existing.continuation_command,
      head: existing.head, reused: true };
    const result = runJson(python, ['-m', 'metrichit_os', 'chat-finish', '--db', databasePath, '--scope', scopeLabel,
      '--branch', declared.branch, '--canonical-worktree', canonicalWorktree, '--worktree', worktree,
      '--head', commitEvidence.commit, '--context-pack', packId, '--task', task], worktree);
    if (result.status !== 'ready_for_new_chat') throw new Error('editorial_lifecycle_blocked:checkpoint');
    return { passed: true, status: result.status, copy_command: result.copy_command, head: result.checkpoint?.head ?? commitEvidence.commit };
  }, verifyCheckpoint);
  const result = { status: 'delivered', order: ['artifact_validation', 'commit', 'serialized_integration',
    'domain_reconciliation', 'close_card', 'clean_checkpoint'], evidence: state.evidence,
    commit: commitEvidence.commit, copy_command: checkpoint.copy_command, state: statePath };
  state.status = 'delivered'; state.result = result; persistState(statePath, state);
  return wasDelivered ? { ...result, replayed: true } : result;
}

function cliArguments(argv) {
  const result = { _: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) { result._.push(token); continue; }
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`editorial_lifecycle_invalid:argument_${key}`);
    result[key] = value;
    index += 1;
  }
  return result;
}

function jsonObject(value, field) {
  try {
    const parsed = JSON.parse(nonEmpty(value, field));
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error();
    return parsed;
  } catch { throw new Error(`editorial_lifecycle_invalid:${field}`); }
}

async function runCli(argv) {
  const args = cliArguments(argv);
  const command = args._[0];
  if (command === 'stage') {
    const staging = args.staging ? stagingFromRoot(args.staging) : createEditorialMediaStaging(args.worktree, args.key);
    const asset = stageEditorialAsset(staging, nonEmpty(args.source, 'source'), nonEmpty(args.target, 'target'));
    return { staging, asset };
  }
  if (command === 'promote') {
    const staging = stagingFromRoot(args.staging);
    const assets = JSON.parse(nonEmpty(args.assets, 'assets'));
    if (!Array.isArray(assets)) throw new Error('editorial_lifecycle_invalid:assets');
    const artifactQa = jsonObject(args['artifact-qa'], 'artifact_qa');
    return promoteEditorialAssets(staging, assets, () => artifactQa);
  }
  if (command === 'finish') {
    return finishEditorialCli(args);
  }
  throw new Error('Usage: editorial-lifecycle.mjs <stage|promote|finish>');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runCli(process.argv.slice(2)).then((result) => console.log(JSON.stringify(result))).catch((error) => {
    console.error(`editorial-lifecycle: ${error.message}`);
    process.exitCode = 1;
  });
}
