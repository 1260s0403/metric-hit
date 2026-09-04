import { createHash, randomUUID } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { DatabaseSync } from 'node:sqlite';
import { EDITORIAL_CONTRACT, compileEditorialSpec, validateEditorialArtifact } from './editorial-contract.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const defaultProjectDatabasePath = join(repositoryRoot, 'data', 'projects', '00000000-0000-4000-a000-000000000102', 'project.sqlite');
const agentsPath = join(repositoryRoot, 'AGENTS.md');
export const COMPILER_VERSION = 9;
export const METRICHIT_PROJECT_ID = '00000000-0000-4000-a000-000000000102';
export const YADRO_CONTROL_PLANE_PROJECT_ID = '00000000-0000-4000-a000-000000000101';
export const SEMANTIC_CORE_REFERENCE_KEY = 'content.metrichit_semantic_core.reference';
export const SCOPE_IDS = Object.freeze({
  core: 'scope:core', metrichit: 'scope:project:metrichit',
  editorial: 'scope:subproject:editorial', panel: 'scope:subproject:panel',
});
export const COORDINATOR_PROFILES = Object.freeze({
  'metrichit.editorial.v1': Object.freeze({
    id: 'metrichit.editorial.v1', status: 'active', scope_id: SCOPE_IDS.editorial,
    task_types: Object.freeze(['editorial', 'research']), role: 'temporary_read_only_coordinator',
    maximum_delegation_depth: 2, maximum_research_branches: 3,
    allowed_skills: Object.freeze({
      editorial: Object.freeze(['content-strategy', 'seo-strategy', 'copywriting', 'image']),
      research: Object.freeze(['content-strategy', 'seo-strategy', 'customer-research']),
    }),
  }),
});
const EDITORIAL_PIPELINE_ID = 'metrichit.editorial.pipeline.v1';
const EDITORIAL_PIPELINE_STAGES = Object.freeze([
  ['metrichit.editorial.planner.v1', 'planner', 'content-strategy'],
  ['metrichit.editorial.architect.v1', 'architect', 'seo-strategy'],
  ['metrichit.editorial.writer.v1', 'writer', 'copywriting'],
  ['metrichit.editorial.designer.v1', 'designer', 'image'],
  ['metrichit.editorial.validator.v1', 'validator', 'compliance-qa'],
]);
const ARTICLE_PIPELINE_TRIGGER = /^напиши\s+новую\s+статью\s+для\s+(.+?)\s*[.!?]?$/iu;
const ARTICLE_REVISION_TRIGGER = /(?:последн\p{L}*\s+стать\p{L}*|стать\p{L}*\s+(?:доработ|исправ|обнов|замен)\p{L}*).*(?:картин|изображ|иллюстрац|доработ|исправ|обнов|замен)|(?:картин|изображ|иллюстрац|доработ|исправ|обнов|замен).*(?:последн\p{L}*\s+стать\p{L}*)/iu;
const ARTICLE_ASSET_PATTERN = /work\/articles\/assets\/[A-Za-z0-9._/-]+\.(?:png|jpe?g|webp|gif|svg)/giu;
const EMPTY_TOPIC_AUTOPLANNING_HOTFIX = Object.freeze({
  id: 'editorial.empty_topic.autoplanning.v1',
  owner_question: 'prohibited',
  profiles: Object.freeze([
    'metrichit.editorial.planner.v1', 'metrichit.editorial.architect.v1',
    'metrichit.editorial.writer.v1', 'metrichit.editorial.designer.v1',
    'metrichit.editorial.validator.v1',
  ]),
});
const ARTICLE_PLATFORM_MATRIX = Object.freeze([
  { id: 'telegram', name: 'Telegram', aliases: ['telegram', 'телеграм', 'тг'], contour: 'work/social/telegram', mode: 'automatic' },
  { id: 'vk', name: 'VK', aliases: ['vk', 'вк', 'вконтакте'], contour: 'work/social/vk', mode: 'draft-only' },
  { id: 'dzen', name: 'Дзен', aliases: ['дзен', 'dzen'], contour: 'work/articles', mode: 'manual-package' },
  { id: 'sostav', name: 'Sostav/SBlogs', aliases: ['sostav', 'sblogs', 'sostav/sblogs', 'состав'], contour: 'work/articles', mode: 'manual-package' },
  { id: 'oborot', name: 'Oborot.ru', aliases: ['oborot', 'oborot.ru', 'оборот', 'оборот.ру'], contour: 'work/articles', mode: 'manual-package' },
  { id: 'timeweb-cloud', name: 'Timeweb Cloud', aliases: ['timeweb', 'timeweb cloud', 'таймвеб', 'таймвеб клауд'], contour: 'work/articles', mode: 'manual-package' },
  { id: 'workspace', name: 'Workspace', aliases: ['workspace', 'workspace media', 'воркспейс'], contour: 'work/articles', mode: 'manual-package' },
  { id: 'max', name: 'MAX', aliases: ['max', 'макс'], contour: null, mode: 'outside-mvp' },
  { id: 'avito', name: 'Avito', aliases: ['avito', 'авито'], contour: null, mode: 'unsupported' },
]);
const TARGET_QUERY_VOLUME_LADDER = Object.freeze(EDITORIAL_CONTRACT.volume_bands.map((band) => Object.freeze({
  minimumCharacters: band.minimum_characters, maximumCharacters: band.maximum_characters,
  minimumQueries: band.minimum_queries, maximumQueries: band.maximum_queries,
})));
const PLANNER_H1_HIGH_FREQUENCY_MARKERS = Object.freeze([...EDITORIAL_CONTRACT.h1.approved_forms]);
const APPROVED_H1_HIGH_FREQUENCY_QUERIES = Object.freeze(
  PLANNER_H1_HIGH_FREQUENCY_MARKERS.map((query) => query.toLocaleLowerCase('ru-RU')),
);
const EDITORIAL_VISUAL_STANDARD_KEY = 'content.editorial_visual_standard';

function now() { return new Date().toISOString(); }
function hash(value) { return createHash('sha256').update(value).digest('hex'); }
function canonical(value) { return JSON.stringify(value); }
function open(databasePath, readOnly = false) {
  if (!existsSync(databasePath)) throw new Error(`Database does not exist: ${databasePath}`);
  const database = new DatabaseSync(databasePath, { readOnly });
  database.exec(`PRAGMA foreign_keys=ON;${readOnly ? ' PRAGMA query_only=ON;' : ''}`);
  return database;
}
function parseJson(value, fallback) { try { return JSON.parse(value); } catch { return fallback; } }
function nonEmptyText(value) { return typeof value === 'string' && value.trim() ? value.trim() : null; }
function nonEmptyList(value) {
  if (!Array.isArray(value)) return [];
  return value.map(nonEmptyText).filter(Boolean);
}
function targetQueryVolumeBand(characterCount) {
  return TARGET_QUERY_VOLUME_LADDER.find((band) => characterCount >= band.minimumCharacters && characterCount <= band.maximumCharacters) ?? null;
}

function articlePlatformRoute(rawName) {
  const normalized = String(rawName).trim().replace(/[.!?]+$/u, '').trim().toLocaleLowerCase('ru-RU');
  const matches = ARTICLE_PLATFORM_MATRIX.filter((platform) => platform.aliases.includes(normalized));
  return matches.length === 1 ? matches[0] : null;
}

function articlePlatformFromText(text) {
  const normalized = String(text).toLocaleLowerCase('ru-RU');
  const matches = ARTICLE_PLATFORM_MATRIX.filter((platform) => platform.aliases.some((alias) => {
    if (alias === 'оборот') return /(?:^|[^\p{L}\p{N}])оборот(?:а|у|ом|е)?(?:\.ру)?(?:$|[^\p{L}\p{N}])/iu.test(normalized);
    return normalized.includes(alias);
  }));
  return matches.length === 1 ? matches[0] : null;
}

function loadEditorialPipeline(projectDatabasePath) {
  const database = open(resolve(projectDatabasePath), true);
  try {
    if (!hasTable(database, 'editorial_agent_profiles')) {
      throw new Error('Migration 007 editorial agent profiles are unavailable');
    }
    const rows = database.prepare(`SELECT profile_id,pipeline_id,stage_order,stage_name,capability,
      profile_kind,isolation_key,execution_mode,policy_json,status
      FROM editorial_agent_profiles WHERE pipeline_id=? ORDER BY stage_order`).all(EDITORIAL_PIPELINE_ID);
    if (rows.length !== EDITORIAL_PIPELINE_STAGES.length || rows.some((row, index) => {
      const [profileId, stageName, capability] = EDITORIAL_PIPELINE_STAGES[index];
      return row.stage_order !== index + 1 || row.profile_id !== profileId || row.stage_name !== stageName
        || row.capability !== capability || row.status !== 'active' || row.execution_mode !== 'isolated_sequential';
    })) {
      throw new Error('Migration 007 editorial pipeline is incomplete or inactive');
    }
    return {
      pipeline_id: EDITORIAL_PIPELINE_ID,
      migration: '007_editorial_agent_pipeline.sql',
      execution_mode: 'isolated_sequential',
      launch_directive: 'start',
      stages: rows.map((row) => ({
        order: row.stage_order, profile_id: row.profile_id, stage: row.stage_name,
        capability: row.capability, profile_kind: row.profile_kind, isolation_key: row.isolation_key,
        policy: parseJson(row.policy_json, null),
        hotfix: {
          ...EMPTY_TOPIC_AUTOPLANNING_HOTFIX,
          planner_execution_required: row.profile_id === 'metrichit.editorial.planner.v1',
          downstream_input: row.profile_id === 'metrichit.editorial.planner.v1'
            ? 'produce_three_structures_and_select_one_deterministically'
            : 'consume_planner_selected_structure_only',
        },
      })),
    };
  } finally { database.close(); }
}

function normalizeOverlapText(value) {
  return String(value ?? '').toLocaleLowerCase('ru-RU').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

function publishedArchiveText() {
  const archiveRoot = join(repositoryRoot, 'work', 'articles', 'published');
  if (!existsSync(archiveRoot) || !statSync(archiveRoot).isDirectory()) return { error: 'published_archive_unavailable', files: 0, text: '' };
  const files = [];
  const collect = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) collect(path);
      else if (entry.isFile() && /\.(?:md|txt|html?)$/iu.test(entry.name)) files.push(path);
    }
  };
  collect(archiveRoot);
  return { files: files.length, text: normalizeOverlapText(files.map((path) => readFileSync(path, 'utf8')).join(' ')) };
}

function approvedSemanticCore302(database) {
  const rows = database.prepare(`SELECT data_json,reviewed_at,id FROM memory_candidates
    WHERE semantic_key='content.metrichit_semantic_core' AND status='approved'
    ORDER BY reviewed_at DESC,id DESC`).all();
  return rows.map((row) => ({ id: row.id, core: parseJson(row.data_json, null) }))
    .filter(({ core }) => core?.keyword_count === 302 && core?.project_id === METRICHIT_PROJECT_ID
      && core?.taxonomy && typeof core.taxonomy === 'object');
}

function freeHfMarkers(taxonomy, archiveText) {
  const markers = [];
  for (const [cluster, queries] of Object.entries(taxonomy)) {
    if (cluster === 'geo_candidates_after_demand_validation' || !Array.isArray(queries)) continue;
    for (const query of queries) {
      const marker = nonEmptyText(query);
      const words = marker?.split(/\s+/u).length ?? 0;
      const h1 = PLANNER_H1_HIGH_FREQUENCY_MARKERS.find((allowed) =>
        normalizeOverlapText(allowed) === normalizeOverlapText(marker));
      if (!h1 || words < 2 || words > 3 || archiveText.includes(normalizeOverlapText(marker))) continue;
      markers.push({ cluster, marker, h1 });
    }
  }
  return markers;
}

