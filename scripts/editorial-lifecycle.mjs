import { createHash } from 'node:crypto';
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
  staging = null, completedStages = null }) {
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
  const evidence = {};
  for (const [stage, operation] of steps) {
    try {
      const result = completedStages ? completedStages[stage] : await operation(evidence);
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
    const staging = stagingFromRoot(args.staging);
    const completedStages = jsonObject(args.evidence, 'evidence');
    return finishEditorialScope({ owner_command: args['owner-command'], completedStages, staging });
  }
  throw new Error('Usage: editorial-lifecycle.mjs <stage|promote|finish>');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runCli(process.argv.slice(2)).then((result) => console.log(JSON.stringify(result))).catch((error) => {
    console.error(`editorial-lifecycle: ${error.message}`);
    process.exitCode = 1;
  });
}
