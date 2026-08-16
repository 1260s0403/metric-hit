import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/model-routing-policy-2026-08-13.md';
const owner = 'owner';
const reviewedAt = '2026-08-16T10:00:00.000Z';
const revision = 4;

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
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-15',
  });
  const sourceId = stableUuid(`source:${decisionPath}:${revision}`);
  const documentId = stableUuid(`document:${decisionPath}:${revision}`);
  const versionId = stableUuid(`document-version:${decisionPath}:${revision}`);
  const candidateId = stableUuid(`candidate:ai.model_routing_policy:${revision}`);
  const title = 'Политика выбора модели Codex';
  const candidateContent = 'Требуемая модель определяется отдельно для каждой задачи; по умолчанию используется GPT-5.6 Terra, reasoning Medium. GPT-5.3-Codex-Spark — только для небольших изолированных UI-правок, CSS, текстов интерфейса, узких исправлений и коротких тестовых циклов; не для архитектуры, SQLite-схем, бизнес-логики, авторизации, security, backup/restore, миграций и больших сквозных модулей. Для сложной архитектуры, security и особо ответственных задач требуется GPT-5.6 Sol; для массовой однотипной обработки — GPT-5.6 Luna. Sol и Luna используются только после подтверждения владельца; разрешение действует только для конкретной задачи либо явно непрерывного этапа и не переносится автоматически на следующую задачу. Сразу после запуска автоматически созданный engineering task-thread обязан сверить фактическую модель с требуемой. Если для задачи требуется Sol или Luna, а фактическая модель иная, thread до любых критических действий останавливается и просит владельца переключить модель. После переключения thread продолжает с текущего состояния без отката, нового thread или перезапуска задачи. Если текущая модель избыточна для новой задачи, Codex до начала работы предлагает вернуться на Terra Medium. Модель самостоятельно не переключается.';
  const candidateData = JSON.stringify({
    default_model: 'GPT-5.6 Terra',
    default_reasoning: 'Medium',
    spark_for: ['isolated_ui_fixes', 'css', 'interface_copy', 'narrow_fixes', 'short_test_cycles'],
    spark_excluded_for: ['architecture', 'sqlite_schema', 'business_logic', 'authorization', 'security', 'backup_restore', 'migrations', 'large_end_to_end_modules'],
    sol_for: ['complex_architecture', 'security_critical', 'high_responsibility'],
    luna_for: ['bulk_classification', 'bulk_extraction', 'large_homogeneous_processing', 'background_operations'],
    owner_confirmation_required: true,
    reclassify_before_each_new_task: true,
    special_model_approval_scope: 'task_or_explicit_continuous_stage_only',
    special_model_approval_carries_to_next_task: false,
    engineering_task_thread_must_verify_actual_model_on_start: true,
    special_model_mismatch_blocks_critical_actions: true,
    special_model_mismatch_action: 'pause_and_request_owner_model_switch',
    after_special_model_switch: 'continue_current_state_without_rollback_new_thread_or_restart',
    recommend_terra_when_current_model_is_excessive: true,
    return_recommendation: 'GPT-5.6 Terra / Medium',
    revision,
    supersedes: 'ai.model_routing_policy revision 3',
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
    ]);
    const competing = database.prepare("SELECT id,status FROM memory_candidates WHERE semantic_key='ai.model_routing_policy' AND status IN ('pending','approved') AND id<>?").all(candidateId)
      .filter((row) => !(row.status === 'approved' && approvedLineage.has(row.id)));
    if (competing.length) throw new Error('Semantic duplicate or evolution requires an explicit superseding revision for ai.model_routing_policy');
    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-15', 'internal')
    `).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-15', 'internal', 1)
    `).run(documentId, title, content, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-15', 'internal', 2)
    `).run(versionId, documentId, title, content, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'ai_policy', 'ai.model_routing_policy', ?, ?, ?, 'pending', ?, ?, '2026-08-15', 'internal', 1)
    `).run(candidateId, title, candidateContent, candidateData, sourceId, owner).changes);

    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
            review_note = ?, updated_at = ?, version = version + 1
        WHERE id = ?
      `).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 15.08.2026; заменяет редакцию маршрутизации моделей от 13.08.2026.', reviewedAt, candidateId);
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
