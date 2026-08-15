import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/operating-core-and-management-purpose-2026-08-15.md';
const reviewedAt = '2026-08-15T15:20:00.000Z';
const revision = 2;

function uuid(key) {
  const h = createHash('sha256').update(`metrichit-operating-context:${key}`).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
}

const entries = [
  {
    key: 'architecture.operating_core_and_departments',
    type: 'decision',
    title: 'Архитектура операционного ядра и автономных отделов',
    content: 'MetricHit OS — центральное операционное ядро бизнеса. Цепочка ядра: информация → память → решение → проект → задача → выполнение → аудит. Ядро отвечает за память, проекты, задачи, решения, права, аудит, бюджеты, согласования и резервирование. Отделы являются автономными бизнес-модулями, а агенты и модели — заменяемыми исполнителями; прямые записи между БД ядра и отделов запрещены, взаимодействие идёт через стабильные сервисные контракты. Редакция остаётся автономным первым отделом. Текущая архитектура — модульный монолит; микросервисы, Kafka и универсальная plugin-платформа не нужны до запуска минимум двух автономных отделов. Завершён модуль проектов; ближайшие этапы — единый входящий поток, затем UI управления памятью. Серверный перенос, editorial API и публикации остаются на паузе. Канонические документы: documents/operating-context.md и documents/roadmap.md.',
    data: {
      chain: ['information', 'memory', 'decision', 'project', 'task', 'execution', 'audit'],
      architecture: 'modular_monolith',
      department_boundary: 'stable_service_contracts',
      direct_cross_database_writes: false,
      generalize_after_departments: 2,
      next: ['unified_inbox', 'memory_management_ui'],
      paused: ['server_migration', 'editorial_openai_api', 'automatic_publication', 'editorial_production'],
    },
  },
  {
    key: 'product.management_and_commercial_purpose',
    type: 'product_fact',
    title: 'Управленческое и коммерческое назначение MetricHit OS',
    content: 'MetricHit OS помогает владельцу понимать, что происходит в бизнесе, почему это происходит, что приносит результат и какое решение сейчас важнее. Система должна связывать фактические данные с целями, решениями, проектами, задачами и результатами. Направления развития: измеримые результаты, реестр решений, гипотезы и эксперименты, центр решений владельца, простая экономика проектов и отделов, ежедневные и недельные сводки, объяснимое состояние работы и повторно используемые шаблоны запуска. Это направления развития, а не уже реализованные функции. Сложный Гант, корпоративный чат, видеосвязь, тяжёлый календарь и замена CRM не являются текущим приоритетом.',
    data: {
      owner_questions: ['what_is_happening', 'why', 'what_drives_results', 'what_decision_matters_now'],
      future_directions_not_implemented: true,
      reusable_launch_templates: 'future_direction',
      excluded_current_priorities: ['complex_gantt', 'corporate_chat', 'video', 'heavy_calendar', 'crm_replacement'],
    },
  },
];

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [key, value] of Object.entries(expected)) if (row[key] !== value) throw new Error(`${label}.${key} differs`);
}

export function applyOperatingContext(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), authority: 'direct_owner_confirmation', decision_date: '2026-08-15' });
  const sourceId = uuid(`source:${decisionPath}:${revision}`);
  const documentId = uuid(`document:${decisionPath}:${revision}`);
  const versionId = uuid(`version:${decisionPath}:${revision}`);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(db.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', 'owner', '2026-08-15', 'internal')`).run(sourceId, 'Операционное ядро и управленческое назначение MetricHit OS', `Repository file: ${decisionPath}`, metadata).changes);
    created.documents += Number(db.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-08-15', 'internal', 1)`).run(documentId, 'Операционное ядро и управленческое назначение MetricHit OS', decision, metadata, sourceId).changes);
    created.versions += Number(db.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-08-15', 'internal', 1)`).run(versionId, documentId, 'Операционное ядро и управленческое назначение MetricHit OS', decision, metadata, sourceId).changes);
    for (const entry of entries) {
      const candidateId = uuid(`candidate:${entry.key}:${revision}`);
      const data = JSON.stringify({ ...entry.data, revision, supersedes_semantic_revision: revision - 1, evidence: { path: decisionPath } });
      created.candidates += Number(db.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 'owner', '2026-08-15', 'internal', 1)`).run(candidateId, entry.type, entry.key, entry.title, entry.content, data, sourceId).changes);
      const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
      if (candidate.status === 'pending') db.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?,review_note='Одобрено прямым решением владельца MetricHit от 15.08.2026.',updated_at=?,version=version+1 WHERE id=?`).run(reviewedAt, reviewedAt, candidateId);
      assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { semantic_key: entry.key, type: entry.type, title: entry.title, content: entry.content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: 'owner', reviewed_at: reviewedAt }, entry.key);
    }
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, created, keys: entries.map(({ key }) => key) };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally {
    db.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const result = applyOperatingContext(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase);
  console.log(`Applied operating context: ${JSON.stringify(result)}`);
}