function threeReadyStructures(h1) {
  return [
    { number: 1, h1, title: h1, sections: ['Что проверяют до старта', 'Как связать цель, страницу и метрики', 'Контрольный список решений', 'Вывод и следующий шаг'] },
    { number: 2, h1, title: h1, sections: ['Когда задача возникает', 'Критерии сравнения вариантов', 'Типичные ошибки планирования', 'Как зафиксировать результат'] },
    { number: 3, h1, title: h1, sections: ['Исходные признаки', 'Приоритеты проверки', 'План на ближайший цикл', 'Как оценить изменения без неподтверждённых обещаний'] },
  ];
}

function automaticEmptyTopicPlannerAssignment(projectDatabasePath, platform) {
  const database = open(resolve(projectDatabasePath), true);
  try {
    const archive = publishedArchiveText();
    const cores = approvedSemanticCore302(database);
    const candidates = [...new Map(cores.flatMap(({ core }) => freeHfMarkers(core.taxonomy, archive.text))
      .map((item) => [item.marker.toLocaleLowerCase('ru-RU'), item])).values()];
    const systemError = (reason) => ({ code: 'E_AMBIGUOUS_TOPIC', reason,
      available_hf_markers: [...PLANNER_H1_HIGH_FREQUENCY_MARKERS] });
    if (archive.error || cores.length !== 1 || candidates.length === 0) {
      return { hotfix_id: EMPTY_TOPIC_AUTOPLANNING_HOTFIX.id, executor_profile: 'metrichit.editorial.planner.v1',
        status: 'blocked', background_mode: true, owner_question: 'prohibited',
        published_archive_overlap: { scanned: !archive.error, archive_files: archive.files, selected_marker_overlaps: null },
        system_error: systemError(archive.error ?? (cores.length !== 1 ? 'semantic_core_conflict' : 'no_free_hf_markers')) };
    }
    const selection = candidates[0];
    const structureOptions = threeReadyStructures(selection.h1);
    return {
      hotfix_id: EMPTY_TOPIC_AUTOPLANNING_HOTFIX.id,
      executor_profile: 'metrichit.editorial.planner.v1', status: 'ready', background_mode: true,
      owner_question: 'prohibited', published_archive_overlap: { scanned: true, archive_files: archive.files, selected_marker_overlaps: false },
      selected_priority_hf_marker: selection.marker, selected_cluster: selection.cluster,
      structure_options: structureOptions,
      selected_structure: structureOptions[0],
      structure_selection: 'deterministic_priority_first',
    };
  } finally { database.close(); }
}

function automaticEditorialSpec(projectDatabasePath, route, assignment) {
  if (!assignment || assignment.status !== 'ready' || route.platform?.id !== 'oborot') return null;
  const database = open(resolve(projectDatabasePath), true);
  try {
    const core = approvedSemanticCore302(database)[0]?.core;
    if (!core) throw new Error('editorial spec requires one approved 302-query core');
    const primary = assignment.selected_priority_hf_marker;
    const selectedClusters = [assignment.selected_cluster];
    const secondary = (core.taxonomy[assignment.selected_cluster] ?? [])
      .filter((query) => normalizeOverlapText(query) !== normalizeOverlapText(primary));
    for (const [cluster, queries] of Object.entries(core.taxonomy)) {
      if (secondary.length >= 17 || selectedClusters.includes(cluster) || cluster === EDITORIAL_CONTRACT.semantic_core.geo_cluster) continue;
      selectedClusters.push(cluster);
      secondary.push(...queries.filter((query) => normalizeOverlapText(query) !== normalizeOverlapText(primary)));
    }
    secondary.splice(17);
    if (secondary.length !== 17) throw new Error('editorial spec requires 18 target queries for Oborot long-form');
    const structure = assignment.selected_structure.sections;
    const inline = structure.slice(0, 3).map((section, index) => ({
      path: `../assets/editorial-inline-${index + 1}.png`, medium: EDITORIAL_CONTRACT.visuals.allowed_medium,
      aspect_ratio: '3:2', section_anchor: section, semantic_role: ['explain_cause', 'show_action', 'show_result'][index],
      scene_intent: ['diagnostic_scene', 'planning_scene', 'measurement_scene'][index],
      observable_action: ['specialist reviews inputs', 'team groups campaign priorities', 'owner compares measured outcomes'][index],
      business_context: ['russian ecommerce operations', 'russian service business planning', 'russian business performance review'][index],
      composition: ['wide environmental', 'medium collaborative', 'close documentary'][index], device_role: 'none',
    }));
    return compileEditorialSpec({ platform: route.platform.name, character_range: { minimum: 7001, maximum: 9000 },
      selected_h1: assignment.selected_structure.h1, primary_query: primary, secondary_queries: secondary,
      selected_clusters: selectedClusters, adjacent_cluster_rationale: selectedClusters.length > 1
        ? 'Кластеры объединены одной практической задачей подготовки и контроля запуска.' : null,
      user_intent: 'Практически подготовить и контролировать запуск накрутки ПФ',
      lsi: [
        { term: 'поисковая выдача', category: 'search_context', section_anchor: structure[0], zone: 'h3' },
        { term: 'релевантность страницы', category: 'page_quality', section_anchor: structure[1], zone: 'h3' },
        { term: 'дневной лимит', category: 'campaign_control', section_anchor: structure[2], zone: 'h3' },
        { term: 'динамика позиций', category: 'measurement', section_anchor: structure[3], zone: 'h3' },
      ], structure,
      links: EDITORIAL_CONTRACT.article.landing_link_positions.map((position) => ({ position, url: EDITORIAL_CONTRACT.article.landing_url })),
      image_package: { preview: [{ path: '../assets/editorial-preview.png', medium: EDITORIAL_CONTRACT.visuals.allowed_medium, aspect_ratio: '1:1', is_screenshot: false }], inline },
    }, core.taxonomy);
  } finally { database.close(); }
}

function automaticArticleTaskBrief(route, taskBrief) {
  if (!route.signals.includes('article_pipeline_trigger')) return taskBrief;
  const platform = route.platform;
  const defaults = {
    result: `Новая статья для ${platform.name} подготовлена и проверена последовательной цепочкой Migration 007`,
    scope: [platform.contour],
    firstCheck: 'Проверить активные профили и порядок стадий Migration 007',
    acceptance: [
      `Площадка ${platform.name} однозначно определена по редакционной матрице`,
      'Planner, architect, writer, designer и validator выполнены строго последовательно',
      'Validator подтвердил обязательные правила execution card',
      'Готов только пакет материала; внешняя публикация не выполнялась',
    ],
    forbiddenChanges: ['Внешняя публикация без отдельного owner approval', 'Обход порядка стадий', 'Использование неактивного профиля'],
  };
  const overrides = Object.fromEntries(Object.entries(taskBrief ?? {})
    .filter(([, value]) => value !== undefined && value !== null));
  return { ...defaults, ...overrides };
}

function latestDeliveredArticleContext(database, platform = null) {
  const rows = database.prepare(`SELECT id,status,created_at,payload_json FROM context_packs
    WHERE scope_id=? AND task_type='editorial' AND status='closed' ORDER BY created_at DESC,id DESC`).all(SCOPE_IDS.editorial);
  for (const row of rows) {
    const payload = parseJson(row.payload_json, null);
    const card = payload?.execution_card;
    if (!card || payload.terminal_outcome !== 'delivered') continue;
    const semanticPlatform = card.editorial_semantics?.platform ?? null;
    const pipelinePlatform = card.editorial_pipeline?.platform ?? null;
    const sourcePlatform = semanticPlatform
      ? articlePlatformRoute(semanticPlatform)
      : ARTICLE_PLATFORM_MATRIX.find((item) => item.id === pipelinePlatform?.id);
    const isArticle = card.editorial_semantics?.format === 'article'
      || (pipelinePlatform?.contour === 'work/articles' && pipelinePlatform?.id !== 'telegram');
    if (!isArticle || (platform && sourcePlatform?.id !== platform.id)) continue;
    return { id: row.id, status: row.status, created_at: row.created_at, payload, card, platform: sourcePlatform ?? platform };
  }
  throw new Error('editorial revision source was not found: latest delivered article card is required');
}

function latestArticlePath(platform) {
  const draftsRoot = join(repositoryRoot, 'work', 'articles', 'drafts');
  if (!existsSync(draftsRoot)) return null;
  const platformToken = platform?.id === 'sostav' ? 'sostav' : platform?.id;
  const candidates = readdirSync(draftsRoot, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.toLocaleLowerCase('ru-RU').endsWith('.md'))
    .map((entry) => `work/articles/drafts/${entry.name}`)
    .filter((path) => !platformToken || path.toLocaleLowerCase('ru-RU').includes(platformToken));
  return candidates.sort((left, right) => right.localeCompare(left))[0] ?? null;
}

function articleRevisionIdentity(source) {
  const sourceScope = nonEmptyList(source.card.scope);
  const articlePath = sourceScope.find((path) => /^work\/articles\/(?:drafts|published)\/.+\.md$/iu.test(path))
    ?? latestArticlePath(source.platform);
  if (!articlePath) throw new Error('editorial revision source article path is unavailable');
  const scopedAssets = sourceScope.filter((path) => /^work\/articles\/assets\/.+\.(?:png|jpe?g|webp|gif|svg)$/iu.test(path));
  const absoluteArticlePath = resolve(repositoryRoot, articlePath);
  const referencedAssets = existsSync(absoluteArticlePath)
    ? [...readFileSync(absoluteArticlePath, 'utf8').matchAll(ARTICLE_ASSET_PATTERN)].map((match) => match[0]) : [];
  const assets = [...new Set([...scopedAssets, ...referencedAssets])].sort();
  return { article_path: articlePath, asset_paths: assets };
}

function inheritedRevisionSemantics(source) {
  const semantics = source.card.editorial_semantics;
  if (semantics) {
    return {
      selectedClusters: semantics.selected_clusters,
      adjacentClusterRationale: semantics.adjacent_cluster_rationale,
      primaryTargetQuery: semantics.primary_target_query,
      secondaryTargetQueries: semantics.secondary_target_queries,
      userIntent: semantics.user_intent,
      platform: semantics.platform,
      format: semantics.format,
      ...(semantics.geo_demand_owner_confirmed === true ? { geoDemandOwnerConfirmed: true } : {}),
    };
  }
  const assignment = source.card.editorial_pipeline?.empty_topic_planner_assignment;
  if (!assignment?.selected_cluster || !assignment?.selected_priority_hf_marker || !source.platform) {
    throw new Error('editorial revision source lacks required article semantics');
  }
  return {
    selectedClusters: [assignment.selected_cluster], adjacentClusterRationale: null,
    primaryTargetQuery: assignment.selected_priority_hf_marker, secondaryTargetQueries: [],
    userIntent: 'Сохранить поисковый интент исходной статьи при визуальной доработке.',
    platform: source.platform.name, format: 'article',
  };
}

