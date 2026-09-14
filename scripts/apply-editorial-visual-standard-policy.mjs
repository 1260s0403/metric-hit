import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-visual-standard-policy-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-14T00:00:00.000Z';
const revision = 7;

const SCREEN_VISUAL_KINDS = new Set([
  'screenshot', 'screen_capture', 'landing_page', 'website', 'browser', 'search_results',
  'dashboard', 'working_ui', 'app_ui', 'service_ui', 'branded_promo_screen',
]);

function requiredVisualField(visual, field, index) {
  const value = visual?.[field];
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`inline visual ${index + 1} requires ${field}`);
  }
  return value.trim();
}

export function validateEditorialVisualPlan(inlineVisuals, expectedCount = 3) {
  if (!Array.isArray(inlineVisuals) || inlineVisuals.length !== expectedCount) {
    throw new Error(`editorial visual plan requires exactly ${expectedCount} inline visuals`);
  }
  const anchors = new Set();
  const scenes = new Set();
  const actions = new Set();
  const compositions = new Set();
  const contexts = new Set();
  let incidentalDevices = 0;
  inlineVisuals.forEach((visual, index) => {
    if (!visual || typeof visual !== 'object' || Array.isArray(visual)) {
      throw new Error(`inline visual ${index + 1} must be an object`);
    }
    const kind = requiredVisualField(visual, 'visual_kind', index).toLowerCase();
    if (SCREEN_VISUAL_KINDS.has(kind) || visual.is_screenshot === true) {
      throw new Error(`inline visual ${index + 1} rejects screenshots and screen captures`);
    }
    if (kind !== 'photorealistic_editorial_photo') {
      throw new Error(`inline visual ${index + 1} must be a photorealistic editorial photo`);
    }
    const anchor = requiredVisualField(visual, 'section_anchor', index).toLowerCase();
    requiredVisualField(visual, 'semantic_role', index);
    const scene = requiredVisualField(visual, 'scene_intent', index).toLowerCase();
    const action = requiredVisualField(visual, 'observable_action', index).toLowerCase();
    const composition = requiredVisualField(visual, 'composition', index).toLowerCase();
    const context = requiredVisualField(visual, 'business_context', index).toLowerCase();
    if (visual.screen_is_subject === true || visual.device_role === 'primary') {
      throw new Error(`inline visual ${index + 1} rejects screen-as-subject composition`);
    }
    if (visual.readable_ui === true) {
      throw new Error(`inline visual ${index + 1} rejects readable UI`);
    }
    if (visual.device_role === 'incidental') incidentalDevices += 1;
    else if (!['none', undefined].includes(visual.device_role)) {
      throw new Error(`inline visual ${index + 1} has invalid device_role`);
    }
    if (visual.generic_screen_gazing === true) {
      throw new Error(`inline visual ${index + 1} rejects generic screen-gazing`);
    }
    for (const [set, value, label] of [[anchors, anchor, 'section_anchor'], [scenes, scene, 'scene_intent'],
      [actions, action, 'observable_action'], [compositions, composition, 'composition'],
      [contexts, context, 'business_context']]) {
      if (set.has(value)) throw new Error(`inline visual set repeats ${label}`);
      set.add(value);
    }
  });
  if (incidentalDevices > 1) throw new Error('at most one inline visual may contain an incidental device');
  return { valid: true, inline_count: inlineVisuals.length, incidental_device_count: incidentalDevices };
}

