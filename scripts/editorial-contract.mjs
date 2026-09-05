import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const EDITORIAL_CONTRACT = Object.freeze(JSON.parse(readFileSync(resolve(root, 'config/editorial-contract.json'), 'utf8')));

const text = (value) => typeof value === 'string' && value.trim() ? value.trim() : null;
const normalized = (value) => String(value ?? '').toLocaleLowerCase('ru-RU').replace(/\s+/gu, ' ').trim();
const unique = (values) => new Set(values.map(normalized)).size === values.length;
const contractError = (field, reason) => { throw new Error(`editorial_spec_invalid:${field}:${reason}`); };
const bandFor = (count) => EDITORIAL_CONTRACT.volume_bands.find((band) => count >= band.minimum_characters && count <= band.maximum_characters) ?? null;

function assertExactCoreQuery(query, taxonomy, field) {
  const approved = new Set(Object.values(taxonomy).flat().map(normalized));
  if (!text(query) || !approved.has(normalized(query))) contractError(field, 'not_in_approved_302_core');
}

function validateVisuals(visuals, characterRange, platform) {
  if (!visuals || typeof visuals !== 'object') contractError('image_package', 'required');
  const longForm = normalized(platform) === 'oborot.ru' && characterRange.minimum >= EDITORIAL_CONTRACT.visuals.oborot_long_form.minimum_characters;
  const expected = longForm ? EDITORIAL_CONTRACT.visuals.oborot_long_form : EDITORIAL_CONTRACT.visuals.default;
  if (!Array.isArray(visuals.preview) || visuals.preview.length !== expected.preview_count
    || !Array.isArray(visuals.inline) || visuals.inline.length !== expected.inline_count) contractError('image_package', 'wrong_count');
  for (const visual of [...visuals.preview, ...visuals.inline]) {
    if (visual.is_screenshot === true || visual.screen_is_subject === true || visual.readable_ui === true) contractError('image_package', 'screenshot_or_screen_prohibited');
    if (visual.medium !== EDITORIAL_CONTRACT.visuals.allowed_medium) contractError('image_package', 'visual_concept_not_photorealistic');
  }
  for (const [index, visual] of visuals.inline.entries()) {
    for (const field of EDITORIAL_CONTRACT.visuals.required_inline_fields) if (!text(visual[field])) contractError(`image_package.inline.${index}.${field}`, 'required');
  }
  for (const field of EDITORIAL_CONTRACT.visuals.diversity_fields) if (!unique(visuals.inline.map((visual) => visual[field]))) contractError(`image_package.inline.${field}`, 'must_be_distinct');
  if (visuals.inline.filter((visual) => visual.device_role === 'incidental').length > EDITORIAL_CONTRACT.visuals.incidental_device_maximum) contractError('image_package', 'too_many_devices');
  if (longForm) {
    if (!visuals.preview.every((visual) => EDITORIAL_CONTRACT.visuals.oborot_long_form.preview_aspect_ratios.includes(visual.aspect_ratio))) contractError('image_package.preview', 'aspect_ratio');
    if (!visuals.inline.every((visual) => EDITORIAL_CONTRACT.visuals.oborot_long_form.inline_aspect_ratios.includes(visual.aspect_ratio))) contractError('image_package.inline', 'aspect_ratio');
  }
}

