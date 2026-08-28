import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/project-storage-foundation-2026-08-21.md';
const semanticKey = 'architecture.project_storage_foundation';
const owner = 'owner';
const reviewedAt = '2026-08-21T18:00:00.000Z';
const materializationReviewedAt = '2026-08-26T13:30:00.000Z';
const runtimeCutoverReviewedAt = '2026-08-27T06:07:32.000Z';
const isolationReviewedAt = '2026-08-27T07:14:42.000Z';
const transferReviewedAt = '2026-08-28T08:00:00.000Z';
const controlPlaneProjectId = '00000000-0000-4000-a000-000000000101';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-project-storage:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) {
    if (row[field] !== value) throw new Error(`${label}.${field} differs`);
  }
}

export function applyProjectStorageFoundation(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');

  const title = 'Фундамент физического хранилища проектов «Ядра»';
  const content = 'Первый этап независимых проектных контуров завершён: каждому каноническому UUID проекта детерминированно соответствует отдельный SQLite-файл data/projects/<project_id>/project.sqlite. Защита пути запрещает выход из корня, перенаправление и пересечение хранилищ; служебная идентичность файла позволяет безопасную идемпотентную повторную инициализацию и явно отклоняет чужой, повреждённый или несовместимый файл. Этап не переносит существующие данные, не меняет legacy-базу или её схему, не переключает рабочий runtime, не меняет операторскую панель и не реализует экспорт/импорт.';
  const data = JSON.stringify({
    revision: 1,
    root: 'data/projects',
    layout: '<project_id>/project.sqlite',
    project_id: 'canonical_lowercase_uuid_v4',
    storage_format: 1,
    path_traversal_allowed: false,
    redirected_or_shared_paths_allowed: false,
    reinitialization: 'validate_only_and_idempotent',
    legacy_database_changed: false,
    runtime_connected: false,
    migrated_existing_data: false,
    operator_panel_changed: false,
    export_import_implemented: false,
    evidence: {
      decision: decisionPath,
      contract: 'documents/project-storage.md',
      implementation: 'src/metrichit_os/project_storage.py',
    },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-21',
  });
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const candidateId = uuid(`candidate:${semanticKey}:1`);
  const materializationCandidateId = uuid(`candidate:${semanticKey}:2`);
  const runtimeCutoverSourceId = uuid('source:git:0150db784e6795f9d08e36e0f70f786594247cee');
  const runtimeCutoverCandidateId = uuid(`candidate:${semanticKey}:3`);
  const runtimeCutoverSourceScopeAuditId = uuid(`audit:${semanticKey}:3:source_scope`);
  const runtimeCutoverCandidateScopeAuditId = uuid(`audit:${semanticKey}:3:project_id`);
  const isolationSourceId = uuid('source:git:51e9279b9e55b80dd182b3599e973460a774d943');
  const isolationCandidateId = uuid(`candidate:${semanticKey}:4`);
  const isolationSourceScopeAuditId = uuid(`audit:${semanticKey}:4:source_scope`);
  const isolationCandidateScopeAuditId = uuid(`audit:${semanticKey}:4:project_id`);
  const transferSourceId = uuid('source:git:bd203a1999b06921fc640fd9ff6c247155e2e38f');
  const transferCandidateId = uuid(`candidate:${semanticKey}:5`);
  const transferSourceScopeAuditId = uuid(`audit:${semanticKey}:5:source_scope`);
  const transferCandidateScopeAuditId = uuid(`audit:${semanticKey}:5:project_id`);
  const materializationScopeAuditId = uuid(`audit:${semanticKey}:2:project_id`);
  const materializationTitle = 'Данные MetricHit материализованы в отдельном project SQLite';
  const materializationContent = 'Все 326 записей канонического managed project MetricHit материализованы в data/projects/00000000-0000-4000-a000-000000000102/project.sqlite вместе с 4 минимальными core provenance dependencies и 10 строками schema_migrations. Четыре ранее утверждённые metadata corrections применены только к эффективным target-связям; legacy SQLite не переписана и остаётся рабочим источником. Exact-source backup и restore-test прошли, target foreign keys и integrity проверены, идемпотентный replay не изменил файл. Runtime, reads/writes, UI, export/import и cutover не переключались.';
  const materializationData = JSON.stringify({
    revision: 2,
    supersedes_semantic_revision: 1,
    supersedes_candidate_id: candidateId,
    stage_status: 'completed',
    project_id: '00000000-0000-4000-a000-000000000102',
    target: 'data/projects/00000000-0000-4000-a000-000000000102/project.sqlite',
    records: { primary: 326, dependency: 4, schema_migrations: 10, total: 340 },
    metadata_corrections: 4,
    source_sha256_at_migration: 'a5f507b6a283e5b5431a95f919470c9a094908023708fa86a2704462d3f1e5de',
    plan_manifest_sha256: '66891c6d4d8b223eca051d732c1833000a839f755c8fa76a1e8542af463a2c0f',
    target_sha256: '69e0ec3841ee43568aa90685c74b30c2f05f0292110f191f36e547cbd20da08d',
    embedded_manifest_sha256: 'd3a602b3dc0b5370bb454d5943bb75cd28fbc294f66bacb04dc6c74ec46868eb',
    backup_id: 'MetricHit-backup-20260826T132336Z',
    verification: ['restore_test', 'foreign_key_check', 'integrity_check', 'exact_coverage', 'idempotent_replay'],
    legacy_database_changed_by_migration: false,
    runtime_connected: false,
    cutover: false,
    export_import_implemented: false,
    next_gate: 'separate_owner_approval_for_export_import_or_cutover',
    evidence: { contract: 'documents/project-storage.md', implementation: 'src/metrichit_os/project_migration.py' },
  });
  const materializationScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-materialization-memory-scope-2026-08-26-v1',
    table: 'memory_candidates',
    entityId: materializationCandidateId,
    project_id: controlPlaneProjectId,
    corrections: [{
      field: 'project_id',
      invalidValue: '00000000-0000-4000-a000-000000000102',
      newValue: null,
      reason: 'project_id describes the migration target; the architecture decision belongs to the control plane',
    }],
  });
  const runtimeCutoverTitle = 'Runtime MetricHit переключён на отдельный project SQLite';
  const runtimeCutoverContent = 'На commit 0150db784e6795f9d08e36e0f70f786594247cee после успешных backup и restore-test выполнена guarded replacement существующего MetricHit target: applied=1, replacedExisting=1, cutover=true. В project SQLite находятся 328 primary, 4 dependency и 10 schema_migrations, всего 342 записи. Центральная и проектная SQLite прошли integrity check и foreign key check с нулём нарушений. Project-first reads и MetricHit-scoped writes маршрутизируются в project SQLite, центральная база остаётся control plane. Legacy-копии сохранены; export/import, generic routing, визуальная изоляция и cleanup остаются отдельными этапами.';
  const runtimeCutoverData = JSON.stringify({
    revision: 3,
    supersedes_semantic_revision: 2,
    supersedes_candidate_id: materializationCandidateId,
    stage_status: 'completed',
    project_id: '00000000-0000-4000-a000-000000000102',
    target: 'data/projects/00000000-0000-4000-a000-000000000102/project.sqlite',
    commit: '0150db784e6795f9d08e36e0f70f786594247cee',
    backup_restore_verified: true,
    guarded_replacement: { applied: 1, replacedExisting: 1, cutover: true },
    records: { primary: 328, dependency: 4, schema_migrations: 10, total: 342 },
    source_sha256_at_cutover: '2b0e6b27826d580d355eb2dabd2ce6c7dcec20db65b951d6177aba3635c486bb',
    target_sha256: 'd9cb1d4635b0c917e9c61eca86cdc182e9db42471637711dae62a1f82a49fea6',
    central_integrity: 'ok',
    project_integrity: 'ok',
    foreign_key_violations: 0,
    project_first_reads: true,
    metrichit_scoped_writes: 'project_sqlite',
    central_database_role: 'control_plane',
    legacy_copies_retained: true,
    export_import_implemented: false,
    generic_routing_implemented: false,
    visual_isolation_implemented: false,
    cleanup_completed: false,
    evidence: { commit: '0150db784e6795f9d08e36e0f70f786594247cee', implementation: 'src/metrichit_os/runtime.py' },
  });
  const runtimeCutoverSourceData = JSON.stringify({
    commit: '0150db784e6795f9d08e36e0f70f786594247cee',
    title: 'feat: activate isolated MetricHit runtime',
    committed_at: '2026-08-27T06:07:32.000Z',
    authority: 'verified_runtime_cutover_closeout',
  });
  const isolationTitle = 'Независимый контур MetricHit готов к export/import';
  const isolationContent = 'Независимый контур MetricHit завершён: runtime cutover `0150db7` направляет project-first reads и MetricHit-scoped writes в отдельный project SQLite при центральной control plane. На `a2d03b455ad8ca981c97415eaec71fe628639c4d` operator panel изолирована: локальные MetricHit задачи, идеи, память и activity project-only; global overview/search остаются federated; записи маршрутизируются в проект. На `51e9279b9e55b80dd182b3599e973460a774d943` readiness восстановлен append-only: исходное содержимое не менялось, effective classification исправлена в control plane. План: core=493, managed=332, unresolved=0, ready=true; project target cutover/integrity/FK valid. Backup `MetricHit-backup-20260827T071442Z` и restore-test прошли. Панель доступна на 8778 (HTTP 200), live screenshot: `work/ui-review/migration-readiness-overview.png`. UI-поставка подтверждена backend 27/27 и E2E 16/16; отдельная E2E-сессия readiness не имеет финальной сводки после 9 успешных сценариев и не считается подтверждением. Следующий утверждённый приоритет — export/import независимого проекта; generic routing второго проекта затем, cleanup legacy-копий — только по отдельному решению владельца.';
  const isolationData = JSON.stringify({
    revision: 4,
    supersedes_semantic_revision: 3,
    supersedes_candidate_id: runtimeCutoverCandidateId,
    stage_status: 'completed',
    runtime_cutover_commit: '0150db784e6795f9d08e36e0f70f786594247cee',
    closeout_commit: '607b6d7',
    operator_panel_isolation_commit: 'a2d03b455ad8ca981c97415eaec71fe628639c4d',
    readiness_repair_commit: '51e9279b9e55b80dd182b3599e973460a774d943',
    migration_plan: { core: 493, managed: 332, unresolved: 0, ready: true },
    project_target: { cutover: true, integrity: 'ok', foreign_key_violations: 0 },
    backup_restore: { backup_id: 'MetricHit-backup-20260827T071442Z', restore_test: 'passed' },
    operator_panel: { port: 8778, http_status: 200, screenshot: 'work/ui-review/migration-readiness-overview.png' },
    verification: { backend: '27/27', operator_panel_e2e: '16/16', readiness_e2e_final_summary: 'not_available_after_9_successful_scenarios' },
    next_priority: 'export_import_independent_project',
    deferred: ['generic_routing_second_project', 'legacy_cleanup_requires_separate_owner_gate'],
  });
  const isolationSourceData = JSON.stringify({
    commit: '51e9279b9e55b80dd182b3599e973460a774d943',
    title: 'fix: restore migration readiness classification',
    committed_at: isolationReviewedAt,
    authority: 'verified_independent_metrichit_closeout',
  });
  const transferTitle = 'Export/import независимого проекта завершён';
  const transferContent = 'На commit bd203a1999b06921fc640fd9ff6c247155e2e38f завершён переносимый export/import независимого проекта. CLI project-export и project-import работают с ZIP-пакетом manifest, project.sqlite и project.json; проверяются версия формата и схемы, SHA-256, integrity, foreign keys, UUID и конфликты. Import атомарный и идемпотентный. Подтверждены Python 195 passed, 1 skipped; Node 62/62; focused export/import 15/15; live export/import и повторный import; readiness valid. Следующий утверждённый приоритет — generic routing второго проекта. Legacy cleanup требует отдельного решения владельца.';
  const transferData = JSON.stringify({
    revision: 5,
    supersedes_semantic_revision: 4,
    supersedes_candidate_id: isolationCandidateId,
    stage_status: 'completed',
    commit: 'bd203a1999b06921fc640fd9ff6c247155e2e38f',
    cli: ['project-export', 'project-import'],
    package: ['manifest', 'project.sqlite', 'project.json'],
    verification: {
      format_version: true, schema_version: true, sha256: true, integrity: 'ok',
      foreign_key_violations: 0, uuid: true, conflicts: true, atomic_import: true,
      idempotent_reimport: true, python: '195 passed, 1 skipped', node: '62/62', focused: '15/15',
      live_round_trip: true, readiness_valid: true,
    },
    next_priority: 'generic_routing_second_project',
    deferred: ['legacy_cleanup_requires_separate_owner_gate'],
  });
  const transferSourceData = JSON.stringify({
    commit: 'bd203a1999b06921fc640fd9ff6c247155e2e38f',
    title: 'feat: add independent project transfer',
    committed_at: '2026-08-28T00:00:00.000Z',
    authority: 'verified_independent_project_transfer_closeout',
  });
  const transferSourceScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-transfer-closeout-memory-scope-2026-08-28-v1', table: 'sources', entityId: transferSourceId,
    project_id: controlPlaneProjectId, basis: 'transfer closeout provenance belongs to the control plane',
  });
  const transferCandidateScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-transfer-closeout-memory-scope-2026-08-28-v1', table: 'memory_candidates', entityId: transferCandidateId,
    project_id: controlPlaneProjectId, corrections: [{ field: 'project_id', invalidValue: '00000000-0000-4000-a000-000000000102', newValue: null, reason: 'project_id describes the verified transfer target; the architecture decision belongs to the control plane' }],
  });
  const runtimeCutoverSourceScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-runtime-cutover-scope-2026-08-27-v1',
    table: 'sources',
    entityId: runtimeCutoverSourceId,
    project_id: controlPlaneProjectId,
    basis: 'runtime cutover provenance belongs to the control plane',
  });
  const runtimeCutoverCandidateScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-runtime-cutover-scope-2026-08-27-v1',
    table: 'memory_candidates',
    entityId: runtimeCutoverCandidateId,
    project_id: controlPlaneProjectId,
    corrections: [{
      field: 'project_id',
      invalidValue: '00000000-0000-4000-a000-000000000102',
      newValue: null,
      reason: 'project_id describes the runtime target; the architecture decision belongs to the control plane',
    }],
  });
  const isolationSourceScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-isolation-closeout-memory-scope-2026-08-27-v1', table: 'sources', entityId: isolationSourceId,
    project_id: controlPlaneProjectId, basis: 'closeout provenance belongs to the control plane',
  });
  const isolationCandidateScopeAuditData = JSON.stringify({
    batchKey: 'project-storage-isolation-closeout-memory-scope-2026-08-27-v1', table: 'memory_candidates', entityId: isolationCandidateId,
    project_id: controlPlaneProjectId, corrections: [{ field: 'project_id', invalidValue: '00000000-0000-4000-a000-000000000102', newValue: null, reason: 'project_id describes the managed target; the closeout decision belongs to the control plane' }],
  });
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, audits: 0 };

  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const lineage = database.prepare(
      "SELECT id,status FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id NOT IN (?,?,?,?)",
    ).all(semanticKey, materializationCandidateId, runtimeCutoverCandidateId, isolationCandidateId, transferCandidateId);
    if (lineage.some((row) => row.id !== candidateId || row.status !== 'approved')) {
      throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    }
    const conflict = database.prepare(
      "SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))",
    ).get(transferCandidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(database.prepare(
      "INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-21', 'internal')",
    ).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.sources += Number(database.prepare(
      "INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'git_commit', ?, ?, ?, 'active', ?, '2026-08-27', 'internal')",
    ).run(runtimeCutoverSourceId, runtimeCutoverTitle, 'Verified repository runtime cutover commit', runtimeCutoverSourceData, owner).changes);
    created.sources += Number(database.prepare(
      "INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'git_commit', ?, ?, ?, 'active', ?, '2026-08-27', 'internal')",
    ).run(isolationSourceId, isolationTitle, 'Verified repository isolation and readiness closeout commit', isolationSourceData, owner).changes);
    created.sources += Number(database.prepare(
      "INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'git_commit', ?, ?, ?, 'active', ?, '2026-08-28', 'internal')",
    ).run(transferSourceId, transferTitle, 'Verified independent project transfer commit', transferSourceData, owner).changes);
    created.documents += Number(database.prepare(
      "INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-21', 'internal', 1)",
    ).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(
      "INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-21', 'internal', 1)",
    ).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-21', 'internal', 1)",
    ).run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-26', 'internal', 1)",
    ).run(materializationCandidateId, semanticKey, materializationTitle, materializationContent, materializationData, sourceId, owner).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-27', 'internal', 1)",
    ).run(runtimeCutoverCandidateId, semanticKey, runtimeCutoverTitle, runtimeCutoverContent, runtimeCutoverData, runtimeCutoverSourceId, owner).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-27', 'internal', 1)",
    ).run(isolationCandidateId, semanticKey, isolationTitle, isolationContent, isolationData, isolationSourceId, owner).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-28', 'internal', 1)",
    ).run(transferCandidateId, semanticKey, transferTitle, transferContent, transferData, transferSourceId, owner).changes);
    const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?",
      ).run(owner, reviewedAt, 'Одобрено прямым решением владельца от 21.08.2026.', reviewedAt, candidateId);
    }
    const materializationCandidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(materializationCandidateId);
    if (materializationCandidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?",
      ).run(owner, materializationReviewedAt, 'Одобрено прямым решением владельца для фактической миграции MetricHit от 26.08.2026.', materializationReviewedAt, materializationCandidateId);
    }
    const runtimeCutoverCandidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(runtimeCutoverCandidateId);
    if (runtimeCutoverCandidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?",
      ).run(owner, runtimeCutoverReviewedAt, 'Зафиксировано по проверенной поставке runtime cutover 0150db7.', runtimeCutoverReviewedAt, runtimeCutoverCandidateId);
    }
    const isolationCandidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(isolationCandidateId);
    if (isolationCandidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?",
      ).run(owner, isolationReviewedAt, 'Зафиксировано по проверенному закрытию независимого контура MetricHit.', isolationReviewedAt, isolationCandidateId);
    }
    const transferCandidate = database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(transferCandidateId);
    if (transferCandidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?",
      ).run(owner, transferReviewedAt, 'Зафиксировано по проверенной поставке export/import bd203a1.', transferReviewedAt, transferCandidateId);
    }
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_metadata_correction', 'Project materialization decision scope corrected', ?, ?, ?, ?, ?, 'restricted', 1, 'decision', ?, 'update')",
    ).run(
      materializationScopeAuditId, materializationScopeAuditData, sourceId, owner,
      materializationReviewedAt, materializationReviewedAt, materializationCandidateId,
    ).changes);
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_assignment', 'Runtime cutover provenance scope assigned', ?, ?, ?, ?, ?, 'restricted', 1, 'git_commit', ?, 'update')",
    ).run(
      runtimeCutoverSourceScopeAuditId, runtimeCutoverSourceScopeAuditData, runtimeCutoverSourceId, owner,
      runtimeCutoverReviewedAt, runtimeCutoverReviewedAt, runtimeCutoverSourceId,
    ).changes);
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_metadata_correction', 'Runtime cutover decision scope corrected', ?, ?, ?, ?, ?, 'restricted', 1, 'decision', ?, 'update')",
    ).run(
      runtimeCutoverCandidateScopeAuditId, runtimeCutoverCandidateScopeAuditData, runtimeCutoverSourceId, owner,
      runtimeCutoverReviewedAt, runtimeCutoverReviewedAt, runtimeCutoverCandidateId,
    ).changes);
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_assignment', 'Isolation closeout provenance scope assigned', ?, ?, ?, ?, ?, 'restricted', 1, 'git_commit', ?, 'update')",
    ).run(isolationSourceScopeAuditId, isolationSourceScopeAuditData, isolationSourceId, owner, isolationReviewedAt, isolationReviewedAt, isolationSourceId).changes);
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_metadata_correction', 'Isolation closeout decision scope corrected', ?, ?, ?, ?, ?, 'restricted', 1, 'decision', ?, 'update')",
    ).run(isolationCandidateScopeAuditId, isolationCandidateScopeAuditData, isolationSourceId, owner, isolationReviewedAt, isolationReviewedAt, isolationCandidateId).changes);
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_assignment', 'Transfer closeout provenance scope assigned', ?, ?, ?, ?, ?, 'restricted', 1, 'git_commit', ?, 'update')",
    ).run(transferSourceScopeAuditId, transferSourceScopeAuditData, transferSourceId, owner, transferReviewedAt, transferReviewedAt, transferSourceId).changes);
    created.audits += Number(database.prepare(
      "INSERT OR IGNORE INTO audit_log(id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES(?, 'project_scope_metadata_correction', 'Transfer closeout decision scope corrected', ?, ?, ?, ?, ?, 'restricted', 1, 'decision', ?, 'update')",
    ).run(transferCandidateScopeAuditId, transferCandidateScopeAuditData, transferSourceId, owner, transferReviewedAt, transferReviewedAt, transferCandidateId).changes);

    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), {
      type: 'decision', semantic_key: semanticKey, title, content, data_json: data,
      status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'project storage decision');
    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(materializationCandidateId), {
      type: 'decision', semantic_key: semanticKey, title: materializationTitle,
      content: materializationContent, data_json: materializationData, status: 'approved',
      source_id: sourceId, reviewed_by: owner, reviewed_at: materializationReviewedAt,
    }, 'project materialization decision');
    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(runtimeCutoverCandidateId), {
      type: 'decision', semantic_key: semanticKey, title: runtimeCutoverTitle,
      content: runtimeCutoverContent, data_json: runtimeCutoverData, status: 'approved',
      source_id: runtimeCutoverSourceId, reviewed_by: owner, reviewed_at: runtimeCutoverReviewedAt,
    }, 'project runtime cutover decision');
    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(isolationCandidateId), {
      type: 'decision', semantic_key: semanticKey, title: isolationTitle, content: isolationContent, data_json: isolationData,
      status: 'approved', source_id: isolationSourceId, reviewed_by: owner, reviewed_at: isolationReviewedAt,
    }, 'project isolation closeout decision');
    assertRow(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(transferCandidateId), {
      type: 'decision', semantic_key: semanticKey, title: transferTitle, content: transferContent, data_json: transferData,
      status: 'approved', source_id: transferSourceId, reviewed_by: owner, reviewed_at: transferReviewedAt,
    }, 'project transfer closeout decision');
    assertRow(database.prepare('SELECT * FROM audit_log WHERE id=?').get(materializationScopeAuditId), {
      type: 'project_scope_metadata_correction', data_json: materializationScopeAuditData,
      source_id: sourceId, entity_type: 'decision', entity_id: materializationCandidateId,
      action: 'update',
    }, 'project materialization decision scope correction');
    assertRow(database.prepare('SELECT * FROM audit_log WHERE id=?').get(runtimeCutoverSourceScopeAuditId), {
      type: 'project_scope_assignment', data_json: runtimeCutoverSourceScopeAuditData,
      source_id: runtimeCutoverSourceId, entity_type: 'git_commit', entity_id: runtimeCutoverSourceId,
      action: 'update',
    }, 'runtime cutover provenance scope assignment');
    assertRow(database.prepare('SELECT * FROM audit_log WHERE id=?').get(runtimeCutoverCandidateScopeAuditId), {
      type: 'project_scope_metadata_correction', data_json: runtimeCutoverCandidateScopeAuditData,
      source_id: runtimeCutoverSourceId, entity_type: 'decision', entity_id: runtimeCutoverCandidateId,
      action: 'update',
    }, 'runtime cutover decision scope correction');
    assertRow(database.prepare('SELECT * FROM audit_log WHERE id=?').get(isolationSourceScopeAuditId), {
      type: 'project_scope_assignment', data_json: isolationSourceScopeAuditData, source_id: isolationSourceId,
      entity_type: 'git_commit', entity_id: isolationSourceId, action: 'update',
    }, 'isolation closeout provenance scope assignment');
    assertRow(database.prepare('SELECT * FROM audit_log WHERE id=?').get(isolationCandidateScopeAuditId), {
      type: 'project_scope_metadata_correction', data_json: isolationCandidateScopeAuditData, source_id: isolationSourceId,
      entity_type: 'decision', entity_id: isolationCandidateId, action: 'update',
    }, 'isolation closeout decision scope correction');
    assertRow(database.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), {
      data_json: metadata, status: 'active',
    }, 'source');
    assertRow(database.prepare('SELECT * FROM sources WHERE id=?').get(runtimeCutoverSourceId), {
      data_json: runtimeCutoverSourceData, status: 'active',
    }, 'runtime cutover source');
    assertRow(database.prepare('SELECT * FROM sources WHERE id=?').get(isolationSourceId), {
      data_json: isolationSourceData, status: 'active',
    }, 'isolation closeout source');
    assertRow(database.prepare('SELECT * FROM sources WHERE id=?').get(transferSourceId), {
      data_json: transferSourceData, status: 'active',
    }, 'project transfer closeout source');
    assertRow(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), {
      content: decision, data_json: metadata, source_id: sourceId, version: 1,
    }, 'document');
    assertRow(database.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), {
      document_id: documentId, content: decision, data_json: metadata, version: 1,
    }, 'document version');
    database.exec('COMMIT');
    return { databasePath, semanticKey, candidateId, materializationCandidateId, runtimeCutoverCandidateId, isolationCandidateId, transferCandidateId, materializationScopeAuditId, runtimeCutoverSourceScopeAuditId, runtimeCutoverCandidateScopeAuditId, isolationSourceScopeAuditId, isolationCandidateScopeAuditId, transferSourceScopeAuditId, transferCandidateScopeAuditId, created };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`Applied project storage foundation: ${JSON.stringify(applyProjectStorageFoundation(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
}
