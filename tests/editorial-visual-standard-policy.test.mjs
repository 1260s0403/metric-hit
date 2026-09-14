import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { applyEditorialVisualStandardPolicy, buildEditorialVisualPrompts,
  validateEditorialVisualPlan } from '../scripts/apply-editorial-visual-standard-policy.mjs';
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
  assert.equal(policy.telegram_social_card_brief.aspect_ratio, '1:1');
  assert.equal(policy.telegram_social_card_brief.semantic_focus, 'one_abstract_metaphor_for_one_post_principle');
  assert.ok(policy.telegram_social_card_brief.prohibited.includes('arrows'));
  assert.ok(policy.telegram_social_card_brief.prohibited.includes('ui'));
  assert.equal(policy.oborot_long_form_image_brief.classifier.source_semantic_key, 'content.editorial_target_query_volume_ladder');
  assert.equal(policy.oborot_long_form_image_brief.classifier.band, 'highest_or_above');
  assert.equal(policy.oborot_long_form_image_brief.classifier.minimum_characters, 7001);
  assert.equal(policy.oborot_long_form_image_brief.classifier.upper_band_maximum_characters, 9000);
  assert.equal(policy.oborot_long_form_image_brief.preview.count, 1);
  assert.equal(policy.oborot_long_form_image_brief.inline.count, 3);
  assert.equal(policy.oborot_long_form_image_brief.total, 4);
  assert.deepEqual(policy.article_image_brief.assets.map((asset) => asset.role),
    ['cover_preview', 'section_semantic_scene']);
  assert.deepEqual(policy.article_image_brief.assets.map((asset) => asset.oborot_aspect_ratio),
    ['1:1', '3:2_landscape']);
  assert.equal(policy.photography_style.look, 'photorealistic_editorial_lifestyle');
  assert.equal(policy.photography_style.setting, 'credible_russian_business_context_matching_intent');
  assert.ok(policy.requirements.includes('section_anchor_required'));
  assert.ok(policy.requirements.includes('semantic_role_required'));
  assert.equal(policy.prompt_contract.topic_only_is_insufficient, true);
  assert.equal(policy.prompt_contract.generic_person_with_laptop_or_phone_is_insufficient, true);
  assert.equal(policy.device_policy.incidental_device_maximum_inline_visuals, 1);
  assert.equal(policy.validator.mode, 'fail_closed');
  assert.ok(policy.validator.reject.includes('landing_page'));
  assert.ok(policy.validator.reject.includes('working_ui'));
  assert.ok(policy.visual_qa.includes('reject_repeated_screen_gazing_set'));
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
  assert.match(compiledRule.content, /ровно три целевых .*визуала/iu);
  assert.match(compiledRule.content, /от 7 001 знака.*ровно четыре визуала/iu);
  assert.equal(compiled.pack.payload.execution_card.editorial_visual_package.long_form.total, 4);
  assert.equal(compiled.pack.payload.execution_card.editorial_visual_package.long_form.inline.count, 3);
  assert.match(compiledRule.content, /превью 1:1/iu);
  assert.match(compiledRule.content, /3:2 landscape/iu);
  assert.match(compiledRule.content, /screenshots\/screen captures.*запрещены/iu);
  assert.match(compiledRule.content, /section_anchor.*semantic_role/iu);
  assert.match(compiledRule.content, /максимум в одном inline-визуале/iu);
  assert.equal(compiled.pack.payload.execution_card.editorial_visual_package.default.prompt_contract.semantic_first, true);
  assert.equal(compiled.pack.payload.execution_card.editorial_visual_package.default.validator.mode, 'fail_closed');

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

const semanticPhotoPlan = () => [
  { visual_kind: 'photorealistic_editorial_photo', section_anchor: 'Почему карточка теряет позиции',
    semantic_role: 'Показать последствие слабой видимости — пустой поток покупателей',
    scene_intent: 'пустой вход в небольшой магазин', observable_action: 'владелец меняет табличку с режимом работы',
    business_context: 'уличный магазин у дома', composition: 'широкий уличный план', device_role: 'none', readable_ui: false },
  { visual_kind: 'photorealistic_editorial_photo', section_anchor: 'Как подготовить посадочную страницу',
    semantic_role: 'Показать сверку предложения с реальным ассортиментом',
    scene_intent: 'проверка наличия товара на полках', observable_action: 'сотрудница сверяет бумажный список с витриной',
    business_context: 'локальный магазин косметики', composition: 'средний план между стеллажами', device_role: 'none', readable_ui: false },
  { visual_kind: 'photorealistic_editorial_photo', section_anchor: 'Как оценить результат запуска',
    semantic_role: 'Показать рост реальных обращений после изменений',
    scene_intent: 'выдача подготовленного заказа покупателю', observable_action: 'продавец передаёт упакованный заказ клиенту',
    business_context: 'пункт выдачи малого бизнеса', composition: 'крупный план рук и упаковки',
    device_role: 'incidental', readable_ui: false, screen_is_subject: false },
];

test('visual validator accepts three anchored distinct photo scenes and builds semantic prompts', () => {
  const plan = semanticPhotoPlan();
  assert.deepEqual(validateEditorialVisualPlan(plan), { valid: true, inline_count: 3, incidental_device_count: 1 });
  const prompts = buildEditorialVisualPrompts(plan);
  assert.equal(prompts.length, 3);
  assert.match(prompts[0], /Section: Почему карточка теряет позиции/);
  assert.match(prompts[0], /Observable action: владелец меняет табличку/);
  assert.match(prompts[0], /No screenshots/);
});

test('visual validator rejects a real landing screenshot and a working UI screenshot', () => {
  for (const visualKind of ['landing_page', 'working_ui']) {
    const plan = semanticPhotoPlan();
    plan[0] = { ...plan[0], visual_kind: visualKind, is_screenshot: true };
    assert.throws(() => validateEditorialVisualPlan(plan), /rejects screenshots and screen captures/);
  }
});

test('visual validator rejects missing semantic mapping, screen-as-subject, and repeated screen-gazing set', () => {
  const missingMapping = semanticPhotoPlan();
  delete missingMapping[1].section_anchor;
  assert.throws(() => validateEditorialVisualPlan(missingMapping), /requires section_anchor/);

  const screenSubject = semanticPhotoPlan();
  screenSubject[1] = { ...screenSubject[1], screen_is_subject: true, device_role: 'primary' };
  assert.throws(() => validateEditorialVisualPlan(screenSubject), /rejects screen-as-subject/);

  const repeated = semanticPhotoPlan().map((visual, index) => ({ ...visual,
    section_anchor: `Раздел ${index + 1}`, semantic_role: `Общая роль ${index + 1}`,
    scene_intent: `человек смотрит в экран ${index + 1}`, observable_action: `смотрит в устройство ${index + 1}`,
    business_context: `офис ${index + 1}`, composition: `стол с ноутбуком ${index + 1}`,
    generic_screen_gazing: true, device_role: index === 0 ? 'incidental' : 'none' }));
  assert.throws(() => validateEditorialVisualPlan(repeated), /rejects generic screen-gazing/);
});