export function buildEditorialVisualPrompts(inlineVisuals) {
  validateEditorialVisualPlan(inlineVisuals);
  return inlineVisuals.map((visual) => [
    `Section: ${visual.section_anchor}.`, `Semantic role: ${visual.semantic_role}.`,
    `Observable action: ${visual.observable_action}.`, `Business context: ${visual.business_context}.`,
    `Scene intent: ${visual.scene_intent}.`, `Composition: ${visual.composition}.`,
    'Photorealistic editorial photography; the section meaning is the subject.',
    'No screenshots, websites, browser pages, search results, dashboards, app UI, promo screens or readable UI.',
    'No screen-centric composition and no generic person looking at a laptop or phone.',
  ].join(' '));
}

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-editorial-visual-standard:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyEditorialVisualStandardPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Фотореалистичный визуальный стандарт статей MetricHit';
  const content = 'Статья по умолчанию получает ровно три целевых фотореалистичных визуала: обложку и две разные смысловые бизнес-сцены. Большая статья Oborot.ru определяется верхним существующим диапазоном шкалы объёма от 7 001 знака; текст свыше 9 000 знаков сохраняет long-form классификацию с обязательным QA-обоснованием. Для неё обязательны ровно четыре визуала: превью 1:1 и три смысловых inline-визуала в разных разделах. Короткие и средние материалы сохраняют стандартный пакет из трёх визуалов. Любые screenshots/screen captures в редакционных статьях запрещены: лендинги, сайты, браузеры, поисковая выдача, dashboards, рабочие интерфейсы, UI приложения или сервиса и брендовые promo screens; исключений для реального интерфейса нет. Каждый inline-визуал обязан иметь точные section_anchor и semantic_role и показывать конкретный тезис, действие, причину или результат раздела. Prompt задаёт наблюдаемое действие и реальный бизнес-контекст раздела; общая тема и generic человек с ноутбуком или телефоном не считаются смыслом. Экран или устройство не может быть главным объектом; устройство допустимо только как второстепенная естественная деталь максимум в одном inline-визуале и без читаемого UI. Пакет из трёх inline-визуалов образует разнообразную visual story: разные разделы, сцены, действия, планы/композиции и бизнес-контексты. Повторяющиеся desk+laptop, phone-gazing, одни люди с коробками и три вариации одной сцены запрещены. Люди и среда правдоподобны для российского бизнеса; запрещены постановочные рукопожатия, фальшивые улыбки и AI-глянец. Без обоснования не добавляются текст, логотипы, стрелки, графики и подписи. Стиль: естественный свет, реалистичные цвета, умеренный контраст и тонкий cyan/blue-акцент только в деталях. Графит/стекло остаётся для social-карточек, схем и продуктовых анонсов, но не для статей. Для Telegram social-карточки обязателен квадрат 1:1, один абстрактный смысловой фокус, глубокий графитовый или почти чёрный фон, простые полупрозрачные матовые стеклянные панели, cyan/blue как основной свет и один небольшой тёплый оранжевый акцент. Карточка не является фотографией архитектуры или интерфейса и не содержит текст, буквы, цифры, логотипы, watermark, людей, устройства, UI, dashboards, иконки, стрелки, шевроны, линии тренда, графики, коридоры или кинематографические архитектурные сцены. QA/validator fail-closed отклоняет screenshot/interface, screen-as-subject, отсутствующую section/semantic mapping, повторяющийся screen-gazing set, AI-артефакты и бессмысленные надписи. Ключевой объект находится в safe area для desktop/mobile crop. Каждый asset имеет описательное имя файла и естественный alt без keyword stuffing. Визуалы оригинальны или лицензированы и релевантны. Для Oborot: превью 1:1, фото в тексте по умолчанию 3:2 landscape; широкий смысловой фотосюжет может быть 16:9 без искажения, а 3:4 используется только по реальной необходимости.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-04', revision });
  const priorPolicyId = stableUuid(`candidate:content.editorial_visual_standard:${revision - 1}`);
  const promptContract = { semantic_first: true, required_fields: ['section_anchor', 'semantic_role', 'scene_intent', 'observable_action', 'business_context', 'composition'], topic_only_is_insufficient: true, generic_person_with_laptop_or_phone_is_insufficient: true, explicit_negative_constraints: ['no_screenshot_or_screen_capture', 'no_screen_as_subject', 'no_readable_ui', 'no_generic_screen_gazing'] };
  const validator = { mode: 'fail_closed', reject: ['screenshot', 'screen_capture', 'landing_page', 'website', 'browser', 'search_results', 'dashboard', 'working_ui', 'app_ui', 'service_ui', 'branded_promo_screen', 'screen_as_subject', 'missing_section_anchor', 'missing_semantic_role', 'repeated_screen_gazing_set', 'repeated_scene_action_composition_or_business_context'], accept: 'three_distinct_anchored_semantic_photo_scenes_with_at_most_one_incidental_non_readable_device' };
  const data = JSON.stringify({ revision, supersedes_semantic_revision: revision - 1, supersedes_candidate_id: priorPolicyId, applies_to: ['articles', 'article_drafts'], article_image_brief: { total: 3, opt_out: 'explicit_owner_instruction', more_only_if: 'necessary_to_explain_content', prompt_contract: promptContract, validator, assets: [{ role: 'cover_preview', count: 1, medium: 'photorealistic_editorial_photo', purpose: 'relevant_business_context_and_credible_action', oborot_aspect_ratio: '1:1' }, { role: 'section_semantic_scene', count: 2, medium: 'photorealistic_editorial_photo', required_fields: ['section_anchor', 'semantic_role', 'scene_intent', 'observable_action', 'business_context', 'composition'], purpose: 'distinct_scene_explaining_anchored_section', oborot_aspect_ratio: '3:2_landscape' }] }, oborot_long_form_image_brief: { classifier: { source_semantic_key: 'content.editorial_target_query_volume_ladder', band: 'highest_or_above', minimum_characters: 7001, upper_band_maximum_characters: 9000, above_band_requires_qa_rationale: true, count_scope: 'content_excluding_internal_markup' }, preview: { count: 1, aspect_ratio: '1:1' }, inline: { count: 3, placement: 'distinct_semantic_sections', required_fields: ['section_anchor', 'semantic_role', 'scene_intent', 'observable_action', 'business_context', 'composition'], photo_aspect_ratio: '3:2_landscape', wide_photo_aspect_ratio: '16:9_when_scene_requires' }, prompt_contract: promptContract, validator, total: 4 }, telegram_social_card_brief: { count: 1, aspect_ratio: '1:1', medium: 'abstract_graphite_glass_social_graphic', semantic_focus: 'one_abstract_metaphor_for_one_post_principle', palette: ['deep_graphite_or_near_black', 'cyan_blue_primary_light', 'one_small_warm_orange_accent'], materials: ['simple_translucent_frosted_glass_panels'], composition: ['one_clear_focal_element', 'calm_negative_space', 'desktop_mobile_safe_area'], prohibited: ['text', 'letters', 'numbers', 'logos', 'watermark', 'people', 'devices', 'ui', 'dashboards', 'icons', 'arrows', 'chevrons', 'trend_lines', 'charts', 'corridors', 'cinematic_architecture'], visual_review_required: true }, photography_style: { look: 'photorealistic_editorial_lifestyle', people: ['natural_pose', 'ordinary_clothing', 'genuine_work_emotion'], setting: 'credible_russian_business_context_matching_intent', lighting: 'natural', color: 'realistic', contrast: 'moderate', brand_accent: 'subtle_cyan_blue_scene_detail_only', avoid: ['staged_handshake', 'fake_success_smile', 'sterile_ai_gloss', 'desk_laptop_repetition', 'phone_gazing', 'screen_centric_composition'] }, prompt_contract: promptContract, visual_story: { inline_count: 3, distinct_across: ['section_anchor', 'scene_intent', 'observable_action', 'composition', 'business_context'], repeated_scene_variations_prohibited: true }, device_policy: { screen_as_subject: 'prohibited', incidental_device_maximum_inline_visuals: 1, readable_ui: 'prohibited', requires_direct_section_semantic_need: true }, requirements: ['section_anchor_required', 'semantic_role_required', 'section_specific_thesis_action_cause_or_result', 'distinct_scenes_actions_compositions_business_contexts', 'desktop_mobile_crop_safe_area', 'descriptive_filename', 'natural_non_stuffed_alt', 'visual_inspection_before_delivery', 'original_or_licensed_and_relevant'], visual_qa: ['section_semantic_mapping', 'visual_story_distinctness', 'faces', 'hands', 'objects', 'background', 'signage', 'unreadable_or_nonsense_text', 'reject_screenshot_or_interface', 'reject_screen_as_subject', 'reject_repeated_screen_gazing_set', 'reject_ai_artifacts'], validator, prohibited: ['all_editorial_screenshots_and_screen_captures', 'landing_site_browser_search_dashboard_working_ui_app_ui_service_ui_brand_promo', 'screen_as_subject', 'generic_person_looking_at_laptop_or_phone', 'repeated_desk_laptop_or_phone_gazing_set', 'abstract_graphite_glass_article_default', 'ai_hallucinated_ui_or_text', 'unjustified_text_logo_arrow_chart_caption_overlays', 'unlicensed_third_party_imagery'], reserved_visual_language: { graphite_glass: ['social_cards', 'diagrams', 'product_announcements'] }, oborot: { preview: '1:1', in_body_photo_default: '3:2_landscape', wide_photo: '16:9_only_when_content_requires', portrait: '3:4_only_when_content_requires', distortion: 'prohibited', official_requirements: ['relevant_to_material', 'copyright_compliant'], official_ratio_found: false, basis: 'observed_published_article_formats_and_owner_approved_editorial_inference' }, owner_approval_required_for: ['global_style_change', 'real_logos', 'external_publication'], non_retroactive: ['existing_content', 'existing_assets'], evidence: { path: decisionPath, social_cards: 'owner-confirmed images in current Telegram Publisher chat', oborot_rules: 'https://oborot.ru/p/community-rules-i31029.html', oborot_observed_article: 'https://oborot.ru/articles/marketpleisy-photography-59-i229015.html' } });
  const sourceId = stableUuid(`source:${decisionPath}:${revision}`);
  const documentId = stableUuid(`document:${decisionPath}:${revision}`);
  const versionId = stableUuid(`document-version:${decisionPath}:${revision}`);
  const policyId = stableUuid(`candidate:content.editorial_visual_standard:${revision}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const priorId = priorPolicyId;
    const priorRows = database.prepare("SELECT id,status,coalesce(json_extract(data_json, '$.revision'), 1) AS revision FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").all('content.editorial_visual_standard', policyId);
    const competing = priorRows.filter((row) => row.status !== 'approved' || Number(row.revision) >= revision);
    if (competing.length) throw new Error('Semantic duplicate or evolution blocks editorial visual standard policy');
    const prior = priorRows.find((row) => row.id === priorId && Number(row.revision) === revision - 1);
    if (!prior) throw new Error(`Approved editorial visual standard revision ${revision - 1} is required before this clarification`);
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(policyId, 'content.editorial_visual_standard');
    if (conflict) throw new Error('Open memory conflict blocks editorial visual standard policy');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-04', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', 'content.editorial_visual_standard', ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(policyId, title, content, data, sourceId, owner).changes);
    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(policyId);
    if (candidate.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым уточнением владельца MetricHit от 04.09.2026; заменяет редакцию 1.', reviewedAt, policyId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(policyId), { type: 'editorial_rule', semantic_key: 'content.editorial_visual_standard', title, content, data_json: data, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'editorial visual standard policy');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, policyId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied editorial visual standard policy: ${JSON.stringify(applyEditorialVisualStandardPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
