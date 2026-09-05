import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { EDITORIAL_CONTRACT } from './editorial-contract.mjs';

const canonical = (value) => JSON.stringify(value);
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const nonEmpty = (value, field) => {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`editorial_lifecycle_invalid:${field}`);
  return value.trim();
};

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
  return Object.freeze({ root, active_worktree: active, status: 'staging' });
}

export function stageEditorialAsset(staging, sourcePath, targetPath) {
  if (!staging?.root || !existsSync(sourcePath)) throw new Error('editorial_lifecycle_invalid:staged_source');
  const target = safeRelative(targetPath, 'asset_target');
  const stagedPath = resolve(staging.root, target);
  mkdirSync(dirname(stagedPath), { recursive: true });
  copyFileSync(sourcePath, stagedPath);
  return { target, staged_path: stagedPath, sha256: sha256(readFileSync(stagedPath)) };
}

export function promoteEditorialAssets(staging, selectedAssets, artifactQa) {
  if (!staging?.root || !Array.isArray(selectedAssets) || !selectedAssets.length) {
    throw new Error('editorial_lifecycle_invalid:selected_assets');
  }
  const qa = artifactQa?.();
  if (!qa?.computed || !qa?.passed) throw new Error('editorial_lifecycle_blocked:artifact_qa');
  const prepared = selectedAssets.map((asset) => {
    const target = safeRelative(asset.target, 'asset_target');
    const source = resolve(staging.root, target);
    if (!existsSync(source)) throw new Error(`editorial_lifecycle_invalid:staged_asset_missing:${target}`);
    const finalPath = resolve(staging.active_worktree, target);
    const pendingPath = `${finalPath}.editorial-pending`;
    if (existsSync(finalPath) || existsSync(pendingPath)) {
      throw new Error(`editorial_lifecycle_blocked:asset_target_exists:${target}`);
    }
    return { target, source, finalPath, pendingPath };
  });
  const promoted = [];
  try {
    for (const asset of prepared) {
      mkdirSync(dirname(asset.finalPath), { recursive: true });
      copyFileSync(asset.source, asset.pendingPath);
    }
    for (const asset of prepared) {
      renameSync(asset.pendingPath, asset.finalPath);
      promoted.push({ path: asset.target, sha256: sha256(readFileSync(asset.finalPath)) });
    }
  } catch (error) {
    for (const asset of prepared) if (existsSync(asset.pendingPath)) rmSync(asset.pendingPath, { force: true });
    throw error;
  }
  rmSync(staging.root, { recursive: true, force: true });
  return { status: 'promoted_after_qa', assets: promoted, artifact_qa: qa };
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
  return { ...card, editorial_lifecycle: { ...lifecycle, contract_pin: editorialContractPin(latest_contract),
    contract_snapshot: structuredClone(latest_contract),
    migrated_from_revision: lifecycle.contract_pin.revision, migrated_at: new Date().toISOString() } };
}

export async function finishEditorialScope({ owner_command, validate, commit, integrate, reconcile, close, checkpoint }) {
  if (owner_command !== 'Заверши задачу.') throw new Error('editorial_finish_blocked:owner_command');
  const steps = [
    ['artifact_validation', validate], ['commit', commit], ['serialized_integration', integrate],
    ['domain_reconciliation', reconcile], ['close_card', close], ['clean_checkpoint', checkpoint],
  ];
  const evidence = {};
  for (const [stage, operation] of steps) {
    try {
      const result = await operation(evidence);
      if (!result || result.passed === false || result.status === 'blocked') throw new Error(result?.blocker ?? 'stage_failed');
      evidence[stage] = result;
    } catch (error) {
      return { status: 'blocked', blocker: { stage, message: error.message }, evidence };
    }
  }
  return { status: 'delivered', order: steps.map(([stage]) => stage), evidence };
}