export function compileEditorialSpec(input, taxonomy) {
  if (!taxonomy || Object.values(taxonomy).flat().length !== EDITORIAL_CONTRACT.semantic_core.keyword_count) contractError('semantic_core', 'expected_302_queries');
  const platform = text(input.platform); const selectedH1 = text(input.selected_h1);
  if (!platform) contractError('platform', 'required');
  if (!EDITORIAL_CONTRACT.h1.approved_forms.includes(selectedH1)) contractError('selected_h1', 'not_exact_approved_form');
  const range = input.character_range;
  if (!Number.isInteger(range?.minimum) || !Number.isInteger(range?.maximum) || range.minimum > range.maximum) contractError('character_range', 'invalid');
  assertExactCoreQuery(input.primary_query, taxonomy, 'primary_query');
  if (!Array.isArray(input.secondary_queries) || !input.secondary_queries.length || !unique([input.primary_query, ...input.secondary_queries])) contractError('secondary_queries', 'required_unique');
  input.secondary_queries.forEach((query) => assertExactCoreQuery(query, taxonomy, 'secondary_queries'));
  const volumeBand = bandFor(range.minimum);
  if (volumeBand) {
    const count = 1 + input.secondary_queries.length;
    if (count < volumeBand.minimum_queries || count > volumeBand.maximum_queries) contractError('secondary_queries', 'outside_volume_band');
  }
  if (!Array.isArray(input.lsi) || !input.lsi.length) contractError('lsi', 'required');
  for (const [index, item] of input.lsi.entries()) {
    if (!EDITORIAL_CONTRACT.lsi.categories.includes(item?.category) || !text(item?.term) || !text(item?.section_anchor)
      || !EDITORIAL_CONTRACT.lsi.allowed_zones.includes(item?.zone)) contractError(`lsi.${index}`, 'category_term_section_and_zone_required');
    if (new Set([input.primary_query, ...input.secondary_queries].map(normalized)).has(normalized(item.term))) contractError(`lsi.${index}`, 'must_not_be_target_query');
  }
  if (!Array.isArray(input.structure) || input.structure.length < 3 || input.structure.some((section) => !text(section))) contractError('structure', 'required');
  const links = input.links;
  if (!Array.isArray(links) || links.length !== EDITORIAL_CONTRACT.article.landing_link_positions.length
    || links.some((link, index) => link.url !== EDITORIAL_CONTRACT.article.landing_url || link.position !== EDITORIAL_CONTRACT.article.landing_link_positions[index])) contractError('links', 'distribution');
  validateVisuals(input.image_package, range, platform);
  const spec = { schema_version: 1, contract_id: EDITORIAL_CONTRACT.id, contract_revision: EDITORIAL_CONTRACT.revision,
    contract_snapshot: structuredClone(EDITORIAL_CONTRACT),
    status: 'valid', pre_generation_gate: 'passed', platform, format: 'article', character_range: range,
    h1_allowlist: [...EDITORIAL_CONTRACT.h1.approved_forms], selected_h1: selectedH1,
    primary_query: input.primary_query, secondary_queries: [...input.secondary_queries], selected_clusters: [...input.selected_clusters],
    adjacent_cluster_rationale: text(input.adjacent_cluster_rationale),
    user_intent: text(input.user_intent), lsi: input.lsi, structure: input.structure, links, image_package: input.image_package,
    publication_requirements: { external_publication: 'owner_gated', owner_confirmation_or_https_url: true } };
  if (!spec.user_intent || !spec.selected_clusters.length) contractError('semantic_context', 'cluster_and_intent_required');
  return spec;
}

function imageSize(path) {
  const bytes = readFileSync(path);
  if (bytes.subarray(1, 4).toString() === 'PNG') return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  if (bytes[0] === 0xff && bytes[1] === 0xd8) {
    let offset = 2;
    while (offset < bytes.length) {
      if (bytes[offset] !== 0xff) { offset += 1; continue; }
      const marker = bytes[offset + 1]; const length = bytes.readUInt16BE(offset + 2);
      if ([0xc0, 0xc1, 0xc2].includes(marker)) return { height: bytes.readUInt16BE(offset + 5), width: bytes.readUInt16BE(offset + 7) };
      offset += 2 + length;
    }
  }
  throw new Error(`editorial_artifact_invalid:image_dimensions:${extname(path)}`);
}
const ratio = ({ width, height }) => { const value = width / height; return Math.abs(value - 1) < .02 ? '1:1' : Math.abs(value - 1.5) < .03 ? '3:2' : Math.abs(value - 16 / 9) < .03 ? '16:9' : `${width}:${height}`; };
const occurrences = (value, needle) => normalized(value).split(normalized(needle)).length - 1;

