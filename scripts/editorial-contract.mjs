import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inflateSync } from 'node:zlib';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const EDITORIAL_CONTRACT = Object.freeze(JSON.parse(readFileSync(resolve(root, 'config/editorial-contract.json'), 'utf8')));
const text = (value) => typeof value === 'string' && value.trim() ? value.trim() : null;
const normalized = (value) => String(value ?? '').toLocaleLowerCase('ru-RU').replace(/\s+/gu, ' ').trim();
const unique = (values) => new Set(values.map(normalized)).size === values.length;
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const fail = (prefix, field) => { throw new Error(`${prefix}:${field}`); };
const specFail = (field, reason) => fail('editorial_spec_invalid', `${field}:${reason}`);
const artifactFail = (field) => fail('editorial_artifact_invalid', field);
const require = createRequire(import.meta.url);
const occurrences = (value, needle) => normalized(value).split(normalized(needle)).length - 1;
const bandFor = (count) => EDITORIAL_CONTRACT.volume_bands.find((band) => count >= band.minimum_characters && count <= band.maximum_characters) ?? null;

function assertCore(query, taxonomy, field) {
  const allowed = new Set(Object.values(taxonomy).flat().map(normalized));
  if (!text(query) || !allowed.has(normalized(query))) specFail(field, 'not_in_approved_302_core');
}
function validateVisuals(visuals, range, platform) {
  if (!visuals || typeof visuals !== 'object') specFail('image_package', 'required');
  const longForm = normalized(platform) === 'oborot.ru' && range.minimum >= EDITORIAL_CONTRACT.visuals.oborot_long_form.minimum_characters;
  const expected = longForm ? EDITORIAL_CONTRACT.visuals.oborot_long_form : EDITORIAL_CONTRACT.visuals.default;
  if (!Array.isArray(visuals.preview) || visuals.preview.length !== expected.preview_count || !Array.isArray(visuals.inline) || visuals.inline.length !== expected.inline_count) specFail('image_package', 'wrong_count');
  for (const visual of [...visuals.preview, ...visuals.inline]) {
    if (visual.is_screenshot === true || visual.screen_is_subject === true || visual.readable_ui === true) specFail('image_package', 'screenshot_or_screen_prohibited');
    if (visual.medium !== EDITORIAL_CONTRACT.visuals.allowed_medium) specFail('image_package', 'visual_concept_not_photorealistic');
  }
  for (const [index, visual] of visuals.inline.entries()) for (const field of EDITORIAL_CONTRACT.visuals.required_inline_fields) if (!text(visual[field])) specFail(`image_package.inline.${index}.${field}`, 'required');
  for (const field of EDITORIAL_CONTRACT.visuals.diversity_fields) if (!unique(visuals.inline.map((visual) => visual[field]))) specFail(`image_package.inline.${field}`, 'must_be_distinct');
  if (visuals.inline.filter((visual) => visual.device_role === 'incidental').length > EDITORIAL_CONTRACT.visuals.incidental_device_maximum) specFail('image_package', 'too_many_devices');
  if (longForm && (!visuals.preview.every((item) => EDITORIAL_CONTRACT.visuals.oborot_long_form.preview_aspect_ratios.includes(item.aspect_ratio)) || !visuals.inline.every((item) => EDITORIAL_CONTRACT.visuals.oborot_long_form.inline_aspect_ratios.includes(item.aspect_ratio)))) specFail('image_package', 'aspect_ratio');
}

