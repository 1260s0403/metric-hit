import { createHash, randomUUID } from 'node:crypto';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const defaultProjectDatabasePath = join(repositoryRoot, 'data', 'projects', '00000000-0000-4000-a000-000000000102', 'project.sqlite');
const agentsPath = join(repositoryRoot, 'AGENTS.md');
export const COMPILER_VERSION = 5;
export const METRICHIT_PROJECT_ID = '00000000-0000-4000-a000-000000000102';
export const SEMANTIC_CORE_REFERENCE_KEY = 'content.metrichit_semantic_core.reference';
export const SCOPE_IDS = Object.freeze({
  core: 'scope:core', metrichit: 'scope:project:metrichit',
  editorial: 'scope:subproject:editorial', panel: 'scope:subproject:panel',
});

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
  indexationPfTarget: 'content.public_editorial_yandex_indexation_pf_target_policy',
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
    const task = database.prepare(`SELECT id,type,title,content,status,author FROM tasks
      WHERE title=? ORDER BY updated_at DESC,id LIMIT 1`).get(OWNER_H1_OBLIGATION_TITLE);
    if (!task || task.type !== 'knowledge_task' || task.status !== 'pending' || task.author !== 'owner'
      || !/накрутка\s+(?:пф|pf)|накрутка\s+поведенческого\s+фактора/iu.test(task.content)) {
      throw new Error(`applicable owner editorial obligation is unavailable: ${OWNER_H1_SEMANTIC_KEY}`);
    }
    requirements.push({
      id: task.id, semantic_key: OWNER_H1_SEMANTIC_KEY, scope_id: SCOPE_IDS.editorial,
      type: 'commitment', title: task.title, content: task.content,
      source: `approved-memory://tasks/${task.id}`, effect: 'require', authority: 'owner_obligation',
      metadata: { required_h1_queries: ['накрутка ПФ', 'накрутка поведенческого фактора'] },
    });
  }
  return requirements.sort((a, b) => a.semantic_key.localeCompare(b.semantic_key) || a.id.localeCompare(b.id));
}

