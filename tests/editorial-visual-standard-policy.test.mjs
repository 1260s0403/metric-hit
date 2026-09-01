import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyEditorialVisualStandardPolicy } from '../scripts/apply-editorial-visual-standard-policy.mjs';
import { compileContextPack } from '../scripts/structured-memory.mjs';

test('editorial visual standard is approved, idempotent, and encodes the default three-image article package', (t) => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-editorial-visual-standard-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const databasePath = join(directory, 'metrichit.db');
  cpSync('data/database/metrichit.db', databasePath);

  const first = applyEditorialVisualStandardPolicy(databasePath);
  const second = applyEditorialVisualStandardPolicy(databasePath);
  assert.ok([0, 1].includes(first.created.candidates));
  assert.equal(second.created.candidates, 0);

  const database = new DatabaseSync(databasePath, { readOnly: true });
  const row = database.prepare("SELECT * FROM memory_candidates WHERE semantic_key='content.editorial_visual_standard'").get();
  database.close();
  assert.equal(row.status, 'approved');
  assert.equal(row.type, 'editorial_rule');
  const policy = JSON.parse(row.data_json);
  assert.deepEqual(policy.applies_to, ['articles', 'article_drafts']);
  assert.deepEqual(policy.default_visual_package, { cover: 1, supporting_visuals: 2, total: 3, opt_out: 'explicit_owner_instruction' });
  assert.deepEqual(policy.owner_approval_required_for, ['global_style_change', 'real_photography', 'real_logos', 'external_publication']);
  assert.ok(policy.requirements.includes('visual_inspection_before_delivery'));
  assert.ok(policy.prohibited.includes('ui_screenshots'));

  const compiled = compileContextPack(databasePath, { text: 'Подготовь статью о накрутке ПФ для интернет-магазина', taskBrief: {
    result: 'Article visual package', scope: ['work/articles'], firstCheck: 'article-check',
    acceptance: ['visual-package-ready'], forbiddenChanges: ['publication'],
  } });
  assert.ok(compiled.pack.payload.execution_card.mandatory_rules
    .some((rule) => rule.semantic_key === 'content.editorial_visual_standard'));
});