function automaticArticleRevisionTaskBrief(route, taskBrief) {
  if (!route.signals.includes('article_revision')) return taskBrief;
  const source = route.articleRevisionSource;
  const identity = articleRevisionIdentity(source);
  const inheritedIndexation = source.card.editorial_indexation;
  const defaults = {
    result: `Изображения последней статьи ${source.platform?.name ?? ''} заменены по действующим редакционным правилам`.trim(),
    scope: [identity.article_path, ...identity.asset_paths],
    firstCheck: 'Проверить исходную статью, её текущие изображения и действующий editorial visual standard',
    acceptance: ['Создана новая execution card, исходная закрытая card не изменена', 'Сохранены семантика и поисковый интент исходной статьи', 'Изменения ограничены исходной статьёй и её изображениями'],
    forbiddenChanges: ['Переоткрытие или изменение исходной закрытой card', 'Изменение текста статьи вне ссылок на изображения', 'Внешняя публикация'],
    editorialSemantics: inheritedRevisionSemantics(source),
    editorialIndexation: inheritedIndexation ? { seoIndexationObjective: inheritedIndexation.seo_indexation_objective }
      : { seoIndexationObjective: 'Сохранить цель индексации исходной статьи при визуальной доработке.' },
  };
  const overrides = Object.fromEntries(Object.entries(taskBrief ?? {})
    .filter(([, value]) => value !== undefined && value !== null));
  route.articleRevisionContext = {
    kind: 'editorial_article_revision', source_context_pack_id: source.id,
    source_status: source.status, source_terminal_outcome: source.payload.terminal_outcome,
    source_created_at: source.created_at, platform: source.platform?.name ?? null,
    ...identity,
    owner_authorizations: {
      delete_replaced_assets: route.signals.includes('owner_authorized_asset_deletion'),
    },
    inherited_fields: ['editorial_semantics', 'editorial_indexation'],
  };
  return { ...defaults, ...overrides,
    editorialSemantics: overrides.editorialSemantics ?? defaults.editorialSemantics,
    editorialIndexation: overrides.editorialIndexation ?? defaults.editorialIndexation };
}

export function scopeChain(database, scopeId) {
  const chain = [];
  const seen = new Set();
  let current = scopeId;
  while (current) {
    if (seen.has(current)) throw new Error('scope hierarchy contains a cycle');
    seen.add(current);
    const row = database.prepare('SELECT * FROM scope_passports WHERE id=? AND status=\'active\'').get(current);
    if (!row) throw new Error(`active scope was not found: ${current}`);
    chain.push({ ...row, metadata: parseJson(row.metadata_json, {}) });
    current = row.parent_scope_id;
  }
  chain.reverse();
  if (chain[0]?.scope_kind !== 'core') throw new Error('scope hierarchy must start at core');
  return chain;
}

export function createTaskScope(databasePath = defaultDatabasePath, { taskId, parentScopeId, name, summary }) {
  if (!String(taskId ?? '').trim()) throw new Error('taskId is required');
  const database = open(resolve(databasePath));
  try {
    scopeChain(database, parentScopeId);
    const id = `scope:task:${String(taskId).trim()}`;
    const timestamp = now();
    database.prepare(`INSERT OR IGNORE INTO scope_passports
      (id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at)
      VALUES (?,'task',?,?,?,'active',?, ?, ?)`).run(id, parentScopeId, name, summary,
        canonical({ task_id: String(taskId).trim() }), timestamp, timestamp);
    const row = database.prepare('SELECT id,scope_kind,parent_scope_id,name,summary,status FROM scope_passports WHERE id=?').get(id);
    if (!row || row.parent_scope_id !== parentScopeId) throw new Error('task scope conflicts with an existing passport');
    return row;
  } finally { database.close(); }
}

export function selectCoordinatorSkills(profileId, taskType, selectedSkills = []) {
  const profile = COORDINATOR_PROFILES[profileId];
  if (!profile || profile.status !== 'active') throw new Error('unknown or inactive coordinator profile');
  if (!profile.task_types.includes(taskType)) throw new Error('task type is not allowed by coordinator profile');
  if (!Array.isArray(selectedSkills) || selectedSkills.some((item) => !nonEmptyText(item))) {
    throw new Error('selected skills must be a list of identifiers');
  }
  const normalized = selectedSkills.map((item) => item.trim());
  if (new Set(normalized).size !== normalized.length) throw new Error('selected skills contain duplicates');
  if (normalized.some((item) => !profile.allowed_skills[taskType].includes(item))) {
    throw new Error('unknown or disallowed skill');
  }
  return normalized;
}

function appliesTo(record, taskType, includeHistory) {
  if (!includeHistory && (record.layer === 'historical' || record.lifecycle_status !== 'active')) return false;
  if (includeHistory && !['active', 'superseded', 'outdated', 'historical'].includes(record.lifecycle_status)) return false;
  const taskTypes = parseJson(record.task_types_json, []);
  return taskTypes.includes('all') || taskTypes.includes(taskType);
}

function referenceMetadata(record) {
  const metadata = parseJson(record.metadata_json, {});
  return metadata.reference_type === 'approved_memory_candidate' ? metadata : null;
}

function compactReference(record) {
  const metadata = referenceMetadata(record);
  if (!metadata) return null;
  return {
    semantic_key: record.semantic_key,
    scope_id: record.scope_id,
    title: record.title,
    summary: record.content,
    source: record.source_ref,
    authority: metadata.authority,
    project_id: metadata.project_id,
    candidate_id: metadata.candidate_id,
    candidate_semantic_key: metadata.candidate_semantic_key,
    keyword_count: metadata.keyword_count,
  };
}

export function loadReferencedMemory(projectDatabasePath = defaultProjectDatabasePath, records, taskType) {
  if (!['editorial', 'research'].includes(taskType)) {
    throw new Error('referenced memory may be expanded only for an explicit editorial or research task');
  }
  const references = records.map((record) => ({ record, metadata: referenceMetadata(record) }))
    .filter(({ metadata }) => metadata);
  if (!references.length) return [];
  const database = open(resolve(projectDatabasePath), true);
  try {
    const metadataTable = database.prepare(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_storage_metadata'",
    ).get();
    if (!metadataTable) throw new Error('referenced memory source is not a project SQLite');
    const storage = database.prepare('SELECT project_id,storage_format FROM project_storage_metadata WHERE singleton=1').get();
    if (!storage || storage.project_id !== METRICHIT_PROJECT_ID) {
      throw new Error('referenced memory source has an unexpected project identity');
    }
    return references.map(({ record, metadata }) => {
      if (metadata.authority !== 'project_sqlite' || metadata.project_id !== storage.project_id) {
        throw new Error(`invalid authority metadata for ${record.semantic_key}`);
      }
      const candidate = database.prepare(`SELECT id,semantic_key,title,content,data_json,status
        FROM memory_candidates WHERE id=?`).get(metadata.candidate_id);
      if (!candidate || candidate.status !== 'approved' || candidate.semantic_key !== metadata.candidate_semantic_key) {
        throw new Error(`authoritative approved memory candidate was not found for ${record.semantic_key}`);
      }
      if (hash(candidate.content ?? '') !== metadata.content_sha256 || hash(candidate.data_json ?? '') !== metadata.data_json_sha256) {
        throw new Error(`authoritative memory hash mismatch for ${record.semantic_key}`);
      }
      const data = parseJson(candidate.data_json, null);
      const taxonomyCount = data?.taxonomy && typeof data.taxonomy === 'object'
        ? Object.values(data.taxonomy).reduce((total, values) => total + (Array.isArray(values) ? values.length : 0), 0)
        : 0;
      if (data?.keyword_count !== metadata.keyword_count || taxonomyCount !== metadata.keyword_count) {
        throw new Error(`authoritative keyword count mismatch for ${record.semantic_key}`);
      }
      return {
        ...compactReference(record),
        title: candidate.title,
        content: candidate.content,
        data,
        source_database: 'project.sqlite',
        storage_format: storage.storage_format,
      };
    });
  } finally { database.close(); }
}

export function resolveScopedMemory(database, scopeId, taskType, { includeHistory = false } = {}) {
  const chain = scopeChain(database, scopeId);
  const rank = new Map(chain.map((scope, index) => [scope.id, index]));
  const placeholders = chain.map(() => '?').join(',');
  const rows = database.prepare(
    `SELECT * FROM scoped_memory_records WHERE scope_id IN (${placeholders}) ORDER BY valid_from,id`,
  ).all(...chain.map((scope) => scope.id)).filter((row) => appliesTo(row, taskType, includeHistory));
  const selected = new Map();
  for (const row of rows.sort((a, b) => rank.get(a.scope_id) - rank.get(b.scope_id)
    || a.semantic_key.localeCompare(b.semantic_key)
    || Number(a.lifecycle_status === 'active') - Number(b.lifecycle_status === 'active')
    || a.valid_from.localeCompare(b.valid_from) || a.id.localeCompare(b.id))) {
    const prior = selected.get(row.semantic_key);
    if (prior?.rule_effect === 'prohibit' && prior.scope_id === SCOPE_IDS.core) continue;
    selected.set(row.semantic_key, row);
  }
  return { chain, records: [...selected.values()] };
}

function inferTaskType(text, explicit) {
  if (explicit) return explicit;
  if (/(research|исследован|семантическ|ключев.{0,20}запрос)/iu.test(text)) return 'research';
  if (/(стать|редак|контент|social|smm|публикац|пост|tenchat|тенчат)/iu.test(text)) return 'editorial';
  if (/(интерфейс|\bui\b|css|html|e2e|operator panel)/iu.test(text)) return 'ui';
  if (/(памят|governance|policy|правил)/iu.test(text)) return 'governance';
  if (/(документ|документац|\bdocs?\b|readme)/iu.test(text)) return 'docs';
  if (/(\bcode\b|\bpython\b|\bjavascript\b|\bnode\b|скрипт|компилятор|router|маршрутизатор|модул|тест)/iu.test(text)) return 'code';
  return 'general';
}

function hasTable(database, name) {
  return Boolean(database.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name));
}

const REQUIRED_EDITORIAL_RULES = Object.freeze({
  semanticCore: 'content.public_editorial_semantic_core_policy',
  targetQueryVolumeLadder: 'content.public_editorial_target_query_volume_ladder_policy',
  geoDemandGate: 'content.geo_demand_gate_automation',
  indexationPfTarget: 'content.public_editorial_yandex_indexation_pf_target_policy',
  vkPostWritingStandard: 'editorial.vk_post_writing_standard',
  article: 'content.editorial_article_preparation_policy',
  tenchat: 'editorial.tenchat_format_and_search_policy',
});
const OWNER_H1_OBLIGATION_TITLE = 'Статьи: ключевые ВЧ-запросы в главном заголовке';
const OWNER_H1_SEMANTIC_KEY = 'owner.editorial.h1_high_frequency_query';

function editorialRequirementApplies(candidate, signals) {
  const data = parseJson(candidate.data_json, {});
  const isTenChat = signals.includes('tenchat');
  const isArticle = signals.includes('article') || isTenChat;
  const isTelegram = signals.includes('telegram');
  if (candidate.semantic_key === REQUIRED_EDITORIAL_RULES.article) return isArticle;
  if (candidate.semantic_key === REQUIRED_EDITORIAL_RULES.tenchat) return isTenChat;
  if (candidate.semantic_key === REQUIRED_EDITORIAL_RULES.semanticCore) return !isTelegram;
  if (candidate.semantic_key === REQUIRED_EDITORIAL_RULES.targetQueryVolumeLadder) return !isTelegram && (isArticle || isTenChat);
  if (candidate.semantic_key === REQUIRED_EDITORIAL_RULES.geoDemandGate) return !isTelegram && (isArticle || isTenChat);
  if (candidate.semantic_key === REQUIRED_EDITORIAL_RULES.indexationPfTarget) return !isTelegram;
  if (data.channel) return signals.includes(String(data.channel).toLocaleLowerCase('ru-RU'));
  if (data.platform) return signals.includes(String(data.platform).toLocaleLowerCase('ru-RU'));
  if (candidate.semantic_key === 'content.test_bonus_messaging') return signals.includes('bonus');
  if (candidate.semantic_key === 'content.public_pf_positive_framing') return signals.includes('pf');
  return true;
}

