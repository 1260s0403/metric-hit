import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyEditorialVisualStandardPolicy } from '../scripts/apply-editorial-visual-standard-policy.mjs';
import { compileContextPack } from '../scripts/structured-memory.mjs';

test('editorial visual standard is approved, idempotent, and encodes default and Oborot long-form packages', (t) => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-editorial-visual-standard-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const databasePath = join(directory, 'metrichit.db');
  const source = new DatabaseSync(process.env.METRICHIT_TEST_DATABASE ?? 'data/database/metrichit.db', { readOnly: true });
  source.exec(`VACUUM INTO '${databasePath.replaceAll("'", "''")}'`);
  source.close();

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
  assert.equal(policy.oborot_long_form_image_brief.classifier.source_semantic_key, 'content.editorial_target_query_volume_ladder');
  assert.equal(policy.oborot_long_form_image_brief.classifier.band, 'highest_or_above');
  assert.equal(policy.oborot_long_form_image_brief.classifier.minimum_characters, 7001);
  assert.equal(policy.oborot_long_form_image_brief.classifier.upper_band_maximum_characters, 9000);
  assert.equal(policy.oborot_long_form_image_brief.preview.count, 1);
  assert.equal(policy.oborot_long_form_image_brief.inline.count, 3);
  assert.equal(policy.oborot_long_form_image_brief.total, 4);
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
    projectDatabasePath: process.env.METRICHIT_TEST_PROJECT_DATABASE
      ?? join('data', 'projects', '00000000-0000-4000-a000-000000000102', 'project.sqlite'), taskBrief: {
    result: 'Article visual package', scope: ['work/articles'], firstCheck: 'article-check',
    acceptance: ['visual-package-ready'], forbiddenChanges: ['publication'],
  } });
  const compiledRule = compiled.pack.payload.execution_card.mandatory_rules
    .find((rule) => rule.semantic_key === 'content.editorial_visual_standard');
  assert.ok(compiledRule);
  assert.match(compiledRule.content, /ровно три целевых визуала/iu);
  assert.match(compiledRule.content, /от 7 001 знака.*ровно четыре визуала/iu);
  assert.equal(compiled.pack.payload.execution_card.editorial_visual_package.long_form.total, 4);
  assert.equal(compiled.pack.payload.execution_card.editorial_visual_package.long_form.inline.count, 3);
  assert.match(compiledRule.content, /превью 1:1/iu);
  assert.match(compiledRule.content, /3:2 landscape/iu);
  assert.match(compiledRule.content, /16:9/iu);
  assert.match(compiledRule.content, /только реальные скриншоты/iu);

  const databaseForRevision = new DatabaseSync(databasePath);
  const sourcePayload = JSON.stringify({ terminal_outcome: 'delivered', execution_card: {
    scope: ['work/articles/drafts/2026-09-04-oborot-example.md'],
    editorial_semantics: { selected_clusters: ['behavioral_factors_general'], adjacent_cluster_rationale: null,
      primary_target_query: 'накрутка поведенческих факторов', secondary_target_queries: [],
      user_intent: 'Один интент.', platform: 'Oborot.ru', format: 'article' },
    editorial_indexation: { seo_indexation_objective: 'Индексация Яндекс.' },
  } });
  databaseForRevision.prepare(`INSERT INTO context_packs
    (id,scope_id,task_type,compiler_version,input_hash,payload_json,compiled_bytes,status,created_at,closed_at)
    VALUES ('20000000-0000-4000-a000-000000000001','scope:subproject:editorial','editorial',8,?,?,?,'closed',?,?)`)
    .run('a'.repeat(64), sourcePayload, Buffer.byteLength(sourcePayload), '2026-09-04T00:00:00.000Z', '2026-09-04T00:01:00.000Z');
  databaseForRevision.close();
  const revision = compileContextPack(databasePath, {
    text: 'Для последней статьи Оборота создай новые картинки по новым правилам.',
    projectDatabasePath: process.env.METRICHIT_TEST_PROJECT_DATABASE
      ?? join('data', 'projects', '00000000-0000-4000-a000-000000000102', 'project.sqlite'),
  });
  assert.ok(revision.pack.payload.execution_card.editorial_revision.source_context_pack_id);
  assert.equal(revision.pack.payload.execution_card.editorial_visual_package.long_form.total, 4);
  assert.equal(revision.pack.payload.execution_card.editorial_visual_package.long_form.inline.count, 3);
});
