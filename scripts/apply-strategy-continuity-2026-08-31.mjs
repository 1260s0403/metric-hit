import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/strategy-continuity-2026-08-31.md';
const semanticKey = 'operations.marketing_skills_evaluation_and_installation';
const owner = 'owner';
const reviewedAt = '2026-08-31T00:00:00.000Z';
const priorTaskId = '915de79c-0125-4fc1-aebc-125e4c791dcd';

function uuid(key) {
  const hex = createHash('sha256').update(`metrichit-strategy-continuity:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function stableRecordId(key) { return `memory:continuity:${key}`; }
function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

function ensureScopedRecord(database, record) {
  const existing = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  if (!existing) {
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,'active',?,?,?,?,NULL,NULL,?,?,?,?)`).run(
      record.id, record.semanticKey, record.scopeId, 'permanent', 'decision', record.title, record.content,
      decisionPath, reviewedAt, JSON.stringify(record.taskTypes), JSON.stringify({ authority: 'direct_owner_confirmation' }), reviewedAt, reviewedAt,
    );
  }
  assertRow(database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id), {
    semantic_key: record.semanticKey, scope_id: record.scopeId, layer: 'permanent', record_type: 'decision',
    lifecycle_status: 'active', title: record.title, content: record.content, source_ref: decisionPath,
  }, `scoped record ${record.semanticKey}`);
}

export function applyStrategyContinuity(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const title = 'Глобальные навыки Codex и continuity Strategy';
  const content = 'Установлены и проверены глобальные навыки: маркетинг (marketing-brief, positioning, customer-research, content-strategy, seo-strategy, copywriting, cro-audit, analytics-tracking, email-sequence), дизайн (frontend-design, ui-ux, image) и разработка (security-best-practices, playwright, code-review, architecture-review, debugging-and-error-recovery, gh-fix-ci). Навыки выбираются по результату и scope, не заменяют execution card, owner-gates, проверки или одного writer. Контролируемый pilot разрешает только 2–3 независимые read-only research/audit-ветки с synthesis Strategy; для mutation/code/data/config остаются один writer и один commit. Владелец работает с телефона: platform approval запрашивается в текущем чате; личные имя/email не требуются, а для commit используется локальная identity MetricHit Automation <metrichit@local.invalid> без глобального Git-конфига. Подпроект «Лендинг» активен под MetricHit: ID 2a95e640-23b0-44a6-96e5-f9f732cd41fa, отдельная scoped memory, исходники work/landing/index.html и work/landing/404.html, публичный URL https://go.mtrhit.ru/ подтвердил HTTP 200 read-only. GitHub-доступ, deploy, login и конфигурация не выполнялись; публикация возможна только после будущего доступа и отдельной команды.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-31' });
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, scopedRecords: 0, completedTasks: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-31', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-31', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-31', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    const existing = db.prepare("SELECT id,status,data_json,source_id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved')").all(semanticKey);
    if (existing.some((row) => row.status === 'pending')) throw new Error(`Pending evolution blocks ${semanticKey}`);
    const revision = Math.max(0, ...existing.map((row) => Number(JSON.parse(row.data_json || '{}').revision) || 0)) + 1;
    const candidateId = uuid(`candidate:${semanticKey}:${revision}`);
    const applied = existing.find((row) => row.source_id === sourceId);
    if (!applied) {
      const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
      if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);
      const data = JSON.stringify({ revision, supersedes_semantic_revision: revision - 1, installation: { status: 'installed_verified', global_scope: true }, skills: { marketing: ['marketing-brief', 'positioning', 'customer-research', 'content-strategy', 'seo-strategy', 'copywriting', 'cro-audit', 'analytics-tracking', 'email-sequence'], design: ['frontend-design', 'ui-ux', 'image'], development: ['security-best-practices', 'playwright', 'code-review', 'architecture-review', 'debugging-and-error-recovery', 'gh-fix-ci'] }, multi_agent_pilot: { max_read_only_branches: 3, synthesis: 'strategy_required', writer_count: 1 }, landing: { subproject_id: '2a95e640-23b0-44a6-96e5-f9f732cd41fa', sources: ['work/landing/index.html', 'work/landing/404.html'], url: 'https://go.mtrhit.ru/', http_status: 200, github: 'not_authorized_or_deployed' }, evidence: { path: decisionPath } });
      created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-31', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
      if (db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Синхронизировано по прямому поручению владельца перед переходом в новый Strategy-чат.', reviewedAt, candidateId);
    }
    const storedCandidate = db.prepare('SELECT * FROM memory_candidates WHERE source_id=? AND semantic_key=?').get(sourceId, semanticKey);
    assertRow(storedCandidate, { type: 'decision', semantic_key: semanticKey, title, content, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'continuity candidate');
    const task = db.prepare('SELECT status FROM tasks WHERE id=?').get(priorTaskId);
    if (!task) throw new Error('Marketing-skills task was not found');
    if (task.status !== 'completed') created.completedTasks += Number(db.prepare("UPDATE tasks SET status='completed',updated_at=?,version=version+1 WHERE id=? AND status<>'completed'").run(reviewedAt, priorTaskId).changes);
    assertRow(db.prepare('SELECT * FROM tasks WHERE id=?').get(priorTaskId), { status: 'completed' }, 'completed marketing-skills task');
    const beforeRecords = db.prepare("SELECT count(*) AS count FROM scoped_memory_records WHERE id IN (?,?)").get(stableRecordId('skills-and-pilot'), stableRecordId('landing-project-record')).count;
    ensureScopedRecord(db, { id: stableRecordId('skills-and-pilot'), semanticKey: 'operations.global_skills_and_multi_agent_pilot', scopeId: 'scope:core', title: 'Глобальные навыки и controlled multi-agent pilot', content: 'Глобально установлены и проверены 9 маркетинговых, 3 дизайн- и 6 development-навыков из continuity decision. Их выбор определяется задачей; controlled pilot ограничен 2–3 независимыми read-only research/audit-ветками и synthesis Strategy, а writer остаётся один.', taskTypes: ['all'] });
    ensureScopedRecord(db, { id: stableRecordId('landing-project-record'), semanticKey: 'landing.project_store_registration', scopeId: 'scope:subproject:landing', title: 'Регистрация подпроекта «Лендинг»', content: '«Лендинг» зарегистрирован как active подпроект MetricHit: 2a95e640-23b0-44a6-96e5-f9f732cd41fa. Scoped memory изолирована в цепочке Ядро → MetricHit → Лендинг.', taskTypes: ['all'] });
    created.scopedRecords = 2 - Number(beforeRecords);
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, decisionPath, candidateId: storedCandidate.id, created };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied Strategy continuity: ${JSON.stringify(applyStrategyContinuity(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