export function resolveApprovedEditorialRequirements(database, route) {
  if (route.taskType !== 'editorial' || route.scopeId !== SCOPE_IDS.editorial) return [];
  if (!hasTable(database, 'memory_candidates') || !hasTable(database, 'tasks')) {
    throw new Error('applicable approved editorial memory is unavailable');
  }
  const signals = Array.isArray(route.signals) ? route.signals : [];
  const approved = database.prepare(`SELECT id,type,semantic_key,title,content,data_json,source_id
    FROM memory_candidates WHERE status='approved' ORDER BY semantic_key,id`).all();
  const currentBySemanticKey = new Map();
  for (const row of approved) {
    const current = currentBySemanticKey.get(row.semantic_key);
    const revision = Number(parseJson(row.data_json, {}).revision ?? 0);
    const currentRevision = Number(parseJson(current?.data_json, {}).revision ?? 0);
    if (!current || revision > currentRevision || (revision === currentRevision && row.id.localeCompare(current.id) > 0)) currentBySemanticKey.set(row.semantic_key, row);
  }
  const currentApproved = [...currentBySemanticKey.values()];
  const directness = currentApproved.find((row) => row.semantic_key === 'content.editorial_directness_policy');
  const superseded = new Set(parseJson(directness?.data_json, {}).supersedes_editorial_rules ?? []);
  const requirements = currentApproved.filter((row) => row.type === 'editorial_rule'
      && !superseded.has(row.semantic_key) && editorialRequirementApplies(row, signals))
    .map((row) => ({
      id: row.id, semantic_key: row.semantic_key, scope_id: SCOPE_IDS.editorial,
      type: 'rule', title: row.title, content: row.content,
      source: `approved-memory://memory_candidates/${row.id}`, effect: 'require',
      metadata: parseJson(row.data_json, {}), authority: 'approved_memory',
    }));
  const requiredKeys = [];
  if (signals.includes('article') || signals.includes('tenchat')) requiredKeys.push(REQUIRED_EDITORIAL_RULES.article);
  if (signals.includes('tenchat')) requiredKeys.push(REQUIRED_EDITORIAL_RULES.tenchat);
  for (const semanticKey of requiredKeys) {
    if (!requirements.some((item) => item.semantic_key === semanticKey)) {
      throw new Error(`applicable approved editorial requirement is unavailable: ${semanticKey}`);
    }
  }
  if (signals.includes('article') || signals.includes('tenchat')) {
    requirements.push({
      id: `${EDITORIAL_CONTRACT.id}:h1`, semantic_key: OWNER_H1_SEMANTIC_KEY, scope_id: SCOPE_IDS.editorial,
      type: 'commitment', title: OWNER_H1_OBLIGATION_TITLE,
      content: `В H1 используется ровно одна утверждённая короткая форма: ${PLANNER_H1_HIGH_FREQUENCY_MARKERS.join(', ')}. ВЧ-маркер нельзя размывать дополнительными словами.`,
      source: 'config/editorial-contract.json', effect: 'require', authority: 'editorial_contract',
      metadata: { required_h1_queries: [...PLANNER_H1_HIGH_FREQUENCY_MARKERS] },
    });
  }
  return requirements.sort((a, b) => a.semantic_key.localeCompare(b.semantic_key) || a.id.localeCompare(b.id));
}

function approvedSemanticCoreTaxonomy(projectDatabasePath, references) {
  const reference = loadReferencedMemory(projectDatabasePath, references, 'editorial')
    .find((item) => item.semantic_key === SEMANTIC_CORE_REFERENCE_KEY);
  const taxonomy = reference?.data?.taxonomy;
  if (!taxonomy || typeof taxonomy !== 'object' || !Object.values(taxonomy).every(Array.isArray)) {
    throw new Error('approved semantic core taxonomy is unavailable');
  }
  return taxonomy;
}

function editorialSemanticsFromBrief(taskBrief, rules, semanticCoreTaxonomy = null) {
  if (!rules.some((rule) => rule.semantic_key === REQUIRED_EDITORIAL_RULES.semanticCore)) return null;
  const source = taskBrief.editorialSemantics ?? {};
  const semanticContext = {
    selected_clusters: Array.isArray(source.selectedClusters)
      ? source.selectedClusters.map(nonEmptyText).filter(Boolean) : null,
    adjacent_cluster_rationale: nonEmptyText(source.adjacentClusterRationale),
    primary_target_query: nonEmptyText(source.primaryTargetQuery),
    secondary_target_queries: Array.isArray(source.secondaryTargetQueries)
      ? source.secondaryTargetQueries.map(nonEmptyText).filter(Boolean) : null,
    user_intent: nonEmptyText(source.userIntent),
    platform: nonEmptyText(source.platform),
    format: nonEmptyText(source.format),
    core_reference: SEMANTIC_CORE_REFERENCE_KEY,
  };
  const missing = Object.entries(semanticContext)
    .filter(([key, value]) => key !== 'adjacent_cluster_rationale' && !value)
    .map(([key]) => `editorial_semantics.${key}`);
  if (missing.length) throw new Error(`execution card is incomplete: ${missing.join(', ')}`);
  if (!['article', 'social_post'].includes(semanticContext.format)) {
    throw new Error('execution card is incomplete: editorial_semantics.format');
  }
  if (!Array.isArray(semanticContext.secondary_target_queries)) {
    throw new Error('execution card is incomplete: editorial_semantics.secondary_target_queries');
  }
  if (!Array.isArray(semanticContext.selected_clusters) || !semanticContext.selected_clusters.length) {
    throw new Error('execution card is incomplete: editorial_semantics.selected_clusters');
  }
  if (new Set(semanticContext.selected_clusters).size !== semanticContext.selected_clusters.length) {
    throw new Error('execution card is incomplete: editorial_semantics.duplicate_selected_cluster');
  }
  const selectedClusterQueries = semanticContext.selected_clusters.flatMap((cluster) => {
    const queries = semanticCoreTaxonomy?.[cluster];
    if (!Array.isArray(queries)) {
      throw new Error('execution card is incomplete: editorial_semantics.selected_cluster_not_in_approved_core');
    }
    return queries;
  });
  if (semanticContext.selected_clusters.length > 1 && !semanticContext.adjacent_cluster_rationale) {
    throw new Error('execution card is incomplete: editorial_semantics.adjacent_cluster_rationale');
  }
  const targetQueries = [semanticContext.primary_target_query, ...semanticContext.secondary_target_queries];
  if (new Set(targetQueries).size !== targetQueries.length) {
    throw new Error('execution card is incomplete: editorial_semantics.duplicate_target_query');
  }
  if (targetQueries.some((query) => !selectedClusterQueries.includes(query))) {
    throw new Error('execution card is incomplete: editorial_semantics.target_query_not_in_selected_approved_core_clusters');
  }
  if (rules.some((rule) => rule.semantic_key === REQUIRED_EDITORIAL_RULES.geoDemandGate)
    && semanticContext.selected_clusters.includes('geo_candidates_after_demand_validation')) {
    if (source.geoDemandOwnerConfirmed !== true) {
      throw new Error('execution card is incomplete: editorial_semantics.geo_demand_owner_confirmed');
    }
    semanticContext.geo_demand_owner_confirmed = true;
  }
  return semanticContext;
}

function editorialIndexationFromBrief(taskBrief, rules) {
  if (!rules.some((rule) => rule.semantic_key === REQUIRED_EDITORIAL_RULES.indexationPfTarget)) return null;
  const source = taskBrief.editorialIndexation ?? {};
  const indexationContext = {
    seo_indexation_objective: nonEmptyText(source.seoIndexationObjective),
    future_pf_campaign: {
      requires_independently_verified_yandex_indexation_after_publication: true,
      separate_owner_approval_required: true,
      auto_authorized: false,
    },
  };
  const missing = !indexationContext.seo_indexation_objective ? ['editorial_indexation.seo_indexation_objective'] : [];
  if (missing.length) throw new Error(`execution card is incomplete: ${missing.join(', ')}`);
  return indexationContext;
}