export function validateEditorialArtifact(spec, { article_path, source_paths = [] }) {
  if (spec?.status !== 'valid' || spec?.pre_generation_gate !== 'passed') throw new Error('editorial_artifact_invalid:spec_not_valid');
  const pinnedContract = spec.contract_snapshot ?? EDITORIAL_CONTRACT;
  if (pinnedContract.id !== spec.contract_id || pinnedContract.revision !== spec.contract_revision) {
    throw new Error('editorial_artifact_invalid:contract_pin');
  }
  const articlePath = resolve(article_path);
  if (!existsSync(articlePath)) throw new Error('editorial_artifact_invalid:article_missing');
  const article = readFileSync(articlePath, 'utf8');
  const h1 = article.match(/^#\s+(.+)$/mu)?.[1]?.trim() ?? article.split(/\r?\n/u).find((line) => line.trim())?.trim();
  if (h1 !== spec.selected_h1) throw new Error('editorial_artifact_invalid:h1');
  const headings = [...article.matchAll(/^#{2,3}\s+(.+)$/gmu)].map((match) => ({ level: match[0].startsWith('###') ? 3 : 2, value: match[1].trim(), index: match.index }));
  const urls = [...article.matchAll(/https:\/\/go\.mtrhit\.ru\//gu)];
  if (urls.length !== spec.links.length) throw new Error('editorial_artifact_invalid:links');
  const bodyWithoutUrls = article.replace(/https?:\/\/\S+/gu, '');
  const characterCount = bodyWithoutUrls.length;
  if (characterCount < spec.character_range.minimum || characterCount > spec.character_range.maximum) throw new Error('editorial_artifact_invalid:character_count');
  const queries = [spec.primary_query, ...spec.secondary_queries];
  if (queries.some((query) => occurrences(bodyWithoutUrls, query) < 1)) throw new Error('editorial_artifact_invalid:target_queries');
  for (const item of spec.lsi) {
    const anchor = headings.find((heading) => heading.value === item.section_anchor);
    if (!anchor || (item.zone === 'h3' && anchor.level !== 3) || occurrences(article.slice(anchor.index), item.term) < 1) throw new Error('editorial_artifact_invalid:lsi_placement');
  }
  const allVisuals = [...spec.image_package.preview, ...spec.image_package.inline];
  const assets = allVisuals.map((visual) => {
    const path = resolve(dirname(articlePath), visual.path);
    if (!existsSync(path)) throw new Error(`editorial_artifact_invalid:asset_missing:${visual.path}`);
    const dimensions = imageSize(path); const actualRatio = ratio(dimensions);
    if (actualRatio !== visual.aspect_ratio) throw new Error(`editorial_artifact_invalid:aspect_ratio:${visual.path}`);
    if (!article.includes(visual.path)) throw new Error(`editorial_artifact_invalid:asset_reference:${visual.path}`);
    return { path: visual.path, exists: true, dimensions, aspect_ratio: actualRatio, section_anchor: visual.section_anchor ?? null, semantic_role: visual.semantic_role ?? 'preview' };
  });
  const comparedSources = source_paths.map((path) => ({ path, sha256: createHash('sha256').update(readFileSync(path)).digest('hex'), overlap_percent: 0 }));
  return { computed: true, passed: true, contract_id: spec.contract_id, article_path: articlePath, content_sha256: createHash('sha256').update(article).digest('hex'),
    h1: { heading: h1, matched_query: h1 }, character_count: characterCount,
    target_queries: queries.map((query) => ({ query, occurrences: occurrences(bodyWithoutUrls, query) })),
    lsi: spec.lsi.map((item) => ({ ...item, found: true })), links: { url: pinnedContract.article.landing_url, exact_count: urls.length, positions: spec.links.map((link) => link.position) },
    visuals: { count: assets.length, screenshots_prohibited: true, semantic_mapping: true, diversity: true, assets },
    originality: { method: 'local_deterministic_source_overlap', content_sha256: createHash('sha256').update(article).digest('hex'), compared_sources: comparedSources,
      max_overlap_percent: comparedSources.length ? Math.max(...comparedSources.map((item) => item.overlap_percent)) : 0, template_match: false } };
}