function editorialSemanticsFromBrief(taskBrief, rules) {
  if (!rules.some((rule) => rule.semantic_key === REQUIRED_EDITORIAL_RULES.semanticCore)) return null;
  const source = taskBrief.editorialSemantics ?? {};
  const semanticContext = {
    selected_cluster: nonEmptyText(source.selectedCluster),
    primary_target_query: nonEmptyText(source.primaryTargetQuery),
    user_intent: nonEmptyText(source.userIntent),
    platform: nonEmptyText(source.platform),
    format: nonEmptyText(source.format),
  };
  const missing = Object.entries(semanticContext).filter(([, value]) => !value).map(([key]) => `editorial_semantics.${key}`);
  if (missing.length) throw new Error(`execution card is incomplete: ${missing.join(', ')}`);
  if (!['article', 'social_post'].includes(semanticContext.format)) {
    throw new Error('execution card is incomplete: editorial_semantics.format');
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

function editorialQaRequirements(rules, editorialSemantics, editorialIndexation) {
  const keys = new Set(rules.map((rule) => rule.semantic_key));
  if (!keys.has(REQUIRED_EDITORIAL_RULES.semanticCore)
    && !keys.has(REQUIRED_EDITORIAL_RULES.article) && !keys.has(REQUIRED_EDITORIAL_RULES.tenchat)) return null;
  const checks = [];
  if (keys.has(REQUIRED_EDITORIAL_RULES.semanticCore)) {
    checks.push({ id: 'semantic_cluster_selection', evidence_fields: ['selected_cluster', 'primary_target_query', 'user_intent', 'platform', 'core_reference', 'non_navigational'] });
    checks.push({ id: 'primary_query_prominence', evidence_fields: ['primary_target_query', 'platform', 'location', 'natural', 'keyword_stuffing'] });
    checks.push({ id: 'single_cluster_intent', evidence_fields: ['selected_cluster', 'user_intent', 'content_serves_selected_intent', 'unrelated_clusters_mixed'] });
    checks.push({ id: 'geo_demand_verification', evidence_fields: ['geo_candidate', 'demand_verification_required', 'demand_verified', 'verification_reference'] });
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

function buildExecutionCard(taskBrief, route, rules) {
  const scope = nonEmptyList(taskBrief.scope ?? taskBrief.allowedChanges);
  const acceptance = nonEmptyList(taskBrief.acceptance);
  const forbiddenChanges = nonEmptyList(taskBrief.forbiddenChanges);
  const editorialSemantics = editorialSemanticsFromBrief(taskBrief, rules);
  const editorialIndexation = editorialIndexationFromBrief(taskBrief, rules);
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
    delivery_qa: editorialQaRequirements(rules, editorialSemantics, editorialIndexation),
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
    || selection.selected_cluster !== semanticContext.selected_cluster
    || selection.primary_target_query !== semanticContext.primary_target_query
    || selection.user_intent !== semanticContext.user_intent
    || selection.platform !== semanticContext.platform
    || selection.core_reference !== SEMANTIC_CORE_REFERENCE_KEY
    || selection.non_navigational !== true)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:semantic_cluster_selection');
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
  const singleCluster = byId.get('single_cluster_intent');
  if (singleCluster && (!semanticContext
    || singleCluster.selected_cluster !== semanticContext.selected_cluster
    || singleCluster.user_intent !== semanticContext.user_intent
    || singleCluster.content_serves_selected_intent !== true
    || singleCluster.unrelated_clusters_mixed !== false)) {
    throw new Error('delivery validation failed: editorial_content_qa_failed:single_cluster_intent');
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
  if (h1 && (!nonEmptyText(h1.heading) || !['накрутка ПФ', 'накрутка поведенческого фактора'].includes(h1.matched_query)
    || !h1.heading.toLocaleLowerCase('ru-RU').includes(h1.matched_query.toLocaleLowerCase('ru-RU')))) {
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
  return {
    validated_at: now(), result: delivery.result.trim(), checks,
    satisfied_acceptance: satisfiedAcceptance, scope_compliant: true,
    forbidden_changes_observed: [], content_qa: contentQa,
  };
}

export function routeTask(database, { text = '', explicitScopeId = null, taskType = null } = {}) {
  const normalized = String(text).trim().toLocaleLowerCase('ru-RU');
  const fingerprint = hash(normalized);
  const inferredType = inferTaskType(normalized, taskType);
  const signals = [];
  if (['editorial', 'research'].includes(inferredType)
    || /(стать|редак|контент|social|smm|публикац|пост|research|исследован|семантическ|ключев.{0,20}запрос|tenchat|тенчат)/iu.test(normalized)) signals.push('editorial');
  if (/(стать|article|лонгрид)/iu.test(normalized)) signals.push('article');
  if (/(tenchat|тенчат)/iu.test(normalized)) signals.push('tenchat');
  if (/(telegram|телеграм|(?:^|[^\p{L}\p{N}])тг(?:$|[^\p{L}\p{N}]))/iu.test(normalized)) signals.push('telegram');
  if (/(?:^|[^\p{L}\p{N}])(?:vk|вк)(?:$|[^\p{L}\p{N}])|вконтакте/iu.test(normalized)) signals.push('vk');
  if (/(?:^|[^\p{L}\p{N}])(?:пф|pf)(?:$|[^\p{L}\p{N}])|поведенческ|накрутк/iu.test(normalized)) signals.push('pf');
  if (/(бонус|1\s*000\s+клик)/iu.test(normalized)) signals.push('bonus');
  if (explicitScopeId) {
    scopeChain(database, explicitScopeId);
    return { outcome: 'routed', scopeId: explicitScopeId, taskType: inferredType, signals: ['explicit_scope', ...signals], fingerprint };
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
  return { outcome: 'routed', scopeId, taskType: inferredType, signals, fingerprint };
}

export function compileDeterministicContext(database, {
  scopeId, taskType, includeHistory = false, includeReferencedContent = false,
  projectDatabasePath = defaultProjectDatabasePath, agentsContent = null, taskBrief = {}, route = null,
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
  const approvedEditorialRequirements = resolveApprovedEditorialRequirements(database, resolvedRoute);
  const rules = [...new Map([...records.filter((item) => item.type === 'rule'), ...approvedEditorialRequirements]
    .map((item) => [item.semantic_key, item])).values()];
  const executionCard = buildExecutionCard(taskBrief, resolvedRoute, rules);
  const payload = {
    schema_version: 4,
    compiler_version: COMPILER_VERSION,
    task_type: taskType,
    target_scope: scopeId,
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
    let payload;
    try {
      payload = compileDeterministicContext(database, {
        scopeId: route.scopeId, taskType: route.taskType, includeHistory: Boolean(request.includeHistory),
        includeReferencedContent: Boolean(request.includeReferencedContent),
        projectDatabasePath: request.projectDatabasePath ?? defaultProjectDatabasePath,
        taskBrief: request.taskBrief ?? {}, route,
      });
    } catch (error) {
      writeAudit(database, { ...route, outcome: 'rejected', signals: [...route.signals, 'execution_preflight_rejected'] }, null,
        request.explicitScopeId ?? null);
      throw error;
    }
    const serialized = canonical(payload);
    const pack = { id: randomUUID(), input_hash: hash(canonical({ scopeId: route.scopeId, taskType: route.taskType, includeHistory: Boolean(request.includeHistory), includeReferencedContent: Boolean(request.includeReferencedContent), taskBrief: request.taskBrief ?? {} })), compiled_bytes: Buffer.byteLength(serialized) };
    database.prepare(`INSERT INTO context_packs
      (id,scope_id,task_type,compiler_version,input_hash,payload_json,compiled_bytes,status,created_at)
      VALUES (?,?,?,?,?,?,?,'open',?)`).run(pack.id, route.scopeId, route.taskType, COMPILER_VERSION,
        pack.input_hash, serialized, pack.compiled_bytes, now());
    writeAudit(database, route, pack.id, request.explicitScopeId ?? null);
    return { route, pack: { ...pack, status: 'open', payload } };
  } finally { database.close(); }
}

export function closeContextPack(databasePath = defaultDatabasePath, packId, delivery = {}) {
  const database = open(resolve(databasePath));
  try {
    const stored = database.prepare('SELECT * FROM context_packs WHERE id=?').get(packId);
    if (!stored) throw new Error('context pack was not found');
    if (stored.status !== 'open') return { id: stored.id, status: stored.status, closed_at: stored.closed_at, changed: false };
    const payload = parseJson(stored.payload_json, null);
    if (!payload?.execution_card) throw new Error('delivery validation failed: execution_card_missing');
    if (hash(canonical(payload.execution_card)) !== payload.execution_card_hash) {
      throw new Error('delivery validation failed: execution_card_hash_mismatch');
    }
    const validation = validateDeliveryEvidence(payload.execution_card, delivery);
    const deliveredPayload = { ...payload, delivery_validation: validation };
    const serialized = canonical(deliveredPayload);
    const closedAt = validation.validated_at;
    const changed = database.prepare(`UPDATE context_packs
      SET payload_json=?,compiled_bytes=?,status='closed',closed_at=? WHERE id=? AND status='open'`)
      .run(serialized, Buffer.byteLength(serialized), closedAt, packId).changes;
    const row = database.prepare('SELECT id,status,closed_at,payload_json FROM context_packs WHERE id=?').get(packId);
    if (!row) throw new Error('context pack was not found');
    return { id: row.id, status: row.status, closed_at: row.closed_at, changed: changed === 1,
      validation: parseJson(row.payload_json, {}).delivery_validation };
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
      taskBrief: { result: args.result, scope: jsonArgument(args['card-scope']), firstCheck: args['first-check'],
        acceptance: jsonArgument(args.acceptance), forbiddenChanges: jsonArgument(args['forbidden-changes']) },
    }), null, 2));
    else if (args.command === 'close') console.log(JSON.stringify(closeContextPack(databasePath, args.id, {
      result: args.result, checks: jsonArgument(args.checks), satisfiedAcceptance: jsonArgument(args['satisfied-acceptance']),
      scopeCompliance: args['scope-compliant'] === 'true', forbiddenChangesObserved: jsonArgument(args['forbidden-observed']),
      contentQa: jsonObjectArgument(args['content-qa']),
    }), null, 2));
    else throw new Error('Usage: structured-memory.mjs <baseline|compile|close> [--db path]');
  } catch (error) { console.error(`structured-memory: ${error.message}`); process.exitCode = 1; }
}
