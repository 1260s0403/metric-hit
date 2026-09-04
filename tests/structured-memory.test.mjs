import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import {
  SEMANTIC_CORE_REFERENCE_KEY, SCOPE_IDS, abandonContextPack, closeContextPack, compileContextPack,
  compileCoordinatorContext, compileDeterministicContext, createTaskScope, loadReferencedMemory,
  registerScopedRecord, resolveScopedMemory, routeTask, selectCoordinatorSkills, supersedeScopedRecord,
} from '../scripts/structured-memory.mjs';
import {
  CENTRAL_ORPHAN_PACK_IDS, PROJECT_ORPHAN_PACK_IDS, repairOrphanContextPacks,
} from '../scripts/apply-integrity-repair.mjs';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-structured-memory-'));
  const databasePath = join(directory, 'memory.sqlite');
  execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
  const database = new DatabaseSync(databasePath);
  const fixtureSourceId = '10000000-0000-4000-a000-000000000001';
  const fixtureArticlePolicyId = '10000000-0000-4000-a000-000000000002';
  const fixtureTenChatPolicyId = '10000000-0000-4000-a000-000000000003';
  const fixtureTelegramPolicyId = '10000000-0000-4000-a000-000000000004';
  const fixturePfPolicyId = '10000000-0000-4000-a000-000000000005';
  database.prepare(`INSERT INTO sources(id,type,title,content,status,author,created_at,updated_at,version)
    VALUES (?,'test','Fixture editorial source','Fixture source','active','owner',?,?,1)`)
    .run(fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixtureArticlePolicyId, 'editorial_rule', 'content.editorial_article_preparation_policy',
    'Правила подготовки статей MetricHit',
    'В статье четыре естественные ссылки на https://go.mtrhit.ru/: в начале, две внутри и в финале/CTA. Статья оригинальна.',
    JSON.stringify({ applies_to: ['articles'], landing: 'https://go.mtrhit.ru/',
      landing_link_distribution: ['beginning', 'body_1', 'body_2', 'final_cta'] }),
    fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixtureTenChatPolicyId, 'editorial_rule', 'editorial.tenchat_format_and_search_policy',
    'Редакционное правило TenChat: объём и поисковая подача',
    'TenChat: максимум 7 000 знаков, цель 4 000–5 500, один интент, естественный ключ в заголовке и начале, 2–4 ссылки без спама.',
    JSON.stringify({ platform: 'TenChat', maximum_characters: 7000, target_characters: { minimum: 4000, maximum: 5500 },
      primary_search_intents: 1, primary_keyword_placement: ['title', 'opening'], prohibited: ['link_spam'] }),
    fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixtureTelegramPolicyId, 'editorial_rule', 'editorial.telegram_short_professional',
    'Формат Telegram', 'Только Telegram.', JSON.stringify({ channel: 'telegram' }),
    fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixturePfPolicyId, 'editorial_rule', 'content.public_pf_positive_framing',
    'Позитивная подача ПФ', 'Публичный материал о ПФ раскрывает практическую пользу.',
    JSON.stringify({ applies_to: ['public_articles'] }), fixtureSourceId,
    '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?
    WHERE id IN (?,?,?,?)`)
    .run('2026-08-31T00:00:00.000Z', fixtureArticlePolicyId, fixtureTenChatPolicyId, fixtureTelegramPolicyId, fixturePfPolicyId);
  database.prepare(`INSERT INTO tasks
    (id,type,title,content,data_json,status,author,created_at,updated_at,version)
    VALUES (?,'knowledge_task',?,?,?,'pending','owner',?,?,1)`).run(
    '10000000-0000-4000-a000-000000000006', 'Статьи: ключевые ВЧ-запросы в главном заголовке',
    'В главном заголовке H1 обязательно использовать утверждённый короткий ВЧ-маркер: «накрутка ПФ», «накрутка ПФ Яндекс» или «накрутка поведенческих факторов».',
    JSON.stringify({ project_id: '00000000-0000-4000-a000-000000000102' }),
    '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.close();
  return { directory, databasePath };
}

function tenChatContentQa() {
  const digest = 'a'.repeat(64);
  return {
    checks: [
      { id: 'landing_link_distribution', performed: true, passed: true, result: '4 landing links: beginning=1, body=2, final CTA=1.',
        evidence: { url: 'https://go.mtrhit.ru/', exact_count: 4,
          positions: ['beginning', 'body_1', 'body_2', 'final_cta'], natural_anchors: true, link_spam: false } },
      { id: 'originality_source_overlap', performed: true, passed: true,
        result: 'Local deterministic comparison: maximum normalized source overlap 8.5%; no template match.',
        evidence: { method: 'local_deterministic_source_overlap', content_sha256: digest,
          compared_sources: [{ path: 'work/social/tenchat/reference.md', sha256: 'b'.repeat(64), overlap_percent: 8.5 }],
          max_overlap_percent: 8.5, template_match: false } },
      { id: 'h1_high_frequency_query', performed: true, passed: true,
        result: 'H1 contains the approved high-frequency query “накрутка ПФ”.',
        evidence: { heading: 'Накрутка ПФ', matched_query: 'накрутка ПФ' } },
      { id: 'tenchat_character_count', performed: true, passed: true,
        result: '4,812 characters including spaces and punctuation; within 4,000–5,500 target and below 7,000 maximum.',
        evidence: { character_count: 4812, maximum: 7000, target_minimum: 4000, target_maximum: 5500, within_target: true } },
      { id: 'single_search_intent', performed: true, passed: true, result: 'Exactly one primary intent: controlled PF promotion in Yandex.',
        evidence: { intent_count: 1, primary_intent: 'controlled PF promotion in Yandex' } },
      { id: 'natural_primary_keyword', performed: true, passed: true,
        result: 'Primary keyword appears once in H1 and naturally in the opening paragraph.',
        evidence: { primary_keyword: 'накрутка ПФ', in_title: true, in_opening: true, natural: true } },
      { id: 'link_count_and_spam', performed: true, passed: true, result: '4 relevant links; no repeated-anchor or link-spam pattern.',
        evidence: { link_count: 4, minimum: 2, maximum: 4, link_spam: false } },
    ],
    external_checks: {
      plagiarism: { status: 'not_performed', result: 'No third-party plagiarism service was used; no external plagiarism claim is made.' },
      ai_detection: { status: 'unavailable', result: 'No external AI detector result is available; no AI-authorship claim is made.' },
    },
  };
}

function referenceFixture() {
  const result = fixture();
  const projectDatabasePath = join(result.directory, 'project.sqlite');
  const project = new DatabaseSync(projectDatabasePath);
  const keywords = Array.from({ length: 295 }, (_, index) => `keyword-${index + 1}`);
  const launchAndManagement = ['накрутка ПФ Яндекс', 'как запустить накрутку ПФ', 'настройка проекта ПФ', 'как выбрать запросы ПФ', 'ПФ для сайта'];
  const segments = ['поведенческие факторы для интернет-магазина'];
  const geoCandidates = ['накрутка пф москва'];
  const content = 'Fixture semantic core with 302 approved non-navigation queries.';
  const dataJson = JSON.stringify({ taxonomy: { fixture: keywords, launch_and_management: launchAndManagement, segments,
    geo_candidates_after_demand_validation: geoCandidates }, project_id: '00000000-0000-4000-a000-000000000102',
  keyword_count: keywords.length + launchAndManagement.length + segments.length + geoCandidates.length });
  project.exec(`CREATE TABLE project_storage_metadata (
    singleton INTEGER PRIMARY KEY, project_id TEXT NOT NULL, storage_format INTEGER NOT NULL
  ); CREATE TABLE memory_candidates (
    id TEXT PRIMARY KEY, semantic_key TEXT NOT NULL, title TEXT NOT NULL, content TEXT,
    data_json TEXT, status TEXT NOT NULL, reviewed_at TEXT
  );`);
  project.prepare('INSERT INTO project_storage_metadata VALUES (1,?,1)').run('00000000-0000-4000-a000-000000000102');
  project.prepare(`INSERT INTO memory_candidates(id,semantic_key,title,content,data_json,status,reviewed_at)
    VALUES (?,?,?,?,?,'approved',?)`).run('fixture-semantic-core', 'content.metrichit_semantic_core',
      'Fixture semantic core', content, dataJson, '2026-09-04T00:00:00.000Z');
  project.exec(readFileSync(resolve('data/project-migrations/editorial/007_editorial_agent_pipeline.sql'), 'utf8'));
  project.close();

  const control = new DatabaseSync(result.databasePath);
  const pointer = control.prepare('SELECT metadata_json FROM scoped_memory_records WHERE semantic_key=?').get(SEMANTIC_CORE_REFERENCE_KEY);
  const metadata = JSON.parse(pointer.metadata_json);
  metadata.candidate_id = 'fixture-semantic-core';
  metadata.keyword_count = 302;
  metadata.content_sha256 = createHash('sha256').update(content).digest('hex');
  metadata.data_json_sha256 = createHash('sha256').update(dataJson).digest('hex');
  control.prepare('UPDATE scoped_memory_records SET metadata_json=? WHERE semantic_key=?')
    .run(JSON.stringify(metadata), SEMANTIC_CORE_REFERENCE_KEY);
  control.close();
  return { ...result, projectDatabasePath, keywords, launchAndManagement, segments, geoCandidates, dataJson };
}

function addPublicEditorialSemanticCorePolicy(databasePath) {
  const database = new DatabaseSync(databasePath);
  try {
    database.prepare(`INSERT INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
      VALUES (?,'editorial_rule','content.public_editorial_semantic_core_policy',?,?,?,'pending',?,'owner',?,?,1)`).run(
      '10000000-0000-4000-a000-000000000007', 'Семантическое ядро для всех новых публичных постов и статей',
      'Каждый новый публичный пост или статья начинается с выбора одного компактного не-навигационного кластера.',
      JSON.stringify({ platforms: ['vk', 'telegram', 'tenchat', 'article_platforms', 'future_public_editorial_channels'] }),
      '10000000-0000-4000-a000-000000000001', '2026-09-01T00:00:00.000Z', '2026-09-01T00:00:00.000Z');
    database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by='owner', reviewed_at='2026-09-01T00:00:00.000Z' WHERE id=?")
      .run('10000000-0000-4000-a000-000000000007');
  } finally { database.close(); }
}

function addPublicEditorialIndexationPfTargetPolicy(databasePath) {
  const database = new DatabaseSync(databasePath);
  try {
    database.prepare(`INSERT INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
      VALUES (?,'editorial_rule','content.public_editorial_yandex_indexation_pf_target_policy',?,?,?,'pending',?,'owner',?,?,1)`).run(
      '10000000-0000-4000-a000-000000000008', 'Индексация Яндекса и post-indexation PF-target',
      'Вне Telegram нужна indexation readiness и PF-target eligibility только после verified indexation.',
      JSON.stringify({ excluded_platforms: ['telegram'], priority: 'highest_editorial_objective_for_non_telegram_public_materials' }),
      '10000000-0000-4000-a000-000000000001', '2026-09-01T00:00:00.000Z', '2026-09-01T00:00:00.000Z');
    database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by='owner', reviewed_at='2026-09-01T00:00:00.000Z' WHERE id=?")
      .run('10000000-0000-4000-a000-000000000008');
  } finally { database.close(); }
}

function addPublicEditorialTargetQueryVolumeLadderPolicy(databasePath) {
  const database = new DatabaseSync(databasePath);
  try {
    database.prepare(`INSERT INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
      VALUES (?,'editorial_rule','content.public_editorial_target_query_volume_ladder_policy',?,?,?,'pending',?,'owner',?,?,1)`).run(
      '10000000-0000-4000-a000-000000000010', 'Количество целевых запросов по объёму публичного материала вне Telegram',
      'Вне Telegram число уникальных точных запросов зависит от объёма текста; Telegram исключён.',
      JSON.stringify({ excluded_platforms: ['telegram'], target_query_count: { unique_only: true, primary_included: true } }),
      '10000000-0000-4000-a000-000000000001', '2026-09-01T00:00:00.000Z', '2026-09-01T00:00:00.000Z');
    database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by='owner', reviewed_at='2026-09-01T00:00:00.000Z' WHERE id=?")
      .run('10000000-0000-4000-a000-000000000010');
  } finally { database.close(); }
}

function addGeoDemandGatePolicy(databasePath) {
  const database = new DatabaseSync(databasePath);
  try {
    database.prepare(`INSERT INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
      VALUES (?,'editorial_rule','content.geo_demand_gate_automation',?,?,?,'pending',?,'owner',?,?,1)`).run(
      '10000000-0000-4000-a000-000000000011', 'Owner-gate геосемантики для статей вне Telegram',
      'Геозапросы разрешены только в H2 статьи после явного подтверждения спроса владельцем в execution card.',
      JSON.stringify({ platforms: ['article_platforms', 'tenchat'], excluded_platforms: ['telegram', 'vk'],
        cluster: 'geo_candidates_after_demand_validation', keyword_count: 37,
        required_execution_card_flag: 'geo_demand_owner_confirmed' }),
      '10000000-0000-4000-a000-000000000001', '2026-09-04T00:00:00.000Z', '2026-09-04T00:00:00.000Z');
    database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by='owner', reviewed_at='2026-09-04T00:00:00.000Z' WHERE id=?")
      .run('10000000-0000-4000-a000-000000000011');
  } finally { database.close(); }
}

function addVkPostWritingStandard(databasePath) {
  const database = new DatabaseSync(databasePath);
  try {
    database.prepare(`INSERT INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
      VALUES (?,'editorial_rule','editorial.vk_post_writing_standard',?,?,?,'pending',?,'owner',?,?,1)`).run(
      '10000000-0000-4000-a000-000000000009', 'Стандарт объёма и SEO-структуры новых VK-постов',
      'VK-пост: 1 800–2 800 знаков, с узкими исключениями и QA-обоснованием; ключ в заголовке и начале, один интент и практическая структура.',
      JSON.stringify({ platform: 'VK', body_character_count: { target: { minimum: 1800, maximum: 2800 } }, delivery_validation: ['vk_body_character_count', 'vk_semantic_structure'] }),
      '10000000-0000-4000-a000-000000000001', '2026-09-01T00:00:00.000Z', '2026-09-01T00:00:00.000Z');
    database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by='owner', reviewed_at='2026-09-01T00:00:00.000Z' WHERE id=?")
      .run('10000000-0000-4000-a000-000000000009');
  } finally { database.close(); }
}

function publicEditorialSemanticQa(semantics) {
  return {
    checks: [
      { id: 'semantic_cluster_selection', performed: true, passed: true,
        result: 'Selected one or more documented adjacent non-navigational semantic-core clusters.',
        evidence: { selected_clusters: semantics.selectedClusters, adjacent_cluster_rationale: semantics.adjacentClusterRationale ?? null, primary_target_query: semantics.primaryTargetQuery,
          secondary_target_queries: semantics.secondaryTargetQueries, user_intent: semantics.userIntent, platform: semantics.platform,
          core_reference: SEMANTIC_CORE_REFERENCE_KEY, non_navigational: true } },
      { id: 'target_queries_approved_core', performed: true, passed: true,
        result: 'Every declared target query is verbatim in the selected approved semantic-core clusters.',
        evidence: { core_reference: SEMANTIC_CORE_REFERENCE_KEY, selected_clusters: semantics.selectedClusters,
          primary_target_query: semantics.primaryTargetQuery, secondary_target_queries: semantics.secondaryTargetQueries,
          target_queries_match_card: true, all_target_queries_approved: true, all_target_queries_in_selected_clusters: true,
          duplicate_target_queries: false, keyword_stuffing: false } },
      { id: 'primary_query_prominence', performed: true, passed: true,
        result: 'Primary query is natural in the required prominent location.',
        evidence: { primary_target_query: semantics.primaryTargetQuery, platform: semantics.platform,
          location: semantics.format === 'article' ? 'h1' : 'headline', natural: true, keyword_stuffing: false } },
      { id: 'adjacent_clusters_one_intent', performed: true, passed: true,
        result: 'The material serves one documented intent across the selected adjacent clusters.',
        evidence: { selected_clusters: semantics.selectedClusters, adjacent_cluster_rationale: semantics.adjacentClusterRationale ?? null,
          user_intent: semantics.userIntent, clusters_are_adjacent: true, content_serves_selected_intent: true, unrelated_clusters_mixed: false } },
      { id: 'geo_demand_verification', performed: true, passed: true,
        result: 'No geo candidate is used.',
        evidence: { geo_candidate: false, demand_verification_required: true, demand_verified: false, verification_reference: null } },
    ],
    external_checks: {
      plagiarism: { status: 'not_performed', result: 'No third-party plagiarism service was used; no external plagiarism claim is made.' },
      ai_detection: { status: 'unavailable', result: 'No external AI detector result is available; no AI-authorship claim is made.' },
    },
  };
}

function publicEditorialSemanticQaWithVolumeLadder(semantics, characterCount, countRationale = null) {
  const contentQa = publicEditorialSemanticQa(semantics);
  const targetQueries = [semantics.primaryTargetQuery, ...semantics.secondaryTargetQueries];
  const band = [
    [1800, 2800, 8, 12], [2801, 5000, 10, 16], [5001, 7000, 14, 20], [7001, 9000, 18, 26],
  ].find(([minimum, maximum]) => characterCount >= minimum && characterCount <= maximum) ?? null;
  contentQa.checks.push({ id: 'target_query_volume_ladder', performed: true, passed: true,
    result: 'The unique exact target-query count matches the applicable body-length band.',
    evidence: {
      character_count: characterCount, count_scope: 'russian_body_excluding_internal_metadata_and_urls',
      primary_target_query: semantics.primaryTargetQuery, secondary_target_queries: semantics.secondaryTargetQueries,
      unique_target_query_count: targetQueries.length, required_minimum: band?.[2] ?? null,
      required_maximum: band?.[3] ?? null, count_rationale: countRationale,
      all_secondary_target_queries_natural_in_body: true, keyword_stuffing: false,
    } });
  return contentQa;
}

function articleEditorialSemanticQaWithVolumeLadder(semantics, characterCount, countRationale = null) {
  const contentQa = publicEditorialSemanticQaWithVolumeLadder(semantics, characterCount, countRationale);
  const articleCheckIds = new Set(['landing_link_distribution', 'originality_source_overlap', 'h1_high_frequency_query']);
  contentQa.checks.push(...tenChatContentQa().checks.filter((check) => articleCheckIds.has(check.id)));
  return contentQa;
}

function publicEditorialIndexationQa(indexation) {
  const verified = indexation.targetUrlStatus === 'verified_indexed';
  return [
    { id: 'format_specific_indexation_readiness', performed: true, passed: true,
      result: 'Platform-appropriate indexation and retrievability checks passed.',
      evidence: { platform: indexation.platform, format: indexation.format,
        seo_indexation_objective: indexation.seoIndexationObjective,
        indexability_retrievability_checks: indexation.indexabilityRetrievabilityChecks, passed: true } },
    { id: 'post_indexation_pf_target_status', performed: true, passed: true,
      result: 'The material is eligible for a later PF campaign only after verified indexation and separate owner approval.',
      evidence: { target_url_status: indexation.targetUrlStatus,
        post_indexation_evidence_status: indexation.postIndexationEvidenceStatus,
        indexation_verified: verified, indexation_evidence: verified ? 'Yandex index verification record' : null,
        eligible_for_later_pf_campaign: verified, eligible_only_after_verified_indexation: true,
        pf_campaign_owner_approval_required: true, pf_campaign_auto_authorized: false } },
  ];
}

function publicEditorialQa(semantics, indexation = null) {
  const qa = publicEditorialSemanticQa(semantics);
  if (indexation) qa.checks.push(...publicEditorialIndexationQa(indexation));
  return qa;
}

function vkPostQa(semantics, characterCount, lengthBand, rationale) {
  const qa = publicEditorialQa(semantics);
  qa.checks.push(
    { id: 'vk_body_character_count', performed: true, passed: true,
      result: `VK post body contains ${characterCount} Russian characters excluding metadata and URLs.`,
      evidence: { character_count: characterCount, count_scope: 'russian_post_body_excluding_internal_metadata_and_urls',
        length_band: lengthBand, rationale, not_extended_for_seo_only: true } },
    { id: 'vk_semantic_structure', performed: true, passed: true,
      result: 'One intent is naturally sustained across the selected clusters from the headline through the CTA.',
      evidence: { primary_target_query: semantics.primaryTargetQuery, selected_clusters: semantics.selectedClusters,
        user_intent: semantics.userIntent, in_headline: true, in_opening_paragraph: true, natural_mentions_total: 2,
        keyword_stuffing: false, all_sections_serve_selected_query: true, opening_answers_query: true,
        useful_subheads_or_checklist: true, concrete_practical_details: true, practical_conclusion: true,
        natural_cta: true, padding_or_repetition: false, unsupported_seo_claims: false } },
  );
  return qa;
}

test('P0/P1: canonical contract, passports and fail-closed ownership are present', () => {
  const { directory, databasePath } = fixture();
  try {
    const specification = readFileSync(resolve('documents/structured-memory.md'), 'utf8');
    assert.match(specification, /147 579 байт/);
    const db = new DatabaseSync(databasePath);
    assert.deepEqual(db.prepare('SELECT id FROM scope_passports ORDER BY id').all().map((row) => row.id),
      [SCOPE_IDS.core, SCOPE_IDS.metrichit, SCOPE_IDS.editorial, SCOPE_IDS.panel].sort());
    assert.equal(db.prepare('SELECT count(*) count FROM scoped_memory_records WHERE scope_id IS NULL').get().count, 0);
    db.close();
    const queued = registerScopedRecord(databasePath, { semanticKey: 'ambiguous.fixture', title: 'Ambiguous', content: 'x' });
    assert.equal(queued.status, 'queued');
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(readOnly.prepare("SELECT count(*) count FROM unresolved_memory_queue WHERE status='pending'").get().count, 1);
    assert.equal(resolveScopedMemory(readOnly, SCOPE_IDS.editorial, 'editorial').records.some((row) => row.semantic_key === 'ambiguous.fixture'), false);
    readOnly.close();
    const task = createTaskScope(databasePath, { taskId: 'fixture-1', parentScopeId: SCOPE_IDS.editorial, name: 'Fixture task', summary: 'Task-local temporary scope.' });
    const taskDb = new DatabaseSync(databasePath, { readOnly: true });
    assert.deepEqual(scopeNames(taskDb, task.id), ['Ядро', 'MetricHit', 'Редакция', 'Fixture task']);
    taskDb.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 15, retryDelay: 100 }); }
});

test('P2: inheritance is deterministic, core prohibition is sticky, superseded and sibling memory do not leak', () => {
  const { directory, databasePath } = fixture();
  try {
    const stored = registerScopedRecord(databasePath, {
      id: 'memory:test:old', semanticKey: 'editorial.revision', scopeId: SCOPE_IDS.editorial,
      layer: 'working', recordType: 'decision', title: 'Old', content: 'old',
      sourceRef: 'test', validFrom: '2026-08-30T00:00:00.000Z', taskTypes: ['editorial'],
    });
    assert.equal(stored.status, 'stored');
    supersedeScopedRecord(databasePath, 'memory:test:old', {
      id: 'memory:test:new', semanticKey: 'editorial.revision', scopeId: SCOPE_IDS.editorial,
      layer: 'working', recordType: 'decision', title: 'New', content: 'new', sourceRef: 'test',
      validFrom: '2026-08-31T00:00:00.000Z', taskTypes: ['editorial'],
    });
    const db = new DatabaseSync(databasePath);
    try {
      assert.throws(() => db.prepare(`INSERT INTO scoped_memory_records
        (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,rule_effect,created_at,updated_at)
        VALUES ('memory:test:override','governance.owner_gates',?,'permanent','rule','active','Override','allow','test','2026-08-31','allow','2026-08-31','2026-08-31')`).run(SCOPE_IDS.editorial), /core prohibition/);
      const active = resolveScopedMemory(db, SCOPE_IDS.editorial, 'editorial').records;
      assert.equal(active.find((row) => row.semantic_key === 'editorial.revision').content, 'new');
      assert.equal(active.some((row) => row.semantic_key === 'panel.ux_contract_required'), false);
      const history = resolveScopedMemory(db, SCOPE_IDS.editorial, 'editorial', { includeHistory: true }).records;
      assert.equal(history.some((row) => row.id === 'memory:test:old'), false, 'superseded revision is not selected over its current semantic key');
    } finally { db.close(); }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('P3: router asks one question for material ambiguity and audit stores no prompt or reasoning', () => {
  const { directory, databasePath } = fixture();
  try {
    const db = new DatabaseSync(databasePath);
    const ambiguous = routeTask(db, { text: 'Проверь панель' });
    assert.equal(ambiguous.outcome, 'needs_clarification');
    assert.match(ambiguous.question, /Уточните один scope/);
    db.close();
    const result = compileContextPack(databasePath, { text: 'Проверь панель' });
    assert.equal(result.pack, null);
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    const audit = readOnly.prepare('SELECT * FROM scope_routing_audit').get();
    assert.equal(audit.outcome, 'needs_clarification');
    assert.equal(Object.hasOwn(audit, 'task_text'), false);
    assert.equal(Object.hasOwn(audit, 'reasoning'), false);
    readOnly.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('article_pipeline_trigger creates a platform card and launches Migration 007 sequentially', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    const compiled = compileContextPack(databasePath, {
      text: 'Напиши новую статью для Sostav/SBlogs', projectDatabasePath,
      taskType: 'code', taskBrief: { result: undefined, scope: undefined, acceptance: undefined },
    });
    assert.equal(compiled.route.outcome, 'routed');
    assert.equal(compiled.route.scopeId, SCOPE_IDS.editorial);
    assert.equal(compiled.route.taskType, 'editorial');
    assert.equal(compiled.route.platform.name, 'Sostav/SBlogs');
    assert.equal(compiled.route.platform.contour, 'work/articles');
    const card = compiled.pack.payload.execution_card;
    assert.equal(card.scope[0], 'work/articles');
    assert.equal(card.editorial_pipeline.pipeline_id, 'metrichit.editorial.pipeline.v1');
    assert.equal(card.editorial_pipeline.launch_directive, 'start');
    assert.equal(card.editorial_pipeline.execution_mode, 'isolated_sequential');
    assert.deepEqual(card.editorial_pipeline.stages.map((stage) => stage.profile_id), [
      'metrichit.editorial.planner.v1',
      'metrichit.editorial.architect.v1',
      'metrichit.editorial.writer.v1',
      'metrichit.editorial.designer.v1',
      'metrichit.editorial.validator.v1',
    ]);
    assert.ok(card.editorial_pipeline.stages.every((stage) => stage.policy.semantic_core.keyword_count === 302));
    assert.equal(card.editorial_pipeline.empty_topic_planner_assignment.executor_profile, 'metrichit.editorial.planner.v1');
    assert.equal(card.editorial_pipeline.empty_topic_planner_assignment.status, 'ready');
    assert.equal(card.editorial_pipeline.empty_topic_planner_assignment.owner_question, 'prohibited');
    assert.equal(card.editorial_pipeline.empty_topic_planner_assignment.published_archive_overlap.scanned, true);
    assert.equal(card.editorial_pipeline.empty_topic_planner_assignment.structure_options.length, 3);
    assert.deepEqual(card.editorial_pipeline.empty_topic_planner_assignment.selected_structure,
      card.editorial_pipeline.empty_topic_planner_assignment.structure_options[0]);
    assert.equal(card.editorial_pipeline.empty_topic_planner_assignment.structure_selection,
      'deterministic_priority_first');
    const allowedH1 = new Set(['Накрутка ПФ', 'Накрутка ПФ Яндекс', 'Накрутка поведенческих факторов']);
    assert.ok(card.editorial_pipeline.empty_topic_planner_assignment.structure_options.every((option) =>
      allowedH1.has(option.h1) && option.title === option.h1
      && !/\b(?:руководство|диагностика|софт)\b/iu.test(option.h1)));
    assert.ok(card.editorial_pipeline.stages.every((stage) => stage.hotfix.id === 'editorial.empty_topic.autoplanning.v1'));
    assert.equal(card.editorial_semantics, null);
    assert.equal(card.delivery_qa, null);

    const project = new DatabaseSync(projectDatabasePath);
    project.prepare(`INSERT INTO memory_candidates(id,semantic_key,title,content,data_json,status,reviewed_at)
      VALUES (?,'content.metrichit_semantic_core','Conflicting core','Fixture conflict',?,'approved',?)`)
      .run('fixture-semantic-core-conflict', dataJson, '2026-09-05T00:00:00.000Z');
    project.close();
    const blocked = compileContextPack(databasePath, { text: 'Напиши новую статью для Sostav/SBlogs', projectDatabasePath });
    const assignment = blocked.pack.payload.execution_card.editorial_pipeline.empty_topic_planner_assignment;
    assert.equal(blocked.route.outcome, 'routed');
    assert.equal(blocked.pack.payload.execution_card.editorial_pipeline.launch_directive, 'blocked');
    assert.equal(assignment.status, 'blocked');
    assert.equal(assignment.system_error.code, 'E_AMBIGUOUS_TOPIC');
    assert.equal(assignment.system_error.available_hf_markers.length, 3);

    const unsupported = compileContextPack(databasePath, {
      text: 'Напиши новую статью для Avito', projectDatabasePath,
    });
    assert.equal(unsupported.route.outcome, 'needs_clarification');
    assert.equal(unsupported.pack, null);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('article image follow-up creates a new linked card from the latest closed article', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    addPublicEditorialSemanticCorePolicy(databasePath);
    addPublicEditorialIndexationPfTargetPolicy(databasePath);
    const semantics = {
      selectedClusters: ['launch_and_management'], adjacentClusterRationale: null,
      primaryTargetQuery: 'накрутка ПФ Яндекс',
      secondaryTargetQueries: ['как запустить накрутку ПФ'],
      userIntent: 'Подготовить страницу и управляемо запустить ПФ-продвижение.',
      platform: 'Oborot.ru', format: 'article',
    };
    const source = compileContextPack(databasePath, {
      text: 'Подготовь статью для Oborot.ru', projectDatabasePath,
      taskBrief: {
        result: 'Последняя статья Oborot подготовлена',
        scope: [
          'work/articles/drafts/2026-09-04-oborot-example.md',
          'work/articles/assets/2026-09-04-oborot-cover.png',
          'work/articles/assets/2026-09-04-oborot-inline.png',
        ],
        firstCheck: 'editorial-check', acceptance: ['source_ready'],
        forbiddenChanges: ['publication'], editorialSemantics: semantics,
        editorialIndexation: { seoIndexationObjective: 'Индексация статьи в Яндексе по утверждённой семантике.' },
      },
    });
    const database = new DatabaseSync(databasePath);
    const sourcePayload = source.pack.payload;
    sourcePayload.terminal_outcome = 'delivered';
    database.prepare("UPDATE context_packs SET status='closed',closed_at=?,payload_json=? WHERE id=?")
      .run('2026-09-04T10:00:00.000Z', JSON.stringify(sourcePayload), source.pack.id);
    const panelPayload = {
      execution_card: { result: 'Unrelated panel result', scope: ['src/panel.js'] },
      terminal_outcome: 'delivered', unrelated_secret: 'must-not-be-inherited',
    };
    database.prepare(`INSERT INTO context_packs
      (id,scope_id,task_type,compiler_version,input_hash,payload_json,compiled_bytes,status,created_at,closed_at)
      VALUES (?,?,?,?,?,?,?,'closed',?,?)`).run(
      'fixture-newer-panel-pack', SCOPE_IDS.panel, 'ui', 1, 'panel-hash', JSON.stringify(panelPayload),
      Buffer.byteLength(JSON.stringify(panelPayload)), '2026-09-04T11:00:00.000Z', '2026-09-04T11:01:00.000Z',
    );
    database.close();

    const text = 'Для последней статьи оборота создай новые картинки по новым правилам. Старые картинки удали';
    const sourceCheckDatabase = new DatabaseSync(databasePath, { readOnly: true });
    const sourceCheck = sourceCheckDatabase.prepare('SELECT status,payload_json FROM context_packs WHERE id=?').get(source.pack.id);
    assert.equal(sourceCheck.status, 'closed');
    assert.equal(JSON.parse(sourceCheck.payload_json).execution_card.editorial_semantics.format, 'article');
    sourceCheckDatabase.close();
    const compiled = compileContextPack(databasePath, { text, projectDatabasePath });
    const card = compiled.pack.payload.execution_card;
    assert.notEqual(compiled.pack.id, source.pack.id);
    assert.equal(compiled.pack.status, 'open');
    assert.deepEqual(card.editorial_semantics, sourcePayload.execution_card.editorial_semantics);
    assert.deepEqual(card.editorial_indexation, sourcePayload.execution_card.editorial_indexation);
    assert.equal(card.editorial_revision.source_context_pack_id, source.pack.id);
    assert.equal(card.editorial_revision.source_status, 'closed');
    assert.equal(card.editorial_revision.source_terminal_outcome, 'delivered');
    assert.equal(card.editorial_revision.article_path, 'work/articles/drafts/2026-09-04-oborot-example.md');
    assert.deepEqual(card.editorial_revision.asset_paths, [
      'work/articles/assets/2026-09-04-oborot-cover.png',
      'work/articles/assets/2026-09-04-oborot-inline.png',
    ]);
    assert.equal(card.editorial_revision.owner_authorizations.delete_replaced_assets, true);
    assert.equal(JSON.stringify(card).includes('unrelated_secret'), false);
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(readOnly.prepare('SELECT status FROM context_packs WHERE id=?').get(source.pack.id).status, 'closed');
    readOnly.close();

    const cli = JSON.parse(execFileSync(process.execPath, [resolve('scripts/structured-memory.mjs'), 'compile',
      '--db', databasePath, '--project-db', projectDatabasePath, '--scope', SCOPE_IDS.editorial,
      '--text', text], { encoding: 'utf8' }));
    assert.equal(cli.pack.status, 'open');
    assert.equal(cli.pack.payload.execution_card.editorial_revision.source_context_pack_id, source.pack.id);
    assert.deepEqual(cli.pack.payload.execution_card.editorial_semantics, card.editorial_semantics);
  } finally {
    try { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
    catch (error) { if (error?.code !== 'EBUSY') throw error; }
  }
});

test('P4/P5: compiler is stable, smaller than baseline and isolates Editorial from Panel', () => {
  const { directory, databasePath } = fixture();
  try {
    const db = new DatabaseSync(databasePath, { readOnly: true });
    const agents = readFileSync(resolve('AGENTS.md'), 'utf8');
    const editorialCard = { result: 'Материал', scope: ['work/articles'], firstCheck: 'editorial-check', acceptance: ['ready'], forbiddenChanges: ['publication'] };
    const panelCard = { result: 'Панель', scope: ['operator-panel'], firstCheck: 'ui-check', acceptance: ['visible'], forbiddenChanges: ['runtime'] };
    const editorialA = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: agents, taskBrief: editorialCard });
    const editorialB = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: agents, taskBrief: editorialCard });
    const panel = compileDeterministicContext(db, { scopeId: SCOPE_IDS.panel, taskType: 'ui', agentsContent: agents, taskBrief: panelCard });
    assert.deepEqual(editorialA, editorialB);
    assert.deepEqual(editorialA.passports.map((item) => item.name), ['Ядро', 'MetricHit', 'Редакция']);
    assert.deepEqual(panel.passports.map((item) => item.name), ['Ядро', 'MetricHit', 'Панель']);
    assert.equal(editorialA.rules.some((item) => item.semantic_key.startsWith('panel.')), false);
    assert.equal(panel.rules.some((item) => item.semantic_key.startsWith('editorial.')), false);
    assert.deepEqual(editorialA.references.map((item) => item.semantic_key), [SEMANTIC_CORE_REFERENCE_KEY]);
    assert.deepEqual(editorialA.expanded_references, []);
    assert.deepEqual(panel.references, []);
    assert.deepEqual(panel.expanded_references, []);
    assert.equal(editorialA.execution_card.task_type, 'editorial');
    assert.equal(editorialA.execution_card.mandatory_rules.some((item) => item.source === 'AGENTS.md'), true);
    assert.equal(editorialA.execution_card.mandatory_rules.some((item) => item.semantic_key.startsWith('panel.')), false);
    assert.equal(panel.execution_card.mandatory_rules.some((item) => item.semantic_key.startsWith('editorial.')), false);
    assert.ok(Buffer.byteLength(JSON.stringify(editorialA)) < 147579);
    db.close();
    const compiled = compileContextPack(databasePath, { text: 'Подготовь статью MetricHit', taskBrief: {
      result: 'Проверенный материал', scope: ['work/articles'], forbiddenChanges: ['publication'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['context_is_minimal'],
    } });
    assert.equal(compiled.route.scopeId, SCOPE_IDS.editorial);
    assert.equal(compiled.pack.status, 'open');
    assert.equal(compiled.pack.payload.task_brief.result, 'Проверенный материал');
    assert.deepEqual(compiled.pack.payload.task_brief.forbidden_changes, ['publication']);
    assert.match(compiled.pack.payload.execution_card_hash, /^[a-f0-9]{64}$/);
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id), /delivery validation failed/);
    assert.equal(closeContextPack(databasePath, compiled.pack.id, {
      result: 'Материал проверен', checks: ['node --test tests/structured-memory.test.mjs'],
      satisfiedAcceptance: ['context_is_minimal'], scopeCompliance: true, forbiddenChangesObserved: [],
      contentQa: tenChatContentQa(),
    }).status, 'closed');
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(readOnly.prepare('SELECT status FROM context_packs WHERE id=?').get(compiled.pack.id).status, 'closed');
    assert.equal(readOnly.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
    assert.deepEqual(readOnly.prepare('PRAGMA foreign_key_check').all(), []);
    readOnly.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('delivery validation rejects a changed execution card', () => {
  const { directory, databasePath } = fixture();
  try {
    const compiled = compileContextPack(databasePath, { text: 'Исправь Python модуль MetricHit', taskBrief: {
      result: 'Исправление', scope: ['scripts'], firstCheck: 'code-check',
      acceptance: ['fixed'], forbiddenChanges: ['ui'],
    } });
    const database = new DatabaseSync(databasePath);
    const row = database.prepare('SELECT payload_json FROM context_packs WHERE id=?').get(compiled.pack.id);
    const payload = JSON.parse(row.payload_json);
    payload.execution_card.acceptance = ['changed'];
    database.prepare('UPDATE context_packs SET payload_json=? WHERE id=?').run(JSON.stringify(payload), compiled.pack.id);
    database.close();
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, {
      result: 'done', checks: ['code-check'], satisfiedAcceptance: ['changed'],
      scopeCompliance: true, forbiddenChangesObserved: [],
    }), /execution_card_hash_mismatch/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('abandoned context packs are audited, idempotent and cannot be reported as delivered', () => {
  const { directory, databasePath } = fixture();
  try {
    const compiled = compileContextPack(databasePath, { text: 'Исправь Python модуль MetricHit', taskBrief: {
      result: 'Исправление', scope: ['scripts'], firstCheck: 'code-check',
      acceptance: ['fixed'], forbiddenChanges: ['ui'],
    } });
    const abandoned = abandonContextPack(databasePath, compiled.pack.id, {
      reason: 'No active executor remains.', owner: 'integrity-repair-executor',
    });
    assert.equal(abandoned.status, 'closed');
    assert.equal(abandoned.terminal_outcome, 'abandoned');
    assert.equal(abandoned.changed, true);
    assert.equal(abandonContextPack(databasePath, compiled.pack.id, {
      reason: 'No active executor remains.', owner: 'integrity-repair-executor',
    }).changed, false);
    const fakeClose = closeContextPack(databasePath, compiled.pack.id, {
      result: 'fake', checks: ['code-check'], satisfiedAcceptance: ['fixed'],
      scopeCompliance: true, forbiddenChangesObserved: [],
    });
    assert.equal(fakeClose.changed, false);
    assert.equal(fakeClose.terminal_outcome, 'abandoned');
    const database = new DatabaseSync(databasePath, { readOnly: true });
    const payload = JSON.parse(database.prepare('SELECT payload_json FROM context_packs WHERE id=?').get(compiled.pack.id).payload_json);
    assert.equal(payload.terminal_outcome, 'abandoned');
    assert.equal(payload.delivery_validation, undefined);
    assert.equal(database.prepare("SELECT count(*) count FROM audit_log WHERE type='context_pack_terminal_event' AND entity_id=?")
      .get(compiled.pack.id).count, 1);
    database.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('integrity repair terminalizes exactly the 11 approved orphan IDs and replay is a no-op', () => {
  const central = fixture();
  const project = fixture();
  try {
    const insert = (databasePath, ids) => {
      const database = new DatabaseSync(databasePath);
      const payload = JSON.stringify({ execution_card: { result: 'stale' } });
      for (const id of ids) database.prepare(`INSERT INTO context_packs
        (id,scope_id,task_type,compiler_version,input_hash,payload_json,compiled_bytes,status,created_at)
        VALUES (?,'scope:project:metrichit','code',1,?,?,?,'open','2026-09-01T00:00:00.000Z')`)
        .run(id, 'a'.repeat(64), payload, Buffer.byteLength(payload));
      database.close();
    };
    insert(central.databasePath, CENTRAL_ORPHAN_PACK_IDS);
    insert(project.databasePath, PROJECT_ORPHAN_PACK_IDS);
    const first = repairOrphanContextPacks(central.databasePath, project.databasePath);
    assert.equal(first.centralPacks.length, 10);
    assert.equal(first.projectPacks.length, 1);
    assert.equal([...first.centralPacks, ...first.projectPacks].every((item) => item.changed), true);
    const replay = repairOrphanContextPacks(central.databasePath, project.databasePath);
    assert.equal([...replay.centralPacks, ...replay.projectPacks].every((item) => !item.changed), true);
    for (const [databasePath, ids] of [[central.databasePath, CENTRAL_ORPHAN_PACK_IDS], [project.databasePath, PROJECT_ORPHAN_PACK_IDS]]) {
      const database = new DatabaseSync(databasePath, { readOnly: true });
      const rows = database.prepare(`SELECT id,payload_json FROM context_packs
        WHERE id IN (${ids.map(() => '?').join(',')}) ORDER BY id`).all(...ids);
      assert.equal(rows.length, ids.length);
      assert.equal(rows.every((row) => JSON.parse(row.payload_json).terminal_outcome === 'abandoned'), true);
      assert.equal(database.prepare("SELECT count(*) count FROM audit_log WHERE type='context_pack_terminal_event'").get().count, ids.length);
      database.close();
    }
  } finally {
    rmSync(central.directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
    rmSync(project.directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
  }
});

test('Timeweb editorial registry keeps an exact existing draft and supporting references', () => {
  const draftRef = 'work/articles/drafts/2026-08-29-timeweb-cloud-pf-service-selection.md';
  const draft = readFileSync(resolve(draftRef));
  assert.equal(createHash('sha256').update(draft).digest('hex'),
    '7e37b52282427ada420734e4b31071ab23c3832a9e73842317b240dcb2495e37');
  assert.equal(existsSync(resolve('work/articles/assets/2026-08-29-timeweb-pf-service-hero-v1.png')), true);
  assert.equal(existsSync(resolve('work/articles/assets/2026-08-29-timeweb-pf-service-flow-v1.png')), true);
  const project = new DatabaseSync(resolve(
    'data/projects/00000000-0000-4000-a000-000000000102/project.sqlite'), { readOnly: true });
  const row = project.prepare(`SELECT content_ref,status,workflow_stage,plan_ref
    FROM editorial_materials WHERE id=?`).get('7d4b6d6e-3576-4d55-be77-4fd710b3c9b5');
  project.close();
  assert.equal(row.content_ref, draftRef);
  assert.equal(row.status, 'draft');
  assert.equal(row.workflow_stage, 'draft');
  assert.equal(existsSync(resolve(row.plan_ref)), true);
});

test('global execution gate fails closed for incomplete cards and validates all supported task types', () => {
  const { directory, databasePath } = fixture();
  try {
    assert.throws(() => compileContextPack(databasePath, { text: 'Обнови документацию MetricHit' }), /execution card is incomplete/);
    const rejectedDb = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(rejectedDb.prepare("SELECT outcome FROM scope_routing_audit WHERE outcome='rejected'").get().outcome, 'rejected');
    assert.equal(rejectedDb.prepare('SELECT count(*) count FROM context_packs').get().count, 0);
    rejectedDb.close();

    const scenarios = [
      ['editorial', 'Подготовь статью MetricHit', SCOPE_IDS.editorial],
      ['code', 'Исправь Python модуль MetricHit', SCOPE_IDS.metrichit],
      ['docs', 'Обнови документацию MetricHit', SCOPE_IDS.metrichit],
      ['research', 'Исследуй семантическое ядро MetricHit', SCOPE_IDS.editorial],
      ['ui', 'Исправь UI operator panel MetricHit', SCOPE_IDS.panel],
    ];
    for (const [taskType, text, scopeId] of scenarios) {
      const acceptance = [`${taskType}_accepted`];
      const firstCheck = `${taskType}-check`;
      const compiled = compileContextPack(databasePath, { text, taskBrief: {
        result: `${taskType} result`, scope: [`${taskType} scope`], firstCheck,
        acceptance, forbiddenChanges: ['out of scope'],
      } });
      assert.equal(compiled.route.taskType, taskType);
      assert.equal(compiled.route.scopeId, scopeId);
      assert.equal(compiled.pack.payload.execution_card.target_scope, scopeId);
      assert.throws(() => closeContextPack(databasePath, compiled.pack.id, {
        result: 'done', checks: [firstCheck], satisfiedAcceptance: [], scopeCompliance: true, forbiddenChangesObserved: [],
      }), /acceptance_evidence/);
      const closed = closeContextPack(databasePath, compiled.pack.id, {
        result: 'done', checks: [firstCheck], satisfiedAcceptance: acceptance,
        scopeCompliance: true, forbiddenChangesObserved: [],
        contentQa: taskType === 'editorial' ? tenChatContentQa() : null,
      });
      assert.equal(closed.validation.scope_compliant, true);
    }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('editorial TenChat gate includes approved unscoped requirements and requires exact local content QA', () => {
  const { directory, databasePath } = fixture();
  try {
    const taskBrief = {
      result: 'Проверенный TenChat-материал', scope: ['work/social/tenchat'],
      firstCheck: 'node --test tests/structured-memory.test.mjs',
      acceptance: ['tenchat_ready'], forbiddenChanges: ['publication'],
    };
    const compiled = compileContextPack(databasePath, {
      text: 'Подготовь статью TenChat о накрутке ПФ для MetricHit', taskBrief,
    });
    const card = compiled.pack.payload.execution_card;
    const keys = card.mandatory_rules.map((item) => item.semantic_key);
    assert.ok(keys.includes('content.editorial_article_preparation_policy'));
    assert.ok(keys.includes('content.public_pf_positive_framing'));
    assert.ok(keys.includes('owner.editorial.h1_high_frequency_query'));
    assert.ok(keys.includes('editorial.tenchat_format_and_search_policy'));
    assert.equal(keys.includes('editorial.telegram_short_professional'), false);
    assert.match(card.mandatory_rules.find((item) => item.semantic_key === 'content.editorial_article_preparation_policy').content,
      /четыре естественные ссылки/);
    assert.match(card.mandatory_rules.find((item) => item.semantic_key === 'owner.editorial.h1_high_frequency_query').content,
      /Накрутка ПФ.*Накрутка ПФ Яндекс.*Накрутка поведенческих факторов/);
    assert.deepEqual(card.delivery_qa.checks.map((item) => item.id), [
      'landing_link_distribution', 'originality_source_overlap', 'h1_high_frequency_query',
      'tenchat_character_count', 'single_search_intent', 'natural_primary_keyword', 'link_count_and_spam',
    ]);

    const baseDelivery = {
      result: 'Материал проверен', checks: [taskBrief.firstCheck],
      satisfiedAcceptance: taskBrief.acceptance, scopeCompliance: true, forbiddenChangesObserved: [],
    };
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, baseDelivery), /editorial_content_qa_missing/);
    const incompleteQa = tenChatContentQa();
    incompleteQa.checks = incompleteQa.checks.filter((item) => item.id !== 'originality_source_overlap');
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, { ...baseDelivery, contentQa: incompleteQa }),
      /editorial_content_qa_incomplete:originality_source_overlap/);
    const falseExternalClaim = tenChatContentQa();
    falseExternalClaim.external_checks.plagiarism.status = 'passed';
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, { ...baseDelivery, contentQa: falseExternalClaim }),
      /editorial_external_check_claim:plagiarism/);
    const closed = closeContextPack(databasePath, compiled.pack.id, { ...baseDelivery, contentQa: tenChatContentQa() });
    assert.equal(closed.status, 'closed');
    assert.equal(closed.validation.content_qa.local_deterministic_checks
      .find((item) => item.id === 'originality_source_overlap').evidence.max_overlap_percent, 8.5);
    assert.equal(closed.validation.content_qa.external_checks.plagiarism.status, 'not_performed');

    const unrelated = compileContextPack(databasePath, { text: 'Исправь UI operator panel MetricHit', taskBrief: {
      result: 'UI', scope: ['operator-panel'], firstCheck: 'ui-check', acceptance: ['visible'], forbiddenChanges: ['editorial'],
    } });
    assert.equal(unrelated.pack.payload.execution_card.mandatory_rules
      .some((item) => item.semantic_key === 'content.editorial_article_preparation_policy'), false);
    assert.equal(unrelated.pack.payload.execution_card.delivery_qa, null);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('editorial H1 validation accepts every approved exact marker and rejects diluted or singular forms', () => {
  const { directory, databasePath } = fixture();
  try {
    const taskBrief = {
      result: 'Проверенный материал', scope: ['work/social/tenchat'],
      firstCheck: 'node --test tests/structured-memory.test.mjs',
      acceptance: ['ready'], forbiddenChanges: ['publication'],
    };
    const delivery = (qa) => ({ result: 'Материал проверен', checks: [taskBrief.firstCheck],
      satisfiedAcceptance: taskBrief.acceptance, scopeCompliance: true, forbiddenChangesObserved: [], contentQa: qa });
    for (const heading of ['Накрутка ПФ', 'Накрутка ПФ Яндекс', 'Накрутка поведенческих факторов']) {
      const compiled = compileContextPack(databasePath, { text: 'Подготовь статью TenChat о накрутке ПФ', taskBrief });
      const qa = tenChatContentQa();
      qa.checks.find((item) => item.id === 'h1_high_frequency_query').evidence = { heading, matched_query: heading };
      assert.equal(closeContextPack(databasePath, compiled.pack.id, delivery(qa)).status, 'closed');
    }
    for (const heading of ['Накрутка поведенческого фактора', 'Накрутка ПФ: практическое руководство']) {
      const compiled = compileContextPack(databasePath, { text: 'Подготовь статью TenChat о накрутке ПФ', taskBrief });
      const qa = tenChatContentQa();
      qa.checks.find((item) => item.id === 'h1_high_frequency_query').evidence = { heading, matched_query: heading };
      assert.throws(() => closeContextPack(databasePath, compiled.pack.id, delivery(qa)), /h1_high_frequency_query/);
    }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('confirmed editorial publication delivery requires a declared and recorded project fact', () => {
  const { directory, databasePath } = fixture();
  try {
    const brief = {
      result: 'Факт публикации Oborot сверён', scope: ['data/projects/editorial'],
      firstCheck: 'project-editorial-record-publication', acceptance: ['publication_recorded'],
      forbiddenChanges: ['external publication'],
    };
    const text = 'Зафиксируй подтверждённую публикацию Oborot';
    assert.throws(() => compileContextPack(databasePath, { text, taskBrief: brief }),
      /publication_reconciliation\.publications/);

    const missing = compileContextPack(databasePath, { text, taskBrief: {
      ...brief, publicationReconciliation: { publications: [{
        platform: 'Oborot', title: 'Несуществующая публикация', publishedAt: '2026-09-03',
        url: 'https://oborot.ru/blogs/missing.html',
      }] },
    } });
    const delivery = {
      result: brief.result, checks: [brief.firstCheck], satisfiedAcceptance: brief.acceptance,
      scopeCompliance: true, forbiddenChangesObserved: [],
    };
    assert.throws(() => closeContextPack(databasePath, missing.pack.id, delivery),
      /editorial_publication_not_recorded:Oborot:Несуществующая публикация/);

    const project = new DatabaseSync(resolve('data/projects/00000000-0000-4000-a000-000000000102/project.sqlite'), { readOnly: true });
    const recorded = project.prepare(`SELECT p.platform,m.title,p.published_at,p.url
      FROM editorial_publications p JOIN editorial_materials m ON m.id=p.material_id
      WHERE p.status='published' AND p.url IS NOT NULL ORDER BY p.published_at,p.id LIMIT 1`).get();
    project.close();
    assert.ok(recorded);
    const present = compileContextPack(databasePath, { text, taskBrief: {
      ...brief, publicationReconciliation: { publications: [{
        platform: recorded.platform, title: recorded.title, publishedAt: recorded.published_at.slice(0, 10), url: recorded.url,
      }] },
    } });
    const closed = closeContextPack(databasePath, present.pack.id, delivery);
    assert.equal(closed.status, 'closed');
    assert.equal(closed.validation.publication_reconciliation.verified_publications[0].title, recorded.title);

    const unrelated = compileContextPack(databasePath, { text: 'Исправь UI operator panel MetricHit', taskBrief: {
      result: 'UI', scope: ['operator-panel'], firstCheck: 'ui-check', acceptance: ['visible'], forbiddenChanges: ['editorial'],
    } });
    assert.equal(unrelated.pack.payload.execution_card.publication_reconciliation, null);
    assert.equal(closeContextPack(databasePath, unrelated.pack.id, {
      result: 'UI', checks: ['ui-check'], satisfiedAcceptance: ['visible'], scopeCompliance: true, forbiddenChangesObserved: [],
    }).status, 'closed');
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('Telegram is exempt while non-Telegram routes require semantic context and only an indexation objective', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    addPublicEditorialSemanticCorePolicy(databasePath);
    addPublicEditorialIndexationPfTargetPolicy(databasePath);
    const baseBrief = {
      result: 'Проверенный публичный материал', scope: ['work/social'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['semantic_ready'],
      forbiddenChanges: ['publication'],
    };
    const vkSemantics = {
      selectedClusters: ['launch_and_management'], adjacentClusterRationale: null,
      primaryTargetQuery: 'накрутка ПФ Яндекс', secondaryTargetQueries: ['как запустить накрутку ПФ'],
      userIntent: 'понять управляемый запуск ПФ', platform: 'VK', format: 'social_post',
    };
    const vkIndexation = {
      seoIndexationObjective: 'Индексация Яндекса по выбранному запросу',
    };
    assert.throws(() => compileContextPack(databasePath, {
      text: 'Подготовь пост VK для MetricHit', projectDatabasePath, taskBrief: baseBrief,
    }), /editorial_semantics\.selected_clusters/);
    assert.throws(() => compileContextPack(databasePath, {
      text: 'Подготовь пост VK для MetricHit', projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: vkSemantics },
    }), /editorial_indexation\.seo_indexation_objective/);

    const vkCompiled = compileContextPack(databasePath, { text: 'Подготовь пост VK для MetricHit', projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: vkSemantics, editorialIndexation: vkIndexation } });
    const vkCard = vkCompiled.pack.payload.execution_card;
    assert.equal(vkCompiled.route.taskType, 'editorial');
    assert.ok(vkCard.mandatory_rules.some((item) => item.semantic_key === 'content.public_editorial_semantic_core_policy'));
    assert.ok(vkCard.mandatory_rules.some((item) => item.semantic_key === 'content.public_editorial_yandex_indexation_pf_target_policy'));
    assert.deepEqual(vkCard.editorial_semantics, {
      selected_clusters: vkSemantics.selectedClusters, adjacent_cluster_rationale: vkSemantics.adjacentClusterRationale,
      primary_target_query: vkSemantics.primaryTargetQuery,
      secondary_target_queries: vkSemantics.secondaryTargetQueries, user_intent: vkSemantics.userIntent,
      platform: vkSemantics.platform, format: 'social_post', core_reference: SEMANTIC_CORE_REFERENCE_KEY,
    });
    assert.deepEqual(vkCard.editorial_indexation, {
      seo_indexation_objective: vkIndexation.seoIndexationObjective,
      future_pf_campaign: {
        requires_independently_verified_yandex_indexation_after_publication: true,
        separate_owner_approval_required: true,
        auto_authorized: false,
      },
    });
    assert.deepEqual(vkCard.delivery_qa.checks.map((item) => item.id), ['semantic_cluster_selection', 'target_queries_approved_core', 'primary_query_prominence', 'adjacent_clusters_one_intent', 'geo_demand_verification']);
    const baseDelivery = { result: 'Материал проверен', checks: [baseBrief.firstCheck],
      satisfiedAcceptance: baseBrief.acceptance, scopeCompliance: true, forbiddenChangesObserved: [] };
    const adjacentSemantics = {
      selectedClusters: ['launch_and_management', 'segments'],
      adjacentClusterRationale: 'Оба кластера обслуживают один интент: планирование запуска ПФ для интернет-магазина.',
      primaryTargetQuery: 'накрутка ПФ Яндекс', secondaryTargetQueries: ['поведенческие факторы для интернет-магазина'],
      userIntent: 'понять управляемый запуск ПФ для интернет-магазина', platform: 'VK', format: 'social_post',
    };
    const adjacentCompiled = compileContextPack(databasePath, { text: 'Подготовь пост VK с несколькими смежными кластерами', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: adjacentSemantics, editorialIndexation: vkIndexation } });
    assert.deepEqual(adjacentCompiled.pack.payload.execution_card.editorial_semantics.selected_clusters, adjacentSemantics.selectedClusters);
    assert.equal(closeContextPack(databasePath, adjacentCompiled.pack.id, { ...baseDelivery, contentQa: publicEditorialQa(adjacentSemantics) }).status, 'closed');
    assert.throws(() => compileContextPack(databasePath, { text: 'Подготовь пост VK с несколькими кластерами без обоснования', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: { ...adjacentSemantics, adjacentClusterRationale: null }, editorialIndexation: vkIndexation } }),
    /editorial_semantics\.adjacent_cluster_rationale/);
    assert.throws(() => compileContextPack(databasePath, { text: 'Подготовь пост VK с неутверждённым ключом', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: { ...vkSemantics, primaryTargetQuery: 'придуманный LSI запрос' }, editorialIndexation: vkIndexation } }),
    /target_query_not_in_selected_approved_core_clusters/);
    assert.throws(() => compileContextPack(databasePath, { text: 'Подготовь пост VK со смешанным кластером', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: { ...vkSemantics, secondaryTargetQueries: ['keyword-1'] }, editorialIndexation: vkIndexation } }),
    /target_query_not_in_selected_approved_core_clusters/);
    assert.throws(() => compileContextPack(databasePath, { text: 'Подготовь пост VK без списка вторичных ключей', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: { ...vkSemantics, secondaryTargetQueries: undefined }, editorialIndexation: vkIndexation } }),
    /editorial_semantics\.secondary_target_queries/);
    const invalidQa = publicEditorialQa(vkSemantics);
    invalidQa.checks.find((item) => item.id === 'target_queries_approved_core').evidence.secondary_target_queries = ['keyword-1'];
    assert.throws(() => closeContextPack(databasePath, vkCompiled.pack.id, { ...baseDelivery, contentQa: invalidQa }),
      /target_queries_approved_core/);
    assert.equal(closeContextPack(databasePath, vkCompiled.pack.id, { ...baseDelivery, contentQa: publicEditorialQa(vkSemantics) }).status, 'closed');

    const telegramCompiled = compileContextPack(databasePath, { text: 'Подготовь пост Telegram для MetricHit', projectDatabasePath, taskBrief: baseBrief });
    const telegramCard = telegramCompiled.pack.payload.execution_card;
    assert.equal(telegramCard.mandatory_rules.some((item) => item.semantic_key === 'content.public_editorial_semantic_core_policy'), false);
    assert.equal(telegramCard.mandatory_rules.some((item) => item.semantic_key === 'content.public_editorial_yandex_indexation_pf_target_policy'), false);
    assert.equal(telegramCard.editorial_semantics, null);
    assert.equal(telegramCard.editorial_indexation, null);
    assert.equal(telegramCard.delivery_qa, null);
    assert.equal(closeContextPack(databasePath, telegramCompiled.pack.id, baseDelivery).status, 'closed');

    for (const [text, semantics, indexation] of [
      ['Подготовь статью TenChat для MetricHit', { ...vkSemantics, platform: 'TenChat', format: 'article' }, vkIndexation],
      ['Подготовь статью для article platform MetricHit', { ...vkSemantics, platform: 'Article platform', format: 'article' }, vkIndexation],
    ]) {
      assert.throws(() => compileContextPack(databasePath, { text, projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: semantics } }),
        /editorial_indexation\.seo_indexation_objective/);
      const compiled = compileContextPack(databasePath, { text, projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: semantics, editorialIndexation: indexation } });
      const keys = compiled.pack.payload.execution_card.mandatory_rules.map((item) => item.semantic_key);
      assert.ok(keys.includes('content.public_editorial_semantic_core_policy'));
      assert.ok(keys.includes('content.public_editorial_yandex_indexation_pf_target_policy'));
    }

    const unrelated = compileContextPack(databasePath, { text: 'Исправь UI operator panel MetricHit', projectDatabasePath, taskBrief: {
      result: 'UI', scope: ['operator-panel'], firstCheck: 'ui-check', acceptance: ['visible'], forbiddenChanges: ['editorial'],
    } });
    assert.equal(unrelated.pack.payload.execution_card.mandatory_rules
      .some((item) => item.semantic_key === 'content.public_editorial_semantic_core_policy'), false);
    assert.equal(unrelated.pack.payload.execution_card.editorial_semantics, null);
    assert.equal(unrelated.pack.payload.execution_card.editorial_indexation, null);
    assert.equal(unrelated.pack.payload.execution_card.delivery_qa, null);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('VK writing standard is isolated and validates target plus both justified exception length bands', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    addPublicEditorialSemanticCorePolicy(databasePath);
    addPublicEditorialIndexationPfTargetPolicy(databasePath);
    addVkPostWritingStandard(databasePath);
    const baseBrief = {
      result: 'Проверенный VK-пост', scope: ['work/social/vk'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['vk_standard_ready'],
      forbiddenChanges: ['publication'],
    };
    const semantics = {
      selectedClusters: ['launch_and_management'], adjacentClusterRationale: null,
      primaryTargetQuery: 'накрутка ПФ Яндекс', secondaryTargetQueries: ['как запустить накрутку ПФ'],
      userIntent: 'понять управляемый запуск ПФ', platform: 'VK', format: 'social_post',
    };
    const indexation = { seoIndexationObjective: 'Индексация Яндекса по выбранному запросу' };
    const delivery = { result: 'VK-пост проверен', checks: [baseBrief.firstCheck],
      satisfiedAcceptance: baseBrief.acceptance, scopeCompliance: true, forbiddenChangesObserved: [] };
    for (const [text, count, band, rationale] of [
      ['Подготовь пост для VK в целевом объёме', 2200, 'target', null],
      ['Подготовь узкий новостной пост для VK в формате чек-листа', 1500, 'narrow_news_or_checklist', 'Узкий чек-лист полностью решает один заявленный интент.'],
      ['Подготовь подробный практический пост для VK', 3400, 'detailed_practical_breakdown', 'Тема требует подробного практического разбора с конкретными действиями.'],
    ]) {
      const compiled = compileContextPack(databasePath, { text, projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: semantics, editorialIndexation: indexation } });
      const card = compiled.pack.payload.execution_card;
      assert.deepEqual(compiled.route.signals, ['editorial', 'vk']);
      assert.ok(card.mandatory_rules.some((item) => item.semantic_key === 'editorial.vk_post_writing_standard'));
      assert.ok(card.delivery_qa.checks.some((item) => item.id === 'vk_body_character_count'));
      assert.ok(card.delivery_qa.checks.some((item) => item.id === 'vk_semantic_structure'));
      assert.equal(closeContextPack(databasePath, compiled.pack.id, { ...delivery, contentQa: vkPostQa(semantics, count, band, rationale) }).status, 'closed');
    }
    const missingRationale = compileContextPack(databasePath, { text: 'Подготовь короткий пост для VK без причины', projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: semantics, editorialIndexation: indexation } });
    assert.throws(() => closeContextPack(databasePath, missingRationale.pack.id, { ...delivery, contentQa: vkPostQa(semantics, 1500, 'narrow_news_or_checklist', null) }), /vk_body_character_count/);

    const telegram = compileContextPack(databasePath, { text: 'Подготовь пост Telegram', projectDatabasePath, taskBrief: baseBrief });
    assert.equal(telegram.pack.payload.execution_card.mandatory_rules.some((item) => item.semantic_key === 'editorial.vk_post_writing_standard'), false);
    const tenchat = compileContextPack(databasePath, { text: 'Подготовь статью TenChat', projectDatabasePath, taskBrief: { ...baseBrief, editorialSemantics: { ...semantics, platform: 'TenChat', format: 'article' }, editorialIndexation: indexation } });
    assert.equal(tenchat.pack.payload.execution_card.mandatory_rules.some((item) => item.semantic_key === 'editorial.vk_post_writing_standard'), false);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('article target-query volume ladder and geo owner-gate are fail-closed while VK and Telegram remain exempt', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    addPublicEditorialSemanticCorePolicy(databasePath);
    addPublicEditorialIndexationPfTargetPolicy(databasePath);
    addPublicEditorialTargetQueryVolumeLadderPolicy(databasePath);
    addGeoDemandGatePolicy(databasePath);
    const baseBrief = {
      result: 'Проверенная статья', scope: ['work/articles/draft.md'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['volume_ladder_ready'],
      forbiddenChanges: ['publication'],
    };
    const semantics = {
      selectedClusters: ['launch_and_management', 'segments', 'fixture'],
      adjacentClusterRationale: 'Кластеры смежны для одного интента: управляемый запуск продвижения товарной категории.',
      primaryTargetQuery: 'накрутка ПФ Яндекс',
      secondaryTargetQueries: ['как запустить накрутку ПФ', 'настройка проекта ПФ', 'поведенческие факторы для интернет-магазина', 'keyword-1', 'keyword-2', 'keyword-3', 'keyword-4'],
      userIntent: 'спланировать запуск продвижения товарной категории', platform: 'Article platform', format: 'article',
    };
    const indexation = { seoIndexationObjective: 'Индексация Яндекса по выбранным запросам' };
    const delivery = { result: 'Материал проверен', checks: [baseBrief.firstCheck],
      satisfiedAcceptance: baseBrief.acceptance, scopeCompliance: true, forbiddenChangesObserved: [] };
    const compiled = compileContextPack(databasePath, { text: 'Подготовь статью с семантикой по объёму', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: semantics, editorialIndexation: indexation } });
    const card = compiled.pack.payload.execution_card;
    assert.ok(card.mandatory_rules.some((item) => item.semantic_key === 'content.public_editorial_target_query_volume_ladder_policy'));
    assert.ok(card.delivery_qa.checks.some((item) => item.id === 'target_query_volume_ladder'));
    assert.equal(closeContextPack(databasePath, compiled.pack.id, { ...delivery,
      contentQa: articleEditorialSemanticQaWithVolumeLadder(semantics, 2200) }).status, 'closed');

    const missingRationale = compileContextPack(databasePath, { text: 'Подготовь короткую статью с семантикой по объёму', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: semantics, editorialIndexation: indexation } });
    assert.throws(() => closeContextPack(databasePath, missingRationale.pack.id, { ...delivery,
      contentQa: articleEditorialSemanticQaWithVolumeLadder(semantics, 1600) }), /target_query_volume_ladder/);

    const shortWithRationale = compileContextPack(databasePath, { text: 'Подготовь короткую статью с обоснованием семантики', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: semantics, editorialIndexation: indexation } });
    assert.equal(closeContextPack(databasePath, shortWithRationale.pack.id, { ...delivery,
      contentQa: articleEditorialSemanticQaWithVolumeLadder(semantics, 1600, 'Короткий формат полностью решает один интент; число точных запросов сохранено для связанной темы.') }).status, 'closed');

    const tooFewQueries = { ...semantics, secondaryTargetQueries: semantics.secondaryTargetQueries.slice(0, 4) };
    const badCount = compileContextPack(databasePath, { text: 'Подготовь статью с недостаточным числом точных запросов', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: tooFewQueries, editorialIndexation: indexation } });
    assert.throws(() => closeContextPack(databasePath, badCount.pack.id, { ...delivery,
      contentQa: articleEditorialSemanticQaWithVolumeLadder(tooFewQueries, 2200) }), /target_query_volume_ladder/);

    const geoSemantics = { ...semantics,
      selectedClusters: [...semantics.selectedClusters, 'geo_candidates_after_demand_validation'],
      secondaryTargetQueries: [...semantics.secondaryTargetQueries.slice(0, 6), 'накрутка пф москва'],
    };
    assert.throws(() => compileContextPack(databasePath, { text: 'Подготовь статью с подтверждаемой геосемантикой', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: geoSemantics, editorialIndexation: indexation } }),
    /editorial_semantics.geo_demand_owner_confirmed/);
    const confirmedGeo = compileContextPack(databasePath, { text: 'Подготовь статью с подтверждённой геосемантикой', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: { ...geoSemantics, geoDemandOwnerConfirmed: true }, editorialIndexation: indexation } });
    assert.equal(confirmedGeo.pack.payload.execution_card.editorial_semantics.geo_demand_owner_confirmed, true);

    const vk = compileContextPack(databasePath, { text: 'Подготовь пост VK', projectDatabasePath,
      taskBrief: { ...baseBrief, editorialSemantics: { ...semantics, platform: 'VK', format: 'social_post' }, editorialIndexation: indexation } });
    assert.equal(vk.pack.payload.execution_card.mandatory_rules
      .some((item) => item.semantic_key === 'content.public_editorial_target_query_volume_ladder_policy'), false);
    assert.equal(vk.pack.payload.execution_card.mandatory_rules
      .some((item) => item.semantic_key === 'content.geo_demand_gate_automation'), false);
    const telegram = compileContextPack(databasePath, { text: 'Подготовь пост Telegram', projectDatabasePath, taskBrief: baseBrief });
    assert.equal(telegram.pack.payload.execution_card.mandatory_rules
      .some((item) => item.semantic_key === 'content.public_editorial_target_query_volume_ladder_policy'), false);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('semantic core pointer is scoped to editorial/research and full content is explicit and project-authoritative', () => {
  const { directory, databasePath, projectDatabasePath, keywords } = referenceFixture();
  try {
    const db = new DatabaseSync(databasePath, { readOnly: true });
    const card = { result: 'Reference test', scope: ['memory'], firstCheck: 'test', acceptance: ['valid'], forbiddenChanges: ['drift'] };
    const general = compileDeterministicContext(db, { scopeId: SCOPE_IDS.metrichit, taskType: 'general', agentsContent: '', taskBrief: card });
    const editorial = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: '', taskBrief: card });
    const research = compileDeterministicContext(db, {
      scopeId: SCOPE_IDS.editorial, taskType: 'research', includeReferencedContent: true,
      projectDatabasePath, agentsContent: '', taskBrief: card,
    });
    assert.deepEqual(general.references, []);
    assert.deepEqual(general.expanded_references, []);
    assert.equal(JSON.stringify(general).includes('keyword-1'), false);
    assert.equal(editorial.references.length, 1);
    assert.deepEqual(editorial.expanded_references, []);
    assert.equal(JSON.stringify(editorial).includes('keyword-1'), false);
    assert.equal(research.references.length, 1);
    assert.equal(research.expanded_references[0].project_id, '00000000-0000-4000-a000-000000000102');
    assert.deepEqual(research.expanded_references[0].data.taxonomy.fixture, keywords);
    assert.equal(research.expanded_references[0].source_database, 'project.sqlite');
    const explicitEditorial = compileDeterministicContext(db, {
      scopeId: SCOPE_IDS.editorial, taskType: 'editorial', includeReferencedContent: true,
      projectDatabasePath, agentsContent: '', taskBrief: card,
    });
    assert.equal(explicitEditorial.expanded_references[0].data.keyword_count, 145);
    assert.throws(() => compileDeterministicContext(db, {
      scopeId: SCOPE_IDS.metrichit, taskType: 'general', includeReferencedContent: true,
      projectDatabasePath, agentsContent: '', taskBrief: card,
    }), /only for an explicit editorial or research task/);
    db.close();

    const routeDatabase = new DatabaseSync(databasePath, { readOnly: true });
    const route = routeTask(routeDatabase, { text: 'Исследуй семантическое ядро MetricHit' });
    routeDatabase.close();
    assert.equal(route.scopeId, SCOPE_IDS.editorial);
    assert.equal(route.taskType, 'research');
    const explicitRouteDatabase = new DatabaseSync(databasePath, { readOnly: true });
    const explicitResearch = routeTask(explicitRouteDatabase, { text: 'MetricHit', taskType: 'research' });
    explicitRouteDatabase.close();
    assert.equal(explicitResearch.scopeId, SCOPE_IDS.editorial);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('authoritative semantic reference fails closed on project content drift', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    const control = new DatabaseSync(databasePath, { readOnly: true });
    const records = resolveScopedMemory(control, SCOPE_IDS.editorial, 'research').records;
    control.close();
    const project = new DatabaseSync(projectDatabasePath);
    project.prepare('UPDATE memory_candidates SET data_json=? WHERE id=?')
      .run('{"taxonomy":{"fixture":[]},"keyword_count":0}', 'fixture-semantic-core');
    project.close();
    assert.throws(() => loadReferencedMemory(projectDatabasePath, records, 'research'), /hash mismatch/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('orchestration v1 routes only Editorial, compiles the task chain and selects allowed skills', () => {
  const { directory, databasePath, projectDatabasePath } = fixture();
  try {
    const taskBrief = {
      result: 'Telegram draft is prepared', scope: ['work/social/telegram/draft.md'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['draft_ready'],
      forbiddenChanges: ['publication'],
    };
    const compiled = compileCoordinatorContext(databasePath, {
      profileId: 'metrichit.editorial.v1', taskId: 'editorial-orchestration-test',
      taskName: 'Editorial orchestration test', text: 'Подготовь пост Telegram для MetricHit',
      taskType: 'editorial', projectDatabasePath, taskBrief,
    });
    assert.equal(compiled.route.outcome, 'routed');
    assert.deepEqual(compiled.pack.payload.passports.map((item) => item.id), [
      SCOPE_IDS.core, SCOPE_IDS.metrichit, SCOPE_IDS.editorial, 'scope:task:editorial-orchestration-test',
    ]);
    assert.equal(compiled.pack.payload.coordinator_profile.role, 'temporary_read_only_coordinator');
    assert.equal(compiled.pack.payload.coordinator_profile.maximum_delegation_depth, 2);
    assert.equal(compiled.pack.payload.coordinator_profile.maximum_research_branches, 3);
    assert.equal(compiled.pack.payload.passports.some((item) => item.id === SCOPE_IDS.panel), false);
    assert.deepEqual(selectCoordinatorSkills('metrichit.editorial.v1', 'editorial', ['copywriting', 'seo-strategy']),
      ['copywriting', 'seo-strategy']);
    assert.throws(() => selectCoordinatorSkills('metrichit.editorial.v1', 'editorial', ['not-installed']),
      /unknown or disallowed skill/);
    assert.throws(() => compileCoordinatorContext(databasePath, {
      profileId: 'metrichit.editorial.v1', taskId: 'panel-route', text: 'Исправь UI operator panel MetricHit',
      taskType: 'ui', taskBrief,
    }), /task type is not allowed|outside the coordinator profile scope/);
    assert.throws(() => compileCoordinatorContext(databasePath, {
      profileId: 'metrichit.editorial.v1', taskId: 'sibling-route', text: 'Исследуй UI operator panel MetricHit',
      taskType: 'research', taskBrief,
    }), /outside the coordinator profile scope/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

function scopeNames(database, scopeId) {
  const names = [];
  let current = scopeId;
  while (current) {
    const row = database.prepare('SELECT name,parent_scope_id FROM scope_passports WHERE id=?').get(current);
    names.push(row.name); current = row.parent_scope_id;
  }
  return names.reverse();
}