export function compileEditorialSpec(input, taxonomy) {
  if (!taxonomy || Object.values(taxonomy).flat().length !== EDITORIAL_CONTRACT.semantic_core.keyword_count) specFail('semantic_core', 'expected_302_queries');
  const platform = text(input.platform); const selectedH1 = text(input.selected_h1); const range = input.character_range;
  if (!platform) specFail('platform', 'required');
  const isExactApprovedH1 = EDITORIAL_CONTRACT.h1.approved_forms.includes(selectedH1);
  if (!isExactApprovedH1) specFail('selected_h1', 'not_approved_short_base_form');
  if (!Number.isInteger(range?.minimum) || !Number.isInteger(range?.maximum) || range.minimum > range.maximum) specFail('character_range', 'invalid');
  assertCore(input.primary_query, taxonomy, 'primary_query');
  if (!Array.isArray(input.secondary_queries) || !input.secondary_queries.length || !unique([input.primary_query, ...input.secondary_queries])) specFail('secondary_queries', 'required_unique');
  input.secondary_queries.forEach((query) => assertCore(query, taxonomy, 'secondary_queries'));
  const band = bandFor(range.minimum); const queryCount = 1 + input.secondary_queries.length;
  if (band && (queryCount < band.minimum_queries || queryCount > band.maximum_queries)) specFail('secondary_queries', 'outside_volume_band');
  if (!Array.isArray(input.lsi) || !input.lsi.length) specFail('lsi', 'required');
  for (const [index, item] of input.lsi.entries()) {
    if (!EDITORIAL_CONTRACT.lsi.categories.includes(item?.category) || !text(item?.term) || !text(item?.section_anchor) || !EDITORIAL_CONTRACT.lsi.allowed_zones.includes(item?.zone)) specFail(`lsi.${index}`, 'category_term_section_and_zone_required');
    if (new Set([input.primary_query, ...input.secondary_queries].map(normalized)).has(normalized(item.term))) specFail(`lsi.${index}`, 'must_not_be_target_query');
  }
  if (!Array.isArray(input.structure) || input.structure.length < 3 || input.structure.some((section) => !text(section))) specFail('structure', 'required');
  if (!Array.isArray(input.links) || input.links.length !== EDITORIAL_CONTRACT.article.landing_link_positions.length || input.links.some((item, index) => item.url !== EDITORIAL_CONTRACT.article.landing_url || item.position !== EDITORIAL_CONTRACT.article.landing_link_positions[index])) specFail('links', 'distribution');
  validateVisuals(input.image_package, range, platform);
  const spec = { schema_version: 2, contract_id: EDITORIAL_CONTRACT.id, contract_revision: EDITORIAL_CONTRACT.revision, contract_snapshot: structuredClone(EDITORIAL_CONTRACT), status: 'valid', pre_generation_gate: 'passed', content_source_format: EDITORIAL_CONTRACT.content_source.format, publication_projection: EDITORIAL_CONTRACT.content_source.projection, platform, format: 'article', character_range: range, h1_allowlist: [...EDITORIAL_CONTRACT.h1.approved_forms], selected_h1: selectedH1, h1_selection: 'exact_approved_form', primary_query: input.primary_query, secondary_queries: [...input.secondary_queries], selected_clusters: [...input.selected_clusters], adjacent_cluster_rationale: text(input.adjacent_cluster_rationale), user_intent: text(input.user_intent), lsi: input.lsi, structure: input.structure, links: input.links, image_package: input.image_package, publication_requirements: { external_publication: 'owner_gated', owner_confirmation_or_https_url: true } };
  if (!spec.user_intent || !spec.selected_clusters.length) specFail('semantic_context', 'cluster_and_intent_required');
  return spec;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngRows(width, height, bitDepth, colorType, interlace) {
  const samples = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[colorType];
  const validDepths = { 0: [1, 2, 4, 8, 16], 2: [8, 16], 3: [1, 2, 4, 8], 4: [8, 16], 6: [8, 16] }[colorType];
  if (!samples || !validDepths.includes(bitDepth)) throw new Error('unsupported_png_layout');
  const bitsPerPixel = samples * bitDepth;
  const passes = interlace === 0 ? [[0, 0, 1, 1]]
    : interlace === 1 ? [[0, 0, 8, 8], [4, 0, 8, 8], [0, 4, 4, 8], [2, 0, 4, 4], [0, 2, 2, 4], [1, 0, 2, 2], [0, 1, 1, 2]] : null;
  if (!passes) throw new Error('unsupported_png_interlace');
  const rows = [];
  for (const [startX, startY, stepX, stepY] of passes) {
    const passWidth = width > startX ? Math.ceil((width - startX) / stepX) : 0;
    const passHeight = height > startY ? Math.ceil((height - startY) / stepY) : 0;
    if (!passWidth || !passHeight) continue;
    const rowBytes = Math.ceil(passWidth * bitsPerPixel / 8);
    for (let row = 0; row < passHeight; row += 1) rows.push(rowBytes);
  }
  return rows;
}

function decodePng(bytes) {
  let offset = 8; let header = null; let ended = false; const idat = [];
  while (offset + 12 <= bytes.length) {
    const length = bytes.readUInt32BE(offset); const end = offset + 12 + length;
    if (end > bytes.length) throw new Error('truncated_png_chunk');
    const typeBytes = bytes.subarray(offset + 4, offset + 8); const type = typeBytes.toString('ascii');
    const data = bytes.subarray(offset + 8, offset + 8 + length);
    if (crc32(Buffer.concat([typeBytes, data])) !== bytes.readUInt32BE(offset + 8 + length)) throw new Error('png_crc');
    if (type === 'IHDR') {
      if (header || offset !== 8 || length !== 13) throw new Error('png_ihdr');
      header = { width: data.readUInt32BE(0), height: data.readUInt32BE(4), bitDepth: data[8], colorType: data[9],
        compression: data[10], filter: data[11], interlace: data[12] };
    } else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') { if (length !== 0) throw new Error('png_iend'); ended = true; offset = end; break; }
    offset = end;
  }
  if (!header || !header.width || !header.height || header.compression !== 0 || header.filter !== 0
    || !ended || offset !== bytes.length || !idat.length || idat.every((chunk) => chunk.length === 0)) throw new Error('png_structure');
  const rowSizes = pngRows(header.width, header.height, header.bitDepth, header.colorType, header.interlace);
  const pixels = inflateSync(Buffer.concat(idat));
  const expected = rowSizes.reduce((total, rowBytes) => total + 1 + rowBytes, 0);
  if (pixels.length !== expected) throw new Error('png_pixel_length');
  let rowOffset = 0;
  for (const rowBytes of rowSizes) {
    if (pixels[rowOffset] > 4) throw new Error('png_filter');
    rowOffset += 1 + rowBytes;
  }
  return { width: header.width, height: header.height };
}

function decodeJpeg(bytes) {
  const candidates = [
    'jpeg-js',
    resolve(dirname(process.execPath), '..', 'node_modules', 'jpeg-js'),
    process.env.USERPROFILE ? join(process.env.USERPROFILE, '.cache', 'codex-runtimes', 'codex-primary-runtime',
      'dependencies', 'node', 'node_modules', 'jpeg-js') : null,
  ].filter(Boolean);
  let decoder = null;
  for (const candidate of candidates) {
    try { decoder = require(candidate); break; } catch (error) {
      if (error?.code !== 'MODULE_NOT_FOUND') throw error;
    }
  }
  if (!decoder?.decode) throw new Error('jpeg_decoder_unavailable');
  const decoded = decoder.decode(bytes, { useTArray: true, formatAsRGBA: false, tolerantDecoding: false });
  if (!Number.isInteger(decoded?.width) || decoded.width < 1 || !Number.isInteger(decoded?.height)
    || decoded.height < 1 || !decoded.data || decoded.data.length < decoded.width * decoded.height * 3) {
    throw new Error('jpeg_pixels');
  }
  return { width: decoded.width, height: decoded.height };
}

function imageSize(path) {
  const bytes = readFileSync(path);
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    try { return decodePng(bytes); } catch { artifactFail(`image_unreadable:${extname(path)}`); }
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    try { return decodeJpeg(bytes); } catch { artifactFail(`image_unreadable:${extname(path)}`); }
  }
  artifactFail(`image_unreadable:${extname(path)}`);
}
const ratio = ({ width, height }) => { const value = width / height; return Math.abs(value - 1) < .02 ? '1:1' : Math.abs(value - 1.5) < .03 ? '3:2' : Math.abs(value - 16 / 9) < .03 ? '16:9' : `${width}:${height}`; };

