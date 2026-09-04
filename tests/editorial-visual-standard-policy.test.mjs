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
  const row = database.prepare("SELECT * FROM memory_candidates WHERE semantic_key='content.editorial_visual_standard' AND status='approved' ORDER BY coalesce(json_extract(data_json, '$.revision'), 1) DESC LIMIT 1").get();
  database.close();
  assert.equal(row.status, 'approved');
  assert.equal(row.type, 'editorial_rule');
  const policy = JSON.parse(row.data_json);
  assert.deepEqual(policy.applies_to, ['articles', 'article_drafts']);
  assert.equal(policy.article_image_brief.total, 3);
  assert.deepEqual(policy.article_image_brief.assets.map((asset) => asset.role),
    ['cover_preview', 'section_business_scene', 'real_screenshot_or_workflow']);
  assert.deepEqual(policy.article_image_brief.assets.map((asset) => asset.oborot_aspect_ratio),
    ['1:1', '3:2_landscape', '16:9_allowed']);
  assert.equal(policy.photography_style.look, 'photorealistic_editorial_lifestyle');
  assert.equal(policy.photography_style.setting, 'credible_russian_business_context_matching_intent');
  assert.ok(policy.requirements.includes('distinct_scenes_within_article'));
  assert.ok(policy.requirements.includes('real_ui_screenshots_or_composites_only'));
  assert.ok(policy.requirements.includes('desktop_mobile_crop_safe_area'));
  assert.ok(policy.requirements.includes('descriptive_filename'));
  assert.ok(policy.requirements.includes('natural_non_stuffed_alt'));
  assert.ok(policy.visual_qa.includes('reject_ai_artifacts'));
  assert.ok(policy.prohibited.includes('abstract_graphite_glass_article_default'));
  assert.ok(policy.prohibited.includes('unlicensed_third_party_imagery'));
  assert.equal(policy.oborot.distortion, 'prohibited');
  assert.equal(policy.oborot.portrait, '3:4_only_when_content_requires');
  assert.deepEqual(policy.owner_approval_required_for, ['global_style_change', 'real_logos', 'external_publication']);
  assert.ok(policy.requirements.includes('visual_inspection_before_delivery'));
  assert.ok(policy.prohibited.includes('ai_hallucinated_ui_or_text'));

  const compiled = compileContextPack(databasePath, { text: 'Напиши новую статью для Oborot.ru',
    projectDatabasePath: join('data', 'projects', '00000000-0000-4000-a000-000000000102', 'project.sqlite'), taskBrief: {
    result: 'Article visual package', scope: ['work/articles'], firstCheck: 'article-check',
    acceptance: ['visual-package-ready'], forbiddenChanges: ['publication'],
  } });
  const compiledRule = compiled.pack.payload.execution_card.mandatory_rules
    .find((rule) => rule.semantic_key === 'content.editorial_visual_standard');
  assert.ok(compiledRule);
  assert.match(compiledRule.content, /ровно три целевых визуала/iu);
  assert.match(compiledRule.content, /превью 1:1/iu);
  assert.match(compiledRule.content, /3:2 landscape/iu);
  assert.match(compiledRule.content, /16:9/iu);
  assert.match(compiledRule.content, /только реальные скриншоты/iu);
});
