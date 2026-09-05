import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { deflateSync } from 'node:zlib';
import { EDITORIAL_CONTRACT, compileEditorialSpec, validateEditorialArtifact } from '../scripts/editorial-contract.mjs';

const core = { behavioral_factors_general: [
  'Накрутка ПФ', ...Array.from({ length: 301 }, (_, index) => `точный запрос ${index + 1}`),
] };
const structure = ['Подготовка', 'Планирование', 'Контроль', 'Результат'];
function validInput() {
  const inline = structure.slice(0, 3).map((section, index) => ({ path: `../assets/inline-${index + 1}.png`,
    medium: 'photorealistic_editorial_photo', aspect_ratio: '3:2', section_anchor: section,
    semantic_role: `role-${index}`, scene_intent: `scene-${index}`, observable_action: `action-${index}`,
    business_context: `context-${index}`, composition: `composition-${index}`, device_role: 'none' }));
  return { platform: 'Oborot.ru', character_range: { minimum: 7001, maximum: 9000 }, selected_h1: 'Накрутка ПФ',
    primary_query: 'Накрутка ПФ', secondary_queries: Array.from({ length: 17 }, (_, index) => `точный запрос ${index + 1}`),
    selected_clusters: ['behavioral_factors_general'], user_intent: 'Подготовить управляемый запуск', structure,
    lsi: [
      { term: 'поисковая выдача', category: 'search_context', section_anchor: structure[0], zone: 'unordered_list' },
      { term: 'релевантность страницы', category: 'page_quality', section_anchor: structure[1], zone: 'unordered_list' },
      { term: 'дневной лимит', category: 'campaign_control', section_anchor: structure[2], zone: 'unordered_list' },
      { term: 'динамика позиций', category: 'measurement', section_anchor: structure[3], zone: 'unordered_list' },
    ], links: EDITORIAL_CONTRACT.article.landing_link_positions.map((position) => ({ position, url: 'https://go.mtrhit.ru/' })),
    image_package: { preview: [{ path: '../assets/preview.png', medium: 'photorealistic_editorial_photo', aspect_ratio: '1:1' }], inline } };
}

test('one contract owns the 302 core, exactly three H1 forms, links and long-form image package', () => {
  assert.equal(EDITORIAL_CONTRACT.semantic_core.keyword_count, 302);
  assert.deepEqual(EDITORIAL_CONTRACT.h1.approved_forms, ['Накрутка ПФ', 'Накрутка ПФ Яндекс', 'Накрутка поведенческих факторов']);
  assert.deepEqual(EDITORIAL_CONTRACT.article.landing_link_positions, ['beginning', 'body_1', 'body_2', 'final_cta']);
  assert.deepEqual(EDITORIAL_CONTRACT.visuals.oborot_long_form, { minimum_characters: 7001, preview_count: 1, inline_count: 3,
    preview_aspect_ratios: ['1:1'], inline_aspect_ratios: ['3:2', '16:9'] });
  assert.equal(EDITORIAL_CONTRACT.supersedes.length, 3);
});

test('pre-generation spec rejects invalid H1, LSI and visual concept', () => {
  for (const mutate of [
    (input) => { input.selected_h1 = 'Накрутка поведенческого фактора'; },
    (input) => { input.lsi[0].zone = 'h2'; },
    (input) => { input.image_package.inline[0].is_screenshot = true; },
  ]) {
    const input = validInput(); mutate(input);
    assert.throws(() => compileEditorialSpec(input, core), /editorial_spec_invalid/);
  }
});