function publicationReconciliationFromBrief(taskBrief, route) {
  const publicationTask = route.taskType === 'editorial' && route.scopeId === SCOPE_IDS.editorial
    && route.signals.includes('confirmed_publication');
  const source = taskBrief.publicationReconciliation;
  if (!publicationTask && (source === undefined || source === null)) return null;
  const entries = Array.isArray(source) ? source : source?.publications;
  if (!Array.isArray(entries) || !entries.length) {
    throw new Error('execution card is incomplete: publication_reconciliation.publications');
  }
  const publications = entries.map((entry) => {
    const platform = nonEmptyText(entry?.platform);
    const title = nonEmptyText(entry?.title);
    const publishedAt = nonEmptyText(entry?.publishedAt ?? entry?.published_at ?? entry?.publishedDate);
    const publishedDate = publishedAt?.slice(0, 10);
    const validPublishedDate = /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(publishedAt ?? '')
      && Number.isFinite(Date.parse(`${publishedDate}T00:00:00Z`))
      && new Date(`${publishedDate}T00:00:00Z`).toISOString().slice(0, 10) === publishedDate;
    const url = nonEmptyText(entry?.url);
    const ownerConfirmation = nonEmptyText(entry?.ownerConfirmation ?? entry?.owner_confirmation);
    if (!platform || !title || !validPublishedDate
      || Boolean(url) === Boolean(ownerConfirmation) || (url && !/^https:\/\//iu.test(url))) {
      throw new Error('execution card is incomplete: publication_reconciliation.publication');
    }
    return {
      platform, title, published_at: publishedDate,
      url: url || null, owner_confirmation: ownerConfirmation || null,
    };
  });
  if (new Set(publications.map((item) => canonical(item))).size !== publications.length) {
    throw new Error('execution card is incomplete: publication_reconciliation.duplicate_publication');
  }
  return { required: true, publications };
}

function editorialQaRequirements(rules, editorialSemantics, editorialIndexation) {
  const keys = new Set(rules.map((rule) => rule.semantic_key));
  if (!keys.has(REQUIRED_EDITORIAL_RULES.semanticCore)
    && !keys.has(REQUIRED_EDITORIAL_RULES.article) && !keys.has(REQUIRED_EDITORIAL_RULES.tenchat)) return null;
  const checks = [];
  if (keys.has(REQUIRED_EDITORIAL_RULES.semanticCore)) {
    checks.push({ id: 'semantic_cluster_selection', evidence_fields: ['selected_clusters', 'adjacent_cluster_rationale', 'primary_target_query', 'secondary_target_queries', 'user_intent', 'platform', 'core_reference', 'non_navigational'] });
    checks.push({ id: 'target_queries_approved_core', evidence_fields: ['core_reference', 'selected_clusters', 'primary_target_query', 'secondary_target_queries', 'target_queries_match_card', 'all_target_queries_approved', 'all_target_queries_in_selected_clusters', 'duplicate_target_queries', 'keyword_stuffing'] });
    checks.push({ id: 'primary_query_prominence', evidence_fields: ['primary_target_query', 'platform', 'location', 'natural', 'keyword_stuffing'] });
    checks.push({ id: 'adjacent_clusters_one_intent', evidence_fields: ['selected_clusters', 'adjacent_cluster_rationale', 'user_intent', 'clusters_are_adjacent', 'content_serves_selected_intent', 'unrelated_clusters_mixed'] });
    checks.push({ id: 'geo_demand_verification', evidence_fields: ['geo_candidate', 'demand_verification_required', 'demand_verified', 'verification_reference'] });
  }
  if (keys.has(REQUIRED_EDITORIAL_RULES.targetQueryVolumeLadder)) {
    checks.push({ id: 'target_query_volume_ladder', evidence_fields: ['character_count', 'count_scope', 'primary_target_query', 'secondary_target_queries', 'unique_target_query_count', 'required_minimum', 'required_maximum', 'count_rationale', 'all_secondary_target_queries_natural_in_body', 'keyword_stuffing'] });
  }
  if (keys.has(REQUIRED_EDITORIAL_RULES.vkPostWritingStandard)) {
    checks.push({ id: 'vk_body_character_count', evidence_fields: ['character_count', 'count_scope', 'length_band', 'rationale', 'not_extended_for_seo_only'] });
    checks.push({ id: 'vk_semantic_structure', evidence_fields: ['primary_target_query', 'selected_clusters', 'user_intent', 'in_headline', 'in_opening_paragraph', 'natural_mentions_total', 'keyword_stuffing', 'all_sections_serve_selected_query', 'opening_answers_query', 'useful_subheads_or_checklist', 'concrete_practical_details', 'practical_conclusion', 'natural_cta', 'padding_or_repetition', 'unsupported_seo_claims'] });
  }
  if (keys.has(REQUIRED_EDITORIAL_RULES.article)) {
    checks.push({ id: 'landing_link_distribution', evidence_fields: ['url', 'exact_count', 'positions', 'natural_anchors', 'link_spam'] });
    checks.push({ id: 'originality_source_overlap', evidence_fields: ['method', 'content_sha256', 'compared_sources', 'max_overlap_percent', 'template_match'] });
  }
  if (keys.has(OWNER_H1_SEMANTIC_KEY)) {
    checks.push({ id: 'h1_high_frequency_query', evidence_fields: ['heading', 'matched_query'] });
  }
  if (keys.has(REQUIRED_EDITORIAL_RULES.tenchat)) {
    checks.push({ id: 'tenchat_character_count', evidence_fields: ['character_count', 'maximum', 'target_minimum', 'target_maximum', 'within_target'] });
    checks.push({ id: 'single_search_intent', evidence_fields: ['intent_count', 'primary_intent'] });
    checks.push({ id: 'natural_primary_keyword', evidence_fields: ['primary_keyword', 'in_title', 'in_opening', 'natural'] });
    checks.push({ id: 'link_count_and_spam', evidence_fields: ['link_count', 'minimum', 'maximum', 'link_spam'] });
  }
  return {
    required: true, checks, semantic_context: editorialSemantics, indexation_context: editorialIndexation,
    external_detection: {
      plagiarism: 'unavailable_or_not_performed',
      ai_detection: 'unavailable_or_not_performed',
    },
  };
}

function editorialVisualPackage(rules, editorialSemantics, editorialPipeline, route) {
  const policy = rules.find((rule) => rule.semantic_key === EDITORIAL_VISUAL_STANDARD_KEY)?.metadata;
  if (!policy?.article_image_brief) return null;
  const platform = editorialSemantics?.platform ?? editorialPipeline?.platform?.name ?? route?.platform?.name ?? null;
  const isOborot = articlePlatformRoute(platform)?.id === 'oborot';
  return {
    platform,
    default: policy.article_image_brief,
    long_form: isOborot ? policy.oborot_long_form_image_brief ?? null : null,
  };
}

function buildExecutionCard(taskBrief, route, rules, semanticCoreTaxonomy, editorialPipeline = null) {
  const scope = nonEmptyList(taskBrief.scope ?? taskBrief.allowedChanges);
  const acceptance = nonEmptyList(taskBrief.acceptance);
  const forbiddenChanges = nonEmptyList(taskBrief.forbiddenChanges);
  const pipelineTrigger = route.signals.includes('article_pipeline_trigger');
  const editorialSemantics = pipelineTrigger ? null : editorialSemanticsFromBrief(taskBrief, rules, semanticCoreTaxonomy);
  const editorialIndexation = pipelineTrigger ? null : editorialIndexationFromBrief(taskBrief, rules);
  const publicationReconciliation = publicationReconciliationFromBrief(taskBrief, route);
  const card = {
    result: nonEmptyText(taskBrief.result),
    scope,
    task_type: route.taskType,
    target_scope: route.scopeId,
    mandatory_rules: [
      { semantic_key: 'governance.constitution', source: 'AGENTS.md', effect: 'mandatory' },
      ...rules.map((rule) => ({ semantic_key: rule.semantic_key, title: rule.title, content: rule.content,
        source: rule.source, effect: rule.effect ?? 'mandatory', authority: rule.authority ?? 'scoped_memory' })),
    ],
    editorial_semantics: editorialSemantics,
    editorial_indexation: editorialIndexation,
    editorial_revision: route.articleRevisionContext ?? null,
    editorial_visual_package: editorialVisualPackage(rules, editorialSemantics, editorialPipeline, route),
    editorial_spec: editorialPipeline?.editorial_spec ?? null,
    publication_reconciliation: publicationReconciliation,
    delivery_qa: pipelineTrigger ? null : editorialQaRequirements(rules, editorialSemantics, editorialIndexation),
    editorial_pipeline: editorialPipeline ? {
      ...editorialPipeline,
      platform: route.platform,
      stage_handoff: 'next stage starts only after the preceding stage completes',
      planner_semantic_gate: 'planner must populate article semantics before architect and writer start',
    } : null,
    first_check: nonEmptyText(taskBrief.firstCheck),
    acceptance,
    forbidden_changes: forbiddenChanges,
  };
  const missing = [];
  if (!card.result) missing.push('result');
  if (!card.scope.length) missing.push('scope');
  if (!card.task_type) missing.push('task_type');
  if (!card.target_scope) missing.push('target_scope');
  if (!card.mandatory_rules.length) missing.push('mandatory_rules');
  if (!card.first_check) missing.push('first_check');
  if (!card.acceptance.length) missing.push('acceptance');
  if (!card.forbidden_changes.length) missing.push('forbidden_changes');
  if (missing.length) throw new Error(`execution card is incomplete: ${missing.join(', ')}`);
  return card;
}

function validateEditorialContentQa(specification, contentQa) {
  if (!specification?.required) return null;
  if (!contentQa || !Array.isArray(contentQa.checks)) {
    throw new Error('delivery validation failed: editorial_content_qa_missing');
  }
  const reports = new Map(contentQa.checks.map((item) => [item?.id, item]));
  if (reports.size !== contentQa.checks.length) {
    throw new Error('delivery validation failed: editorial_content_qa_duplicate_check');
  }
  const exactReports = [];
  for (const required of specification.checks) {
    const report = reports.get(required.id);
    if (!report || report.performed !== true || report.passed !== true || !nonEmptyText(report.result)
      || !report.evidence || typeof report.evidence !== 'object') {
      throw new Error(`delivery validation failed: editorial_content_qa_incomplete:${required.id}`);
    }
    if (required.evidence_fields.some((field) => !Object.hasOwn(report.evidence, field))) {
      throw new Error(`delivery validation failed: editorial_content_qa_evidence:${required.id}`);
    }
    exactReports.push({ id: required.id, performed: true, passed: true,
      result: report.result.trim(), evidence: report.evidence });
  }
  const byId = new Map(exactReports.map((item) => [item.id, item.evidence]));
  const semanticContext = specification.semantic_context;
  const selection = byId.get('semantic_cluster_selection');
  if (selection && (!semanticContext
    || canonical(selection.selected_clusters) !== canonical(semanticContext.selected_clusters)
    || selection.adjacent_cluster_rationale !== semanticContext.adjacent_cluster_rationale
    || selection.primary_target_query !== semanticContext.primary_target_query
    || canonical(selection.secondary_target_queries) !== canonical(semanticContext.secondary_target_queries)
    || selection.user_intent !== semanticContext.user_intent
    || selection.platform !== semanticContext.platform
    || selection.core_reference !== semanticContext.core_reference
    || selection.non_navigational !== true)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:semantic_cluster_selection');
  }
  const approvedTargets = byId.get('target_queries_approved_core');
  if (approvedTargets && (!semanticContext
    || approvedTargets.core_reference !== semanticContext.core_reference
    || canonical(approvedTargets.selected_clusters) !== canonical(semanticContext.selected_clusters)
    || approvedTargets.primary_target_query !== semanticContext.primary_target_query
    || canonical(approvedTargets.secondary_target_queries) !== canonical(semanticContext.secondary_target_queries)
    || approvedTargets.target_queries_match_card !== true
    || approvedTargets.all_target_queries_approved !== true
    || approvedTargets.all_target_queries_in_selected_clusters !== true
    || approvedTargets.duplicate_target_queries !== false
    || approvedTargets.keyword_stuffing !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:target_queries_approved_core');
  }
  const targetQueryVolume = byId.get('target_query_volume_ladder');
  if (targetQueryVolume) {
    const targetQueries = semanticContext ? [semanticContext.primary_target_query, ...semanticContext.secondary_target_queries] : [];
    const expectedBand = targetQueryVolumeBand(targetQueryVolume.character_count);
    const matchingBand = expectedBand
      && targetQueryVolume.required_minimum === expectedBand.minimumQueries
      && targetQueryVolume.required_maximum === expectedBand.maximumQueries;
    if (!semanticContext || !Number.isInteger(targetQueryVolume.character_count) || targetQueryVolume.character_count < 0
      || targetQueryVolume.count_scope !== 'russian_body_excluding_internal_metadata_and_urls'
      || targetQueryVolume.primary_target_query !== semanticContext.primary_target_query
      || canonical(targetQueryVolume.secondary_target_queries) !== canonical(semanticContext.secondary_target_queries)
      || targetQueryVolume.unique_target_query_count !== targetQueries.length
      || new Set(targetQueries).size !== targetQueries.length
      || targetQueryVolume.all_secondary_target_queries_natural_in_body !== true
      || targetQueryVolume.keyword_stuffing !== false
      || (expectedBand && (!matchingBand || targetQueryVolume.unique_target_query_count < expectedBand.minimumQueries || targetQueryVolume.unique_target_query_count > expectedBand.maximumQueries || targetQueryVolume.count_rationale !== null))
      || (!expectedBand && (targetQueryVolume.required_minimum !== null || targetQueryVolume.required_maximum !== null || !nonEmptyText(targetQueryVolume.count_rationale)))) {
      throw new Error('delivery validation failed: editorial_content_qa_failed:target_query_volume_ladder');
    }
  }
  const prominence = byId.get('primary_query_prominence');
  const allowedProminentLocations = semanticContext?.format === 'article' ? ['h1'] : ['headline', 'opening_paragraph'];
  if (prominence && (!semanticContext
    || prominence.primary_target_query !== semanticContext.primary_target_query
    || prominence.platform !== semanticContext.platform
    || !allowedProminentLocations.includes(prominence.location)
    || prominence.natural !== true || prominence.keyword_stuffing !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:primary_query_prominence');
  }
  const adjacentClusters = byId.get('adjacent_clusters_one_intent');
  if (adjacentClusters && (!semanticContext
    || canonical(adjacentClusters.selected_clusters) !== canonical(semanticContext.selected_clusters)
    || adjacentClusters.adjacent_cluster_rationale !== semanticContext.adjacent_cluster_rationale
    || adjacentClusters.user_intent !== semanticContext.user_intent
    || adjacentClusters.clusters_are_adjacent !== true
    || adjacentClusters.content_serves_selected_intent !== true
    || adjacentClusters.unrelated_clusters_mixed !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:adjacent_clusters_one_intent');
  }
  const geoDemand = byId.get('geo_demand_verification');
  if (geoDemand && (typeof geoDemand.geo_candidate !== 'boolean'
    || geoDemand.demand_verification_required !== true
    || (geoDemand.geo_candidate === true && (geoDemand.demand_verified !== true || !nonEmptyText(geoDemand.verification_reference))))) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:geo_demand_verification');
  }
  const links = byId.get('landing_link_distribution');
  if (links && (links.url !== 'https://go.mtrhit.ru/' || links.exact_count !== 4
    || canonical(links.positions) !== canonical(['beginning', 'body_1', 'body_2', 'final_cta'])
    || links.natural_anchors !== true || links.link_spam !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:landing_link_distribution');
  }
  const originality = byId.get('originality_source_overlap');
  const overlapValues = Array.isArray(originality?.compared_sources)
    ? originality.compared_sources.map((item) => item.overlap_percent) : [];
  if (originality && (originality.method !== 'local_deterministic_source_overlap'
    || !/^[a-f0-9]{64}$/.test(originality.content_sha256 ?? '')
    || !Array.isArray(originality.compared_sources) || !originality.compared_sources.length
    || originality.compared_sources.some((item) => !nonEmptyText(item?.path) || !/^[a-f0-9]{64}$/.test(item?.sha256 ?? '')
      || typeof item?.overlap_percent !== 'number' || item.overlap_percent < 0 || item.overlap_percent > 100)
    || typeof originality.max_overlap_percent !== 'number' || originality.max_overlap_percent < 0
    || originality.max_overlap_percent > 100 || originality.max_overlap_percent !== Math.max(...overlapValues)
    || originality.template_match !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:originality_source_overlap');
  }
  const h1 = byId.get('h1_high_frequency_query');
  const normalizedHeading = nonEmptyText(h1?.heading)?.toLocaleLowerCase('ru-RU') ?? null;
  const normalizedMatchedQuery = nonEmptyText(h1?.matched_query)?.toLocaleLowerCase('ru-RU') ?? null;
  if (h1 && (!normalizedHeading || !APPROVED_H1_HIGH_FREQUENCY_QUERIES.includes(normalizedMatchedQuery)
    || normalizedHeading !== normalizedMatchedQuery)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:h1_high_frequency_query');
  }
  const length = byId.get('tenchat_character_count');
  if (length && (!Number.isInteger(length.character_count) || length.character_count < 0 || length.maximum !== 7000
    || length.target_minimum !== 4000 || length.target_maximum !== 5500 || typeof length.within_target !== 'boolean'
    || length.character_count > length.maximum
    || length.within_target !== (length.character_count >= length.target_minimum && length.character_count <= length.target_maximum))) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:tenchat_character_count');
  }
  const intent = byId.get('single_search_intent');
  if (intent && (intent.intent_count !== 1 || !nonEmptyText(intent.primary_intent))) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:single_search_intent');
  }
  const keyword = byId.get('natural_primary_keyword');
  if (keyword && (!nonEmptyText(keyword.primary_keyword) || keyword.in_title !== true
    || keyword.in_opening !== true || keyword.natural !== true)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:natural_primary_keyword');
  }
  const linkSpam = byId.get('link_count_and_spam');
  if (linkSpam && (!Number.isInteger(linkSpam.link_count) || linkSpam.minimum !== 2 || linkSpam.maximum !== 4
    || linkSpam.link_count < 2 || linkSpam.link_count > 4 || linkSpam.link_spam !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:link_count_and_spam');
  }
  const vkLength = byId.get('vk_body_character_count');
  if (vkLength && (!Number.isInteger(vkLength.character_count) || vkLength.character_count < 1200 || vkLength.character_count > 4000
    || vkLength.count_scope !== 'russian_post_body_excluding_internal_metadata_and_urls'
    || !['target', 'narrow_news_or_checklist', 'detailed_practical_breakdown'].includes(vkLength.length_band)
    || vkLength.not_extended_for_seo_only !== true
    || (vkLength.length_band === 'target' && (vkLength.character_count < 1800 || vkLength.character_count > 2800 || vkLength.rationale !== null))
    || (vkLength.length_band === 'narrow_news_or_checklist' && (vkLength.character_count < 1200 || vkLength.character_count > 1799 || !nonEmptyText(vkLength.rationale)))
    || (vkLength.length_band === 'detailed_practical_breakdown' && (vkLength.character_count < 3000 || vkLength.character_count > 4000 || !nonEmptyText(vkLength.rationale))))) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:vk_body_character_count');
  }
  const vkStructure = byId.get('vk_semantic_structure');
  if (vkStructure && (!semanticContext
    || vkStructure.primary_target_query !== semanticContext.primary_target_query
    || canonical(vkStructure.selected_clusters) !== canonical(semanticContext.selected_clusters)
    || vkStructure.user_intent !== semanticContext.user_intent
    || vkStructure.in_headline !== true || vkStructure.in_opening_paragraph !== true
    || !Number.isInteger(vkStructure.natural_mentions_total) || vkStructure.natural_mentions_total < 2 || vkStructure.natural_mentions_total > 3
    || vkStructure.keyword_stuffing !== false || vkStructure.all_sections_serve_selected_query !== true
    || vkStructure.opening_answers_query !== true || vkStructure.useful_subheads_or_checklist !== true
    || vkStructure.concrete_practical_details !== true || vkStructure.practical_conclusion !== true
    || vkStructure.natural_cta !== true || vkStructure.padding_or_repetition !== false
    || vkStructure.unsupported_seo_claims !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:vk_semantic_structure');
  }
  const external = contentQa.external_checks;
  for (const id of ['plagiarism', 'ai_detection']) {
    if (!external?.[id] || !['unavailable', 'not_performed'].includes(external[id].status)
      || !nonEmptyText(external[id].result)) {
      throw new Error(`delivery validation failed: editorial_external_check_claim:${id}`);
    }
  }
  return { local_deterministic_checks: exactReports, external_checks: external };
}

function validateDeliveryEvidence(card, delivery) {
  const checks = nonEmptyList(delivery.checks);
  const satisfiedAcceptance = nonEmptyList(delivery.satisfiedAcceptance);
  const forbiddenChangesObserved = nonEmptyList(delivery.forbiddenChangesObserved);
  const missing = [];
  if (!nonEmptyText(delivery.result)) missing.push('result');
  if (delivery.scopeCompliance !== true) missing.push('scope_compliance');
  if (!checks.includes(card.first_check)) missing.push('first_check_evidence');
  if (!card.acceptance.every((criterion) => satisfiedAcceptance.includes(criterion))) missing.push('acceptance_evidence');
  if (!Array.isArray(delivery.forbiddenChangesObserved)) missing.push('forbidden_changes_evidence');
  if (forbiddenChangesObserved.length) missing.push('forbidden_changes_observed');
  if (missing.length) throw new Error(`delivery validation failed: ${missing.join(', ')}`);
  const contentQa = validateEditorialContentQa(card.delivery_qa, delivery.contentQa);
  const artifactValidation = card.editorial_spec
    ? validateEditorialArtifact(card.editorial_spec, delivery.artifact ?? {}) : null;
  return {
    validated_at: now(), result: delivery.result.trim(), checks,
    satisfied_acceptance: satisfiedAcceptance, scope_compliant: true,
    forbidden_changes_observed: [], content_qa: contentQa, artifact_validation: artifactValidation,
  };
}

function validatePublicationReconciliation(specification, projectDatabasePath) {
  if (!specification?.required) return null;
  const project = new DatabaseSync(projectDatabasePath, { readOnly: true });
  try {
    const verified = specification.publications.map((publication) => {
      const row = project.prepare(`SELECT p.id,p.platform,m.title,p.published_at,p.url,p.confirmation_kind,p.confirmation_ref
        FROM editorial_publications p JOIN editorial_materials m ON m.id=p.material_id
        WHERE p.status='published' AND p.platform=? AND m.title=? AND substr(p.published_at,1,10)=?
          AND ((? IS NOT NULL AND p.url=?)
            OR (? IS NOT NULL AND p.confirmation_kind='owner' AND p.confirmation_ref=?))
        ORDER BY p.created_at DESC,p.id DESC LIMIT 1`).get(
        publication.platform, publication.title, publication.published_at,
        publication.url, publication.url, publication.owner_confirmation, publication.owner_confirmation,
      );
      if (!row) throw new Error(`delivery validation failed: editorial_publication_not_recorded:${publication.platform}:${publication.title}`);
      return {
        publication_id: row.id, platform: row.platform, title: row.title,
        published_at: row.published_at, url: row.url, confirmation_kind: row.confirmation_kind,
      };
    });
    return { project_database: projectDatabasePath, verified_publications: verified };
  } finally { project.close(); }
}

export function routeTask(database, { text = '', explicitScopeId = null, taskType = null } = {}) {
  const rawText = String(text).trim();
  const normalized = rawText.toLocaleLowerCase('ru-RU');
  const fingerprint = hash(normalized);
  const requestedType = inferTaskType(normalized, taskType);
  const signals = [];
  const articleTriggerMatch = rawText.match(ARTICLE_PIPELINE_TRIGGER);
  const articleRevisionMatch = ARTICLE_REVISION_TRIGGER.test(rawText);
  const inferredType = articleTriggerMatch || articleRevisionMatch ? 'editorial' : requestedType;
  const platform = articleTriggerMatch ? articlePlatformRoute(articleTriggerMatch[1])
    : articleRevisionMatch ? articlePlatformFromText(rawText) : null;
  if (articleTriggerMatch && (!platform || !platform.contour)) {
    return { outcome: 'needs_clarification', scopeId: null, taskType: 'editorial',
      signals: ['editorial', 'article', 'article_pipeline_trigger', 'platform_unavailable'], fingerprint,
      question: 'Укажите одну поддерживаемую площадку из редакционной матрицы; unsupported и outside-MVP маршруты не запускаются.' };
  }
  if (articleTriggerMatch && platform) signals.push('article_pipeline_trigger', platform.id);
  if (articleRevisionMatch) {
    signals.push('article_revision');
    if (platform) signals.push(platform.id);
    if (/(?:стар\p{L}*\s+(?:картин|изображ|иллюстрац)|(?:картин|изображ|иллюстрац)\p{L}*\s+удал)/iu.test(normalized)) {
      signals.push('owner_authorized_asset_deletion');
    }
  }
  if (['editorial', 'research'].includes(inferredType)
    || /(стать|редак|контент|social|smm|публикац|пост|research|исследован|семантическ|ключев.{0,20}запрос|tenchat|тенчат)/iu.test(normalized)) signals.push('editorial');
  if (/(стать|article|лонгрид)/iu.test(normalized)) signals.push('article');
  if (/(tenchat|тенчат)/iu.test(normalized)) signals.push('tenchat');
  if (/(telegram|телеграм|(?:^|[^\p{L}\p{N}])тг(?:$|[^\p{L}\p{N}]))/iu.test(normalized)) signals.push('telegram');
  if (/(?:^|[^\p{L}\p{N}])(?:vk|вк)(?:$|[^\p{L}\p{N}])|вконтакте/iu.test(normalized)) signals.push('vk');
  if (/(?:^|[^\p{L}\p{N}])(?:пф|pf)(?:$|[^\p{L}\p{N}])|поведенческ|накрутк/iu.test(normalized)) signals.push('pf');
  if (/(бонус|1\s*000\s+клик)/iu.test(normalized)) signals.push('bonus');
  if (/(?:подтвержд|проверяем|верифицир).{0,80}(?:публик|https?:\/\/|ссылк)|(?:публик|https?:\/\/|ссылк).{0,80}(?:подтвержд|проверяем|верифицир)/iu.test(normalized)) {
    signals.push('confirmed_publication');
  }
  if (explicitScopeId) {
    scopeChain(database, explicitScopeId);
    if (articleRevisionMatch && explicitScopeId !== SCOPE_IDS.editorial) {
      throw new Error('editorial revision must use the Editorial scope');
    }
    const routed = { outcome: 'routed', scopeId: explicitScopeId, taskType: inferredType, signals: ['explicit_scope', ...signals], fingerprint,
      platform: platform ? { id: platform.id, name: platform.name, contour: platform.contour, mode: platform.mode,
        source: 'documents/editorial-publishing-matrix.md' } : null };
    if (articleRevisionMatch) Object.defineProperty(routed, 'articleRevisionSource', {
      value: latestDeliveredArticleContext(database, platform),
    });
    return routed;
  }
  const panelWord = /(панел)/iu.test(normalized);
  const panelSpecific = /(интерфейс|\bui\b|css|html|e2e|operator panel|backend)/iu.test(normalized);
  if (panelWord) signals.push('panel_word');
  if (panelSpecific) signals.push('panel_specific');
  if (/(metrichit|метрикхит)/iu.test(normalized)) signals.push('metrichit');
  if (/(ядр|\bcore\b)/iu.test(normalized)) signals.push('core');
  if (panelWord && !panelSpecific && !signals.includes('editorial')) {
    return { outcome: 'needs_clarification', scopeId: null, taskType: inferredType, signals, fingerprint,
      question: 'Уточните один scope: речь об operator panel MetricHit или о другой панели?' };
  }
  if (signals.includes('editorial') && panelSpecific) {
    return { outcome: 'needs_clarification', scopeId: null, taskType: inferredType, signals, fingerprint,
      question: 'Уточните один scope: «Редакция» или «Панель» MetricHit?' };
  }
  const scopeId = signals.includes('editorial') ? SCOPE_IDS.editorial
    : panelSpecific ? SCOPE_IDS.panel
      : signals.includes('core') && !signals.includes('metrichit') ? SCOPE_IDS.core : SCOPE_IDS.metrichit;
  scopeChain(database, scopeId);
  const articleRevisionSource = articleRevisionMatch ? latestDeliveredArticleContext(database, platform) : null;
  const routed = { outcome: 'routed', scopeId, taskType: inferredType, signals, fingerprint,
    platform: platform ? { id: platform.id, name: platform.name, contour: platform.contour, mode: platform.mode,
      source: 'documents/editorial-publishing-matrix.md' } : null };
  if (articleRevisionSource) Object.defineProperty(routed, 'articleRevisionSource', { value: articleRevisionSource });
  return routed;
}

export function compileDeterministicContext(database, {
  scopeId, taskType, includeHistory = false, includeReferencedContent = false,
  projectDatabasePath = defaultProjectDatabasePath, agentsContent = null, taskBrief = {}, route = null,
  coordinatorProfile = null,
}) {
  const resolved = resolveScopedMemory(database, scopeId, taskType, { includeHistory });
  const records = resolved.records.map((row) => ({
    id: row.id, semantic_key: row.semantic_key, scope_id: row.scope_id, layer: row.layer,
    type: row.record_type, status: row.lifecycle_status, title: row.title, content: row.content,
    source: row.source_ref, valid_from: row.valid_from, supersedes: row.supersedes_id,
    effect: row.rule_effect,
  }));
  const referenceRecords = resolved.records.filter((row) => referenceMetadata(row));
  const references = referenceRecords.map(compactReference);
  const expandedReferences = includeReferencedContent
    ? loadReferencedMemory(projectDatabasePath, referenceRecords, taskType) : [];
  const latestDecisions = records.filter((item) => item.type === 'decision')
    .sort((a, b) => b.valid_from.localeCompare(a.valid_from) || a.semantic_key.localeCompare(b.semantic_key)).slice(0, 5);
  const resolvedRoute = route ?? { scopeId, taskType, signals: [] };
  const effectiveRequirementRoute = resolved.chain.some((item) => item.id === SCOPE_IDS.editorial)
    ? { ...resolvedRoute, scopeId: SCOPE_IDS.editorial } : resolvedRoute;
  const approvedEditorialRequirements = resolveApprovedEditorialRequirements(database, effectiveRequirementRoute);
  const rules = [...new Map([...records.filter((item) => item.type === 'rule'), ...approvedEditorialRequirements]
    .map((item) => [item.semantic_key, item])).values()];
  const pipelineTrigger = resolvedRoute.signals.includes('article_pipeline_trigger');
  const semanticCoreTaxonomy = !pipelineTrigger && rules.some((rule) => rule.semantic_key === REQUIRED_EDITORIAL_RULES.semanticCore)
    ? approvedSemanticCoreTaxonomy(projectDatabasePath, referenceRecords) : null;
  const emptyTopicPlannerAssignment = pipelineTrigger
    ? automaticEmptyTopicPlannerAssignment(projectDatabasePath, resolvedRoute.platform) : null;
  const editorialSpec = pipelineTrigger
    ? automaticEditorialSpec(projectDatabasePath, resolvedRoute, emptyTopicPlannerAssignment) : null;
  const editorialPipeline = pipelineTrigger ? {
    ...loadEditorialPipeline(projectDatabasePath),
    launch_directive: emptyTopicPlannerAssignment.status === 'blocked' ? 'blocked' : 'start',
    empty_topic_planner_assignment: emptyTopicPlannerAssignment,
    editorial_spec: editorialSpec,
  } : null;
  const executionCard = buildExecutionCard(taskBrief, resolvedRoute, rules, semanticCoreTaxonomy, editorialPipeline);
  const payload = {
    schema_version: 4,
    compiler_version: COMPILER_VERSION,
    task_type: taskType,
    target_scope: scopeId,
    project_database_path: resolve(projectDatabasePath),
    execution_card: executionCard,
    execution_card_hash: hash(canonical(executionCard)),
    task_brief: {
      result: executionCard.result,
      allowed_changes: executionCard.scope,
      forbidden_changes: executionCard.forbidden_changes,
      first_check: executionCard.first_check,
      acceptance: executionCard.acceptance,
    },
    agents: agentsContent ?? readFileSync(agentsPath, 'utf8'),
    passports: resolved.chain.map((scope) => ({ id: scope.id, kind: scope.scope_kind, name: scope.name, summary: scope.summary })),
    rules,
    approved_editorial_requirements: approvedEditorialRequirements,
    decisions: latestDecisions,
    commitments: records.filter((item) => item.type === 'commitment'),
    references,
    expanded_references: expandedReferences,
    history_included: includeHistory,
    coordinator_profile: coordinatorProfile,
  };
  return payload;
}

function writeAudit(database, route, packId, requestedScopeId = null) {
  database.prepare(`INSERT INTO scope_routing_audit
    (id,task_fingerprint,requested_scope_id,resolved_scope_id,task_type,outcome,signals_json,context_pack_id,created_at)
    VALUES (?,?,?,?,?,?,?,?,?)`).run(randomUUID(), route.fingerprint, requestedScopeId, route.scopeId,
      route.taskType, route.outcome, canonical(route.signals), packId, now());
}

export function compileContextPack(databasePath = defaultDatabasePath, request = {}) {
  const database = open(resolve(databasePath));
  try {
    const route = routeTask(database, request);
    if (route.outcome !== 'routed') {
      writeAudit(database, route, null, request.explicitScopeId ?? null);
      return { route, pack: null };
    }
    const taskBrief = automaticArticleRevisionTaskBrief(route,
      automaticArticleTaskBrief(route, request.taskBrief ?? {}));
    let payload;
    try {
      payload = compileDeterministicContext(database, {
        scopeId: route.scopeId, taskType: route.taskType, includeHistory: Boolean(request.includeHistory),
        includeReferencedContent: Boolean(request.includeReferencedContent),
        projectDatabasePath: request.projectDatabasePath ?? defaultProjectDatabasePath,
        taskBrief, route, coordinatorProfile: request.coordinatorProfile ?? null,
      });
    } catch (error) {
      writeAudit(database, { ...route, outcome: 'rejected', signals: [...route.signals, 'execution_preflight_rejected'] }, null,
        request.explicitScopeId ?? null);
      throw error;
    }
    const serialized = canonical(payload);
    const pack = { id: randomUUID(), input_hash: hash(canonical({ scopeId: route.scopeId, taskType: route.taskType, includeHistory: Boolean(request.includeHistory), includeReferencedContent: Boolean(request.includeReferencedContent), taskBrief, coordinatorProfileId: request.coordinatorProfile?.id ?? null })), compiled_bytes: Buffer.byteLength(serialized) };
    database.prepare(`INSERT INTO context_packs
      (id,scope_id,task_type,compiler_version,input_hash,payload_json,compiled_bytes,status,created_at)
      VALUES (?,?,?,?,?,?,?,'open',?)`).run(pack.id, route.scopeId, route.taskType, COMPILER_VERSION,
        pack.input_hash, serialized, pack.compiled_bytes, now());
    writeAudit(database, route, pack.id, request.explicitScopeId ?? null);
    return { route, pack: { ...pack, status: 'open', payload } };
  } finally { database.close(); }
}

export function compileCoordinatorContext(databasePath = defaultDatabasePath, request = {}) {
  const profile = COORDINATOR_PROFILES[request.profileId];
  if (!profile || profile.status !== 'active') throw new Error('unknown or inactive coordinator profile');
  if (!nonEmptyText(request.taskId)) throw new Error('coordinator taskId is required');
  if (!profile.task_types.includes(request.taskType)) throw new Error('task type is not allowed by coordinator profile');
  const database = open(resolve(databasePath), true);
  let parentRoute;
  try {
    parentRoute = routeTask(database, { text: request.text ?? '', taskType: request.taskType });
  } finally { database.close(); }
  if (parentRoute.outcome !== 'routed' || parentRoute.scopeId !== profile.scope_id) {
    throw new Error('task is outside the coordinator profile scope');
  }
  const taskScope = createTaskScope(databasePath, {
    taskId: request.taskId, parentScopeId: profile.scope_id,
    name: request.taskName ?? `Task ${request.taskId}`,
    summary: request.taskSummary ?? 'Temporary coordinator task scope.',
  });
  const coordinatorProfile = {
    id: profile.id, status: profile.status, scope_id: profile.scope_id, task_types: [...profile.task_types],
    role: profile.role, maximum_delegation_depth: profile.maximum_delegation_depth,
    maximum_research_branches: profile.maximum_research_branches,
    allowed_skills: Object.fromEntries(Object.entries(profile.allowed_skills).map(([key, value]) => [key, [...value]])),
  };
  const compiled = compileContextPack(databasePath, {
    ...request, explicitScopeId: taskScope.id, taskType: request.taskType,
    coordinatorProfile, taskBrief: request.taskBrief ?? {},
  });
  const chain = compiled.pack?.payload?.passports?.map((item) => item.id) ?? [];
  const expected = [SCOPE_IDS.core, SCOPE_IDS.metrichit, SCOPE_IDS.editorial, taskScope.id];
  if (canonical(chain) !== canonical(expected)) throw new Error('coordinator context contains an invalid scope chain');
  return { ...compiled, coordinator: coordinatorProfile, taskScope };
}

export function closeContextPack(databasePath = defaultDatabasePath, packId, delivery = {}) {
  const database = open(resolve(databasePath));
  try {
    const stored = database.prepare('SELECT * FROM context_packs WHERE id=?').get(packId);
    if (!stored) throw new Error('context pack was not found');
    if (stored.status !== 'open') {
      const terminalPayload = parseJson(stored.payload_json, {});
      return { id: stored.id, status: stored.status, closed_at: stored.closed_at, changed: false,
        terminal_outcome: terminalPayload.terminal_outcome ?? 'delivered' };
    }
    const payload = parseJson(stored.payload_json, null);
    if (!payload?.execution_card) throw new Error('delivery validation failed: execution_card_missing');
    if (hash(canonical(payload.execution_card)) !== payload.execution_card_hash) {
      throw new Error('delivery validation failed: execution_card_hash_mismatch');
    }
    const validation = validateDeliveryEvidence(payload.execution_card, delivery);
    validation.publication_reconciliation = validatePublicationReconciliation(
      payload.execution_card.publication_reconciliation,
      payload.project_database_path,
    );
    const deliveredPayload = { ...payload, terminal_outcome: 'delivered', delivery_validation: validation };
    const serialized = canonical(deliveredPayload);
    const closedAt = validation.validated_at;
    const changed = database.prepare(`UPDATE context_packs
      SET payload_json=?,compiled_bytes=?,status='closed',closed_at=? WHERE id=? AND status='open'`)
      .run(serialized, Buffer.byteLength(serialized), closedAt, packId).changes;
    const row = database.prepare('SELECT id,status,closed_at,payload_json FROM context_packs WHERE id=?').get(packId);
    if (!row) throw new Error('context pack was not found');
    return { id: row.id, status: row.status, closed_at: row.closed_at, changed: changed === 1,
      terminal_outcome: 'delivered', validation: parseJson(row.payload_json, {}).delivery_validation };
  } finally { database.close(); }
}

function deterministicUuid(value) {
  const hex = hash(value).slice(0, 32).split('');
  hex[12] = '5';
  hex[16] = ['8', '9', 'a', 'b'][Number.parseInt(hex[16], 16) % 4];
  return `${hex.slice(0, 8).join('')}-${hex.slice(8, 12).join('')}-${hex.slice(12, 16).join('')}-${hex.slice(16, 20).join('')}-${hex.slice(20).join('')}`;
}

export function abandonContextPack(databasePath = defaultDatabasePath, packId, abandonment = {}) {
  if (!nonEmptyText(abandonment.reason)) throw new Error('context pack abandonment reason is required');
  if (!nonEmptyText(abandonment.owner)) throw new Error('context pack abandonment owner is required');
  const database = open(resolve(databasePath));
  database.exec('BEGIN IMMEDIATE');
  try {
    const stored = database.prepare('SELECT * FROM context_packs WHERE id=?').get(packId);
    if (!stored) throw new Error('context pack was not found');
    const payload = parseJson(stored.payload_json, null);
    if (!payload) throw new Error('context pack payload is invalid');
    if (stored.status !== 'open') {
      const outcome = payload.terminal_outcome ?? 'delivered';
      if (outcome !== 'abandoned') throw new Error('delivered context pack cannot be abandoned');
      database.exec('COMMIT');
      return { id: stored.id, status: stored.status, closed_at: stored.closed_at,
        terminal_outcome: outcome, changed: false };
    }
    const closedAt = now();
    const abandonmentEvidence = {
      reason: abandonment.reason.trim(), owner: abandonment.owner.trim(), abandoned_at: closedAt,
    };
    const terminalPayload = { ...payload, terminal_outcome: 'abandoned', abandonment: abandonmentEvidence };
    const serialized = canonical(terminalPayload);
    const changed = database.prepare(`UPDATE context_packs
      SET payload_json=?,compiled_bytes=?,status='closed',closed_at=? WHERE id=? AND status='open'`)
      .run(serialized, Buffer.byteLength(serialized), closedAt, packId).changes;
    if (changed !== 1) throw new Error('context pack abandonment did not change exactly one open pack');
    const projectId = String(stored.scope_id).startsWith('scope:core')
      ? YADRO_CONTROL_PLANE_PROJECT_ID : METRICHIT_PROJECT_ID;
    const auditId = deterministicUuid(`context-pack-abandoned:${packId}`);
    database.prepare(`INSERT INTO audit_log
      (id,type,title,content,data_json,author,entity_type,entity_id,action,valid_at)
      VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING`).run(
      auditId, 'context_pack_terminal_event', 'Context pack abandoned', abandonmentEvidence.reason,
      canonical({ context_pack_id: packId, terminal_outcome: 'abandoned', project_id: projectId,
        owner: abandonmentEvidence.owner, reason: abandonmentEvidence.reason }),
      abandonmentEvidence.owner, 'context_pack', packId, 'update', closedAt,
    );
    database.exec('COMMIT');
    return { id: stored.id, status: 'closed', closed_at: closedAt,
      terminal_outcome: 'abandoned', changed: true, audit_id: auditId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally { database.close(); }
}

export function registerScopedRecord(databasePath = defaultDatabasePath, record) {
  const database = open(resolve(databasePath));
  try {
    const scope = typeof record.scopeId === 'string'
      ? database.prepare("SELECT id FROM scope_passports WHERE id=? AND status='active'").get(record.scopeId) : null;
    if (!scope) {
      const id = randomUUID();
      database.prepare(`INSERT INTO unresolved_memory_queue
        (id,semantic_key,title,content,reason,candidate_scope_id,status,created_at) VALUES (?,?,?,?,?,?,'pending',?)`)
        .run(id, record.semanticKey ?? null, record.title ?? 'Без названия', record.content ?? '', 'scope_missing_or_invalid', record.scopeId ?? null, now());
      return { status: 'queued', id };
    }
    const id = record.id ?? randomUUID();
    const timestamp = now();
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, record.semanticKey, record.scopeId,
        record.layer, record.recordType, record.lifecycleStatus ?? 'active', record.title, record.content,
        record.sourceRef, record.validFrom ?? timestamp, record.supersedesId ?? null, record.ruleEffect ?? null,
        canonical(record.taskTypes ?? ['all']), canonical(record.metadata ?? {}), timestamp, timestamp);
    return { status: 'stored', id };
  } finally { database.close(); }
}

export function supersedeScopedRecord(databasePath = defaultDatabasePath, priorId, record) {
  const database = open(resolve(databasePath));
  database.exec('BEGIN IMMEDIATE');
  try {
    const prior = database.prepare("SELECT * FROM scoped_memory_records WHERE id=? AND lifecycle_status='active'").get(priorId);
    if (!prior) throw new Error('active prior record was not found');
    if (record.scopeId !== prior.scope_id || record.semanticKey !== prior.semantic_key) {
      throw new Error('superseding record must keep the same scope and semantic key');
    }
    const timestamp = now();
    database.prepare("UPDATE scoped_memory_records SET lifecycle_status='superseded',updated_at=? WHERE id=? AND lifecycle_status='active'").run(timestamp, priorId);
    const id = record.id ?? randomUUID();
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?)`).run(id, record.semanticKey, record.scopeId,
        record.layer, record.recordType, record.title, record.content, record.sourceRef,
        record.validFrom ?? timestamp, priorId, record.ruleEffect ?? null,
        canonical(record.taskTypes ?? ['all']), canonical(record.metadata ?? {}), timestamp, timestamp);
    database.exec('COMMIT');
    return { status: 'stored', id, supersedesId: priorId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally { database.close(); }
}

export function baselineMetrics(paths = [agentsPath, join(repositoryRoot, 'knowledge', 'approved', 'current-context.md'), join(repositoryRoot, 'documents', 'operating-context.md'), join(repositoryRoot, 'documents', 'roadmap.md')]) {
  const started = performance.now();
  for (const path of paths) readFileSync(path, 'utf8');
  return { files: paths.map((path) => ({ path: resolve(path), bytes: statSync(path).size })), total_bytes: paths.reduce((total, path) => total + statSync(path).size, 0), elapsed_ms: performance.now() - started };
}

function argumentsOf(values) {
  const result = { command: values[0] };
  for (let index = 1; index < values.length; index += 1) {
    const key = values[index];
    if (!key.startsWith('--')) continue;
    result[key.slice(2)] = values[index + 1]; index += 1;
  }
  return result;
}
function jsonArgument(value, fallback = []) {
  if (value === undefined) return fallback;
  const parsed = parseJson(value, null);
  if (!Array.isArray(parsed)) throw new Error('list arguments must be JSON arrays');
  return parsed;
}
function jsonObjectArgument(value, fallback = null) {
  if (value === undefined) return fallback;
  const parsed = parseJson(value, null);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('object arguments must be JSON objects');
  return parsed;
}

function isMainModule() { return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href; }
if (isMainModule()) {
  try {
    const args = argumentsOf(process.argv.slice(2));
    const databasePath = resolve(args.db ?? defaultDatabasePath);
    if (args.command === 'baseline') console.log(JSON.stringify(baselineMetrics(), null, 2));
    else if (args.command === 'compile') console.log(JSON.stringify(compileContextPack(databasePath, {
      text: args.text ?? '', explicitScopeId: args.scope ?? null, taskType: args['task-type'] ?? null,
      includeReferencedContent: args['include-references'] === 'true',
      projectDatabasePath: args['project-db'] ? resolve(args['project-db']) : defaultProjectDatabasePath,
      taskBrief: { result: args.result,
        scope: args['card-scope'] === undefined ? undefined : jsonArgument(args['card-scope']),
        firstCheck: args['first-check'],
        acceptance: args.acceptance === undefined ? undefined : jsonArgument(args.acceptance),
        forbiddenChanges: args['forbidden-changes'] === undefined ? undefined : jsonArgument(args['forbidden-changes']),
        editorialSemantics: jsonObjectArgument(args['editorial-semantics']),
        editorialIndexation: jsonObjectArgument(args['editorial-indexation']),
        publicationReconciliation: jsonObjectArgument(args['publication-reconciliation']) },
    }), null, 2));
    else if (args.command === 'close') console.log(JSON.stringify(closeContextPack(databasePath, args.id, {
      result: args.result, checks: jsonArgument(args.checks), satisfiedAcceptance: jsonArgument(args['satisfied-acceptance']),
      scopeCompliance: args['scope-compliant'] === 'true', forbiddenChangesObserved: jsonArgument(args['forbidden-observed']),
      contentQa: jsonObjectArgument(args['content-qa']),
      artifact: jsonObjectArgument(args.artifact),
    }), null, 2));
    else throw new Error('Usage: structured-memory.mjs <baseline|compile|close> [--db path]');
  } catch (error) { console.error(`structured-memory: ${error.message}`); process.exitCode = 1; }
}
