import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-visual-standard-policy-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-04T00:00:00.000Z';
const revision = 3;

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
  const content = 'Статья по умолчанию получает ровно три целевых визуала: фотореалистичную обложку, отличающуюся живую бизнес-сцену для ближайшего раздела и реальный скриншот поиска, сайта, MetricHit или рабочего процесса. Каждый визуал иллюстрирует конкретный смысл и интент. Обложка показывает людей, тип бизнеса и правдоподобную рабочую ситуацию по интенту: ноутбук с поиском или сайтом, витрину, офис, склад, клинику, производство или кафе. Люди и среда правдоподобны для российского бизнеса; запрещены постановочные рукопожатия, фальшивые улыбки и AI-глянец. Сцены в одной статье должны быть разными. Поиск, сайты, UI MetricHit, текст и метрики не генерируются: используются только реальные скриншоты или композиты. Без обоснования не добавляются текст, логотипы, стрелки, графики и подписи. Стиль: естественный свет, реалистичные цвета, умеренный контраст и тонкий cyan/blue-акцент только в деталях. Графит/стекло остаётся для social-карточек, схем и продуктовых анонсов, но не для статей. QA проверяет лица, руки, предметы, фон, вывески и текст; AI-артефакты и бессмысленные надписи блокируют asset. Ключевой объект находится в safe area для desktop/mobile crop. Каждый asset имеет описательное имя файла и естественный alt без keyword stuffing. Визуалы оригинальны или лицензированы и релевантны. Для Oborot: превью 1:1, фото в тексте по умолчанию 3:2 landscape, реальный скриншот/workflow может оставаться 16:9; ничего не растягивать, а 3:4 использовать только по реальной необходимости. Больше трёх визуалов — только если это нужно для объяснения.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-04', revision });
  const priorPolicyId = stableUuid(`candidate:content.editorial_visual_standard:${revision - 1}`);
  const data = JSON.stringify({ revision, supersedes_semantic_revision: revision - 1, supersedes_candidate_id: priorPolicyId, applies_to: ['articles', 'article_drafts'], article_image_brief: { total: 3, opt_out: 'explicit_owner_instruction', more_only_if: 'necessary_to_explain_content', assets: [{ role: 'cover_preview', count: 1, medium: 'photorealistic_editorial_photo', purpose: 'people_relevant_business_and_credible_work_situation', oborot_aspect_ratio: '1:1' }, { role: 'section_business_scene', count: 1, medium: 'photorealistic_editorial_photo', purpose: 'distinct_scene_explaining_nearby_section', oborot_aspect_ratio: '3:2_landscape' }, { role: 'real_screenshot_or_workflow', count: 1, medium: 'real_screenshot_or_composite', purpose: 'real_search_site_metrichit_or_workflow', oborot_aspect_ratio: '16:9_allowed' }] }, photography_style: { look: 'photorealistic_editorial_lifestyle', people: ['natural_pose', 'ordinary_clothing', 'genuine_work_emotion'], setting: 'credible_russian_business_context_matching_intent', lighting: 'natural', color: 'realistic', contrast: 'moderate', brand_accent: 'subtle_cyan_blue_scene_detail_only', avoid: ['staged_handshake', 'fake_success_smile', 'sterile_ai_gloss'] }, requirements: ['section_specific_purpose', 'cover_people_business_work_situation', 'distinct_scenes_within_article', 'real_ui_screenshots_or_composites_only', 'desktop_mobile_crop_safe_area', 'descriptive_filename', 'natural_non_stuffed_alt', 'visual_inspection_before_delivery', 'original_or_licensed_and_relevant'], visual_qa: ['faces', 'hands', 'objects', 'background', 'signage', 'unreadable_or_nonsense_text', 'reject_ai_artifacts'], prohibited: ['abstract_graphite_glass_article_default', 'ai_hallucinated_ui_or_text', 'unjustified_text_logo_arrow_chart_caption_overlays', 'unlicensed_third_party_imagery'], reserved_visual_language: { graphite_glass: ['social_cards', 'diagrams', 'product_announcements'] }, oborot: { preview: '1:1', in_body_photo_default: '3:2_landscape', real_screenshot_or_workflow: '16:9_allowed', portrait: '3:4_only_when_content_requires', distortion: 'prohibited', official_requirements: ['relevant_to_material', 'copyright_compliant'], official_ratio_found: false, basis: 'observed_published_article_formats_and_owner_approved_editorial_inference' }, owner_approval_required_for: ['global_style_change', 'real_logos', 'external_publication'], non_retroactive: ['existing_content', 'existing_assets'], evidence: { path: decisionPath, oborot_rules: 'https://oborot.ru/p/community-rules-i31029.html', oborot_observed_article: 'https://oborot.ru/articles/marketpleisy-photography-59-i229015.html' } });
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