test('owner approval does not turn an arbitrary long core query into a short base H1', () => {
  const rejected = validInput();
  rejected.selected_h1 = 'накрутка поведенческих факторов купить заказать с длинным пояснением';
  rejected.primary_query = rejected.selected_h1;
  rejected.owner_structure_approved = true;
  rejected.approved_structure = { h1: rejected.selected_h1 };
  const taxonomy = { behavioral_factors_general: [
    'Накрутка ПФ', rejected.selected_h1, ...Array.from({ length: 300 }, (_, index) => `точный запрос ${index + 1}`),
  ] };
  assert.throws(() => compileEditorialSpec(rejected, taxonomy), /selected_h1/);
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function png(width, height) {
  const chunk = (type, data) => {
    const header = Buffer.alloc(8); header.writeUInt32BE(data.length, 0); header.write(type, 4);
    const checksum = Buffer.alloc(4); checksum.writeUInt32BE(crc32(Buffer.concat([Buffer.from(type), data])));
    return Buffer.concat([header, data, checksum]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
  const rows = Buffer.alloc(height * (1 + width * 3));
  for (let row = 0; row < height; row += 1) rows[row * (1 + width * 3)] = 0;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
}

function headerOnlyPng(width, height) {
  const chunk = (type, data) => { const header = Buffer.alloc(8); header.writeUInt32BE(data.length, 0); header.write(type, 4); return Buffer.concat([header, data, Buffer.alloc(4)]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IEND', Buffer.alloc(0))]);
}

function artifactFixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'editorial-contract-')); t.after(() => rmSync(directory, { recursive: true, force: true }));
  const drafts = join(directory, 'drafts'); const assets = join(directory, 'assets'); mkdirSync(drafts); mkdirSync(assets);
  const input = validInput(); const spec = compileEditorialSpec(input, core);
  writeFileSync(join(assets, 'preview.png'), png(100, 100));
  for (let index = 1; index <= 3; index += 1) writeFileSync(join(assets, `inline-${index}.png`), png(150, 100));
  const targetQueries = [input.primary_query, ...input.secondary_queries].join('. ');
  const sections = input.lsi.map((item, index) => `### ${item.section_anchor}\n- ${item.term}\n${index < 3 ? `![${item.semantic_role}](../assets/inline-${index + 1}.png)` : ''}\n${index === 0 || index === 1 ? 'https://go.mtrhit.ru/' : ''}`).join('\n');
  let article = `# ${input.selected_h1}\n![preview](../assets/preview.png)\n${targetQueries}\nhttps://go.mtrhit.ru/\n${sections}\n`;
  article += 'Практическая рекомендация для управления кампанией. '.repeat(150);
  article += '\n### Дополнительный контроль\nПрактика.\n';
  while (article.replace(/https?:\/\/\S+/gu, '').length < 7001) article += 'Контроль результата. ';
  article += '\nhttps://go.mtrhit.ru/\nИтог.';
  const articlePath = join(drafts, 'article.md'); writeFileSync(articlePath, article);
  const reviewedAssets = [
    ['../assets/preview.png', 'preview.png'],
    ...Array.from({ length: 3 }, (_, index) => [`../assets/inline-${index + 1}.png`, `inline-${index + 1}.png`]),
  ].map(([path, file]) => ({ path, sha256: createHash('sha256').update(readFileSync(join(assets, file))).digest('hex'), passed: true }));
  const visualReview = { performed: true, passed: true, reviewer: 'visual-reviewer',
    result: 'Every current image was inspected.', assets: reviewedAssets };
  return { directory, drafts, assets, input, spec, article, articlePath, visualReview };
}

test('valid real article and assets produce computed evidence', (t) => {
  const { spec, articlePath, visualReview } = artifactFixture(t);
  assert.equal(spec.contract_snapshot.revision, spec.contract_revision);
  const evidence = validateEditorialArtifact(spec, { article_path: articlePath, visual_review: visualReview });
  assert.equal(evidence.computed, true); assert.equal(evidence.passed, true);
  assert.equal(evidence.visuals.count, 4); assert.equal(evidence.links.exact_count, 4);
  assert.match(evidence.content_sha256, /^[a-f0-9]{64}$/u);
});

test('source overlap detects exact, near-full and embedded fragment borrowing and keeps no-source unknown', (t) => {
  const fixture = artifactFixture(t);
  const exactPath = join(fixture.directory, 'exact.txt'); writeFileSync(exactPath, fixture.article);
  const nearPath = join(fixture.directory, 'near.txt'); writeFileSync(nearPath, `${fixture.article.slice(0, -1)}!`);
  const fragment = fixture.article.split(/\s+/u).slice(80, 180).join(' ');
  const partialPath = join(fixture.directory, 'partial.txt'); writeFileSync(partialPath, `Unrelated opening. ${fragment} Unrelated ending.`);
  const run = (source_paths) => validateEditorialArtifact(fixture.spec, {
    article_path: fixture.articlePath, source_paths, visual_review: fixture.visualReview,
  }).originality;
  assert.equal(run([exactPath]).max_overlap_percent, 100);
  assert.ok(run([nearPath]).max_overlap_percent >= 99);
  assert.ok(run([partialPath]).max_overlap_percent > 0);
  assert.equal(run([]).comparison_status, 'not_performed_no_accessible_sources');
  assert.equal(run([]).max_overlap_percent, null);
});

test('PNG headers without decodable image data and corrupted images are rejected', (t) => {
  const fixture = artifactFixture(t);
  writeFileSync(join(fixture.assets, 'preview.png'), headerOnlyPng(100, 100));
  assert.throws(() => validateEditorialArtifact(fixture.spec, {
    article_path: fixture.articlePath, visual_review: fixture.visualReview,
  }), /image_unreadable/);
  writeFileSync(join(fixture.assets, 'preview.png'), Buffer.alloc(0));
  assert.throws(() => validateEditorialArtifact(fixture.spec, {
    article_path: fixture.articlePath, visual_review: fixture.visualReview,
  }), /image_unreadable/);
});

test('final artifact acceptance waits for a hash-bound review of every current image', (t) => {
  const fixture = artifactFixture(t);
  const pending = validateEditorialArtifact(fixture.spec, { article_path: fixture.articlePath });
  assert.equal(pending.technical_checks.passed, true);
  assert.equal(pending.passed, false);
  assert.equal(pending.visuals.review.performed, false);
  const reviewed = validateEditorialArtifact(fixture.spec, {
    article_path: fixture.articlePath, visual_review: fixture.visualReview,
  });
  assert.equal(reviewed.passed, true);
  const changed = png(100, 100); changed[changed.length - 20] ^= 1;
  writeFileSync(join(fixture.assets, 'preview.png'), changed);
  assert.throws(() => validateEditorialArtifact(fixture.spec, {
    article_path: fixture.articlePath, visual_review: fixture.visualReview,
  }), /visual_review_asset_hash|image_unreadable/);
});