export function projectEditorialSource(source) {
  if (!source || source.format !== EDITORIAL_CONTRACT.content_source.format || !text(source.h1) || !Array.isArray(source.blocks)) artifactFail('structured_source');
  const lines = [source.h1.trim()];
  const append = (block) => { if (!block || typeof block !== 'object') artifactFail('structured_source_block'); if (block.type === 'paragraph') { if (!text(block.text)) artifactFail('structured_source_paragraph'); lines.push(block.text.trim()); return; } if (block.type === 'link') { if (!text(block.url)) artifactFail('structured_source_link'); lines.push(block.url.trim()); return; } if (block.type === 'image') { if (!text(block.path)) artifactFail('structured_source_image'); lines.push(`![${text(block.alt) ?? 'image'}](${block.path.trim()})`); return; } if (block.type === 'section') { if (!text(block.heading) || ![2, 3].includes(block.level) || !Array.isArray(block.blocks)) artifactFail('structured_source_section'); lines.push(block.heading.trim()); block.blocks.forEach(append); return; } if (block.type === 'unordered_list' || block.type === 'checklist') { if (!Array.isArray(block.items) || !block.items.length || block.items.some((item) => !text(item))) artifactFail('structured_source_list'); lines.push(...block.items.map((item) => `${block.type === 'checklist' ? '- [ ]' : '-'} ${item.trim()}`)); return; } artifactFail('structured_source_block_type'); };
  source.blocks.forEach(append); return `${lines.join('\n')}\n`;
}
function loadStructuredSource(path, article) { if (!path) return null; if (!existsSync(path)) artifactFail('structured_source_missing'); const value = readFileSync(path, 'utf8'); const source = JSON.parse(value); const projection = projectEditorialSource(source); if (projection !== article) artifactFail('publication_projection_mismatch'); return { source, sha256: sha256(value), projection_sha256: sha256(projection) }; }
function headingsFor(article, source) { if (source) { const headings = []; let from = 0; const visit = (blocks) => blocks.forEach((block) => { if (block.type === 'section') { const index = article.indexOf(block.heading, from); if (index < 0) artifactFail('structured_heading_missing'); headings.push({ level: block.level, value: block.heading.trim(), index }); from = index + block.heading.length; visit(block.blocks); } }); visit(source.blocks); return headings; } return [...article.matchAll(/^(#{2,3})\s+(.+)$/gmu)].map((match) => ({ level: match[1].length, value: match[2].trim(), index: match.index })); }
function sectionBounds(headings, anchor) { const index = headings.findIndex((heading) => heading.value === anchor); if (index < 0) artifactFail('lsi_anchor'); const heading = headings[index]; const next = headings.slice(index + 1).find((item) => item.level <= heading.level); return { heading, start: heading.index, end: next?.index ?? Infinity }; }
function validateLsi(article, headings, item) { const bounds = sectionBounds(headings, item.section_anchor); const section = article.slice(bounds.start, bounds.end); if (item.zone === 'h3') { const children = headings.filter((heading) => heading.level === 3 && heading.index >= bounds.start && heading.index < bounds.end); if (!children.some((heading) => occurrences(heading.value, item.term) > 0)) artifactFail('lsi_placement'); } else { const matcher = item.zone === 'checklist' ? /^\s*-\s*\[\s?[xX]?\s?\]\s+(.+)$/gmu : /^\s*[-*+]\s+(.+)$/gmu; if (![...section.matchAll(matcher)].some((match) => occurrences(match[1], item.term) > 0)) artifactFail('lsi_placement'); } return { ...item, found: true, section_start: bounds.heading.value }; }
function actualLinkPositions(article, matches, headings) { const firstBody = headings[0]?.index ?? Math.ceil(article.length * .25); const finalStart = Math.max(firstBody, Math.floor(article.length * .75)); return matches.map((match) => { if (match.index < firstBody) return 'beginning'; if (match.index >= finalStart) return 'final_cta'; return headings.filter((heading) => heading.index <= match.index).length <= 1 ? 'body_1' : 'body_2'; }); }
function lexicalTokens(value) { return normalized(value).match(/[\p{L}\p{N}]+/gu) ?? []; }
function fragmentOverlap(article, source) {
  const articleTokens = lexicalTokens(article); const sourceTokens = lexicalTokens(source);
  if (!articleTokens.length || !sourceTokens.length) return { percent: 0, article_tokens: articleTokens.length,
    source_tokens: sourceTokens.length, matched_article_tokens: 0, shingle_size: 0 };
  const shingleSize = Math.min(5, articleTokens.length, sourceTokens.length);
  const sourceShingles = new Set();
  for (let index = 0; index <= sourceTokens.length - shingleSize; index += 1) {
    sourceShingles.add(sourceTokens.slice(index, index + shingleSize).join('\u0000'));
  }
  const matched = new Uint8Array(articleTokens.length);
  for (let index = 0; index <= articleTokens.length - shingleSize; index += 1) {
    if (!sourceShingles.has(articleTokens.slice(index, index + shingleSize).join('\u0000'))) continue;
    matched.fill(1, index, index + shingleSize);
  }
  const matchedCount = matched.reduce((total, item) => total + item, 0);
  return { percent: Number((matchedCount / articleTokens.length * 100).toFixed(2)), article_tokens: articleTokens.length,
    source_tokens: sourceTokens.length, matched_article_tokens: matchedCount, shingle_size: shingleSize };
}
function overlap(article, paths) {
  const sources = paths.map((path) => {
    if (!existsSync(path)) artifactFail(`source_missing:${path}`);
    const source = readFileSync(path, 'utf8'); const measured = fragmentOverlap(article, source);
    return { path, sha256: sha256(source), overlap_percent: measured.percent,
      article_token_count: measured.article_tokens, source_token_count: measured.source_tokens,
      matched_article_token_count: measured.matched_article_tokens, shingle_size: measured.shingle_size };
  });
  return sources.length ? { method: 'local_deterministic_source_overlap', algorithm: 'token_shingle_v1', comparison_status: 'performed',
    content_sha256: sha256(article), compared_sources: sources,
    max_overlap_percent: Math.max(...sources.map((item) => item.overlap_percent)),
    template_match: sources.some((item) => item.overlap_percent === 100) }
    : { method: 'local_deterministic_source_overlap', algorithm: 'token_shingle_v1', comparison_status: 'not_performed_no_accessible_sources',
      content_sha256: sha256(article), compared_sources: [], max_overlap_percent: null, template_match: null };
}
function visualReview(review, assets) {
  if (!review) return { performed: false, passed: false,
    result: 'Visual review was not performed; metadata cannot prove semantic mapping, diversity, or screenshot absence.', assets: [] };
  if (review.performed !== true || typeof review.passed !== 'boolean' || !text(review.result) || !text(review.reviewer)
    || !Array.isArray(review.assets)) artifactFail('visual_review');
  const expected = new Map(assets.map((asset) => [asset.path, asset.sha256]));
  if (review.assets.length !== expected.size || new Set(review.assets.map((asset) => asset?.path)).size !== expected.size) {
    artifactFail('visual_review_assets');
  }
  const evidence = review.assets.map((asset) => {
    if (!text(asset?.path) || !text(asset?.sha256) || typeof asset.passed !== 'boolean'
      || expected.get(asset.path) !== asset.sha256) artifactFail(`visual_review_asset_hash:${asset?.path ?? 'unknown'}`);
    return { path: asset.path, sha256: asset.sha256, passed: asset.passed };
  });
  if ([...expected].some(([path, hash]) => !evidence.some((item) => item.path === path && item.sha256 === hash))) {
    artifactFail('visual_review_assets');
  }
  return { performed: true, passed: review.passed === true && evidence.every((asset) => asset.passed),
    reviewer: review.reviewer.trim(), result: review.result.trim(), assets: evidence };
}

export function validateEditorialArtifact(spec, { article_path, source_paths = [], structured_source_path = null, visual_review = null }) {
  if (spec?.status !== 'valid' || spec?.pre_generation_gate !== 'passed') artifactFail('spec_not_valid');
  if (spec.content_source_format !== EDITORIAL_CONTRACT.content_source.format) artifactFail('structured_source_contract');
  const pin = spec.contract_snapshot ?? EDITORIAL_CONTRACT; if (pin.id !== spec.contract_id || pin.revision !== spec.contract_revision) artifactFail('contract_pin');
  const articlePath = resolve(article_path); if (!existsSync(articlePath)) artifactFail('article_missing'); const article = readFileSync(articlePath, 'utf8'); const structured = loadStructuredSource(structured_source_path, article);
  const h1 = structured?.source.h1 ?? article.match(/^#\s+(.+)$/mu)?.[1]?.trim() ?? article.split(/\r?\n/u).find((line) => line.trim())?.trim(); if (h1 !== spec.selected_h1) artifactFail('h1');
  const headings = headingsFor(article, structured?.source ?? null); const urls = [...article.matchAll(/https:\/\/go\.mtrhit\.ru\//gu)]; if (urls.length !== spec.links.length) artifactFail('links'); const positions = actualLinkPositions(article, urls, headings); if (new Set(positions).size !== spec.links.length || spec.links.some((link) => !positions.includes(link.position))) artifactFail('link_distribution');
  const body = article.replace(/https?:\/\/\S+/gu, ''); if (body.length < spec.character_range.minimum || body.length > spec.character_range.maximum) artifactFail('character_count'); const queries = [spec.primary_query, ...spec.secondary_queries]; if (queries.some((query) => occurrences(body, query) < 1)) artifactFail('target_queries'); const lsi = spec.lsi.map((item) => validateLsi(article, headings, item));
  const visuals = [...spec.image_package.preview, ...spec.image_package.inline]; const expected = new Set(visuals.map((item) => item.path)); const references = new Set([...article.matchAll(/!\[[^\]]*\]\(([^)]+)\)/gu)].map((match) => match[1])); if (references.size !== expected.size || [...references].some((path) => !expected.has(path))) artifactFail('asset_references');
  const assets = visuals.map((visual) => { const path = resolve(dirname(articlePath), visual.path); if (!existsSync(path)) artifactFail(`asset_missing:${visual.path}`); const bytes = readFileSync(path); const dimensions = imageSize(path); const actual = ratio(dimensions); if (actual !== visual.aspect_ratio) artifactFail(`aspect_ratio:${visual.path}`); return { path: visual.path, sha256: sha256(bytes), exists: true, readable: true, dimensions, aspect_ratio: actual, section_anchor: visual.section_anchor ?? null, semantic_role: visual.semantic_role ?? 'preview' }; });
  const review = visualReview(visual_review, assets); const originality = overlap(article, source_paths);
  const technicalPassed = originality.template_match !== true;
  return { computed: true, passed: technicalPassed && review.passed, technical_checks: { performed: true, passed: technicalPassed },
    final_acceptance: { passed: technicalPassed && review.passed, blocked_by: [
      ...(technicalPassed ? [] : ['source_template_match']), ...(review.passed ? [] : ['visual_review']),
    ] }, contract_id: spec.contract_id, article_path: articlePath, content_sha256: sha256(article), structured_source: structured ? { path: structured_source_path, sha256: structured.sha256, projection_sha256: structured.projection_sha256 } : { status: 'not_provided' }, h1: { heading: h1, matched_query: h1 }, character_count: body.length, target_queries: queries.map((query) => ({ query, occurrences: occurrences(body, query) })), lsi, links: { url: pin.article.landing_url, exact_count: urls.length, positions, actual_positions: positions }, visuals: { count: assets.length, review, semantic_mapping: review, diversity: review, screenshots_prohibited: review, assets }, originality };
}
