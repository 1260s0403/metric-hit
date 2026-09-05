import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/model-routing-policy-2026-08-13.md';
const owner = 'owner';
const reviewedAt = '2026-09-05T00:00:00.000Z';
const revision = 8;

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-model-routing:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyModelRoutingPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Model routing decision contains U+FFFD');
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation_after_five_clarifications_and_platform_risk',
    decision_date: '2026-09-05',
  });
  const sourceId = stableUuid(`source:${decisionPath}:${revision}`);
  const documentId = stableUuid(`document:${decisionPath}:${revision}`);
  const versionId = stableUuid(`document-version:${decisionPath}:${revision}`);
  const candidateId = stableUuid(`candidate:ai.model_routing_policy:${revision}`);
  const title = 'Политика выбора модели Codex';
  const candidateContent = 'Terra Medium рекомендована для обычного Strategy и standard executor-задач, но не меняет автоматически owner-selected модель чата или глобальные настройки. Luna используется для полностью определённой механической low-risk задачи в явном scope с простой целевой проверкой; при её недоступности допустим fallback на Terra Medium без blocker. Terra используется для обычной локальной реализации с самостоятельным выбором решения внутри scope. Sol используется для фактической complex architecture, security/auth, schema/data integrity, shared runtime или существенной неоднозначности как единственный writer либо обоснованный независимый reviewer; когда Sol требуется для такого этапа и недоступна, это технический blocker без молчаливого downgrade. Критерии Luna/Sol действуют постоянно и не требуют отдельного вопроса на каждую задачу; один набор изменений сохраняет одного writer, автоматической цепочки моделей и обязательного review Luna нет. Astra применяется только по отдельному прямому решению владельца. Проверки зависят от изменения, а не модели; внешние owner-gates, editorial profile approvals и production pause сохранены. Прямым решением владельца 05.09.2026 введены пять точных уточнений первого этапа: консультация и точечный read-only review не требуют writer, card или полного startup; обе bare-команды запускают полный read-only Strategy startup только по прямой команде; чистота перед mutation проверяется в active registered worktree, canonical — при preparation и integration; идемпотентная запись approved решения не требует повторного согласования содержания; delivery отделена от chat-finish. Остальной восьмишаговый план остаётся планом до отдельной реализации.';
  const candidateData = JSON.stringify({
    default_model: 'GPT-5.6 Terra / Medium',
    default_reasoning: 'Medium',
    routing_scope: 'internal_executor_where_platform_supports_model_selection',
    owner_visible_strategy_model_changes_automatically: false,
    strategy_recommendation: 'GPT-5.6 Terra / Medium',
    luna: {
      standing_approval: true,
      requires: ['fully_defined_mechanical_task', 'explicit_scope', 'low_risk', 'simple_targeted_verification'],
      excludes: ['architecture_choice', 'ambiguous_requirements'],
      on_ambiguity: 'route_with_collected_facts_to_terra_or_sol',
    },
    terra: { use_for: ['standard_local_implementation', 'ordinary_technical_judgment_within_scope'] },
    sol: {
      standing_approval: true,
      use_for: ['complex_architecture', 'security_or_auth', 'schema_or_data_integrity', 'shared_runtime', 'material_ambiguity'],
      roles: ['sole_writer', 'justified_independent_reviewer'],
    },
    astra: { owner_decision_required: true, automatic_selection: false },
    automatic_model_chain: false,
    mandatory_luna_review: false,
    reclassify_before_each_new_task: true,
    actual_model_verification: 'when_platform_supports_selection_before_critical_actions',
    luna_unavailable: 'fallback_to_GPT-5.6_Terra_Medium_without_blocker',
    required_sol_unavailable: 'technical_blocker_no_silent_downgrade',
    handoff_between_models: 'preserve_facts_diff_and_completed_checks',
    checks_depend_on: 'actual_change_not_model',
    owner_gates_preserved: ['external_publication', 'spending', 'access_changes', 'deletion'],
    editorial_profile_approvals_preserved: true,
    production_pause_preserved: true,
    future_agents_md_plan: {
      status: 'approved_plan_first_stage_implemented',
      source_path: decisionPath,
      steps: 8,
      changes_lifecycle_automatically: false,
      first_stage_approved_clarifications: ['consultation_and_read_only_review_no_writer_card_or_full_startup', 'bare_start_commands_owner_triggered_full_read_only_strategy_startup', 'active_isolated_worktree_clean_check_and_canonical_preparation_integration_check', 'approved_decision_recording_no_repeat_content_approval', 'delivery_separate_from_chat_finish'],
    },
    standard_model: 'GPT-5.6 Terra / Medium',
    revision,
    supersedes: 'ai.model_routing_policy revision 7',
    evidence: { path: decisionPath },
  });

  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  try {
    const approvedLineage = new Set([
      stableUuid('candidate:ai.model_routing_policy:2'),
      stableUuid('candidate:ai.model_routing_policy:3'),
      stableUuid('candidate:ai.model_routing_policy'),
      stableUuid('candidate:ai.model_routing_policy:4'),
      stableUuid('candidate:ai.model_routing_policy:5'),
      stableUuid('candidate:ai.model_routing_policy:6'),
      stableUuid('candidate:ai.model_routing_policy:7'),
    ]);
    const competing = database.prepare("SELECT id,status FROM memory_candidates WHERE semantic_key='ai.model_routing_policy' AND status IN ('pending','approved') AND id<>?").all(candidateId)
      .filter((row) => !(row.status === 'approved' && approvedLineage.has(row.id)));
    if (competing.length) throw new Error('Semantic duplicate or evolution requires an explicit superseding revision for ai.model_routing_policy');
    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-05', 'internal')
    `).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-05', 'internal', 1)
    `).run(documentId, title, content, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-05', 'internal', 2)
    `).run(versionId, documentId, title, content, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'ai_policy', 'ai.model_routing_policy', ?, ?, ?, 'pending', ?, ?, '2026-09-05', 'internal', 1)
    `).run(candidateId, title, candidateContent, candidateData, sourceId, owner).changes);

    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
            review_note = ?, updated_at = ?, version = version + 1
        WHERE id = ?
      `).run(owner, reviewedAt, 'Прямое подтверждение владельца после перечисления пяти уточнений и platform risk: «Делай )», 05.09.2026.', reviewedAt, candidateId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), {
      type: 'ai_policy', semantic_key: 'ai.model_routing_policy', title,
      content: candidateContent, data_json: candidateData, source_id: sourceId,
      status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'model routing candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      content, data_json: metadata, source_id: sourceId, version: 1,
    }, 'model routing document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const result = applyModelRoutingPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
  console.log(`Applied model routing policy to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
}
