import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/yadro-independent-project-contours-2026-08-21.md';
const owner = 'owner';
const reviewedAt = '2026-08-21T00:00:00.000Z';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-yadro-project-contours:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function latestRevision(rows) {
  return Math.max(0, ...rows.map((row) => Number(JSON.parse(row.data_json || '{}').revision) || 0));
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyYadroIndependentProjectContours(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
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
  const entries = [
    {
      semanticKey: 'architecture.operating_core_and_departments',
      type: 'decision',
      title: 'Независимые проектные контуры «Ядра»',
      content: '«Ядро» — OS и управляющий контур для нескольких независимых проектов. MetricHit — первый проект внутри «Ядра»; понятие «MetricHit OS» не используется для целевой модели. У каждого проекта должны быть собственные память, правила и бизнес-истина, независимые от «Ядра» и друг от друга. Ближайший приоритет до любой иной разработки — подготовить проектные контуры: отдельное физическое хранилище каждого проекта, безопасную миграцию существующих данных, экспорт/импорт самостоятельного проекта и изоляцию проектов в операторской панели. Реализация каждого направления начинается только после отдельного утверждения владельца; это решение не меняет схему, интерфейс или данные.',
      data: {
        yadro_role: 'operating_system_and_control_plane',
        metrichit_role: 'managed_project_inside_yadro',
        target_term: 'Ядро',
        deprecated_target_term: 'MetricHit OS',
        project_independence: ['memory', 'rules', 'business_truth'],
        next_priority: ['physical_project_storage', 'safe_migration', 'project_export_import', 'operator_panel_isolation'],
        implementation_requires_separate_owner_approval: true,
      },
    },
    {
      semanticKey: 'architecture.backend_runtime_python_fastapi',
      type: 'decision',
      title: 'Целевой backend «Ядра»: Python/FastAPI',
      content: 'Целевой backend «Ядра» — Python 3.13 и FastAPI. Новая функциональность Node.js заморожена, а существующее Node.js-ядро остаётся эталоном совместимости. SQLite сохраняется для MVP. Удаление Node.js-ядра возможно только после функционального паритета, прохождения полного набора тестов и отдельного решения владельца. Python-зависимости устанавливаются только в проектное окружение .venv, без глобальной установки.',
      data: { target_system: 'Ядро', runtime: 'Python 3.13', framework: 'FastAPI', revision_note: 'terminology synchronized with independent project contours' },
    },
    {
      semanticKey: 'architecture.decision_governance_policy',
      type: 'decision',
      title: 'Политика контура решений «Ядра»',
      content: 'Контур решений относится к «Ядру», а не к отделу или автономному агенту. Явно утверждённые владельцем решения могут сохраняться как approved; предложения, выводы и непринятые варианты остаются pending candidates, а потенциальные решения никогда не auto-approve. Перед сохранением проверяются semantic duplicate, evolution и conflicts. Решения могут связываться с проектом, задачей, источником и при необходимости Git-коммитом. В current context включаются только значимые approved-решения; технические мелкие правки решениями не считаются. Контур охватывает архитектуру, продукт, приоритеты, правила, бюджеты, сроки, права, ограничения и направления проектов.',
      data: { target_system: 'Ядро', governance_scope: 'central_core', revision_note: 'terminology synchronized with independent project contours' },
    },
    {
      semanticKey: 'product.management_and_commercial_purpose',
      type: 'product_fact',
      title: 'Управленческое и коммерческое назначение «Ядра»',
      content: '«Ядро» помогает владельцу понимать, что происходит в бизнесе, почему это происходит, что приносит результат и какое решение сейчас важнее. Система связывает фактические данные с целями, решениями, независимыми проектами, задачами и результатами. Направления развития: измеримые результаты, реестр решений, гипотезы и эксперименты, центр решений владельца, простая экономика проектов и отделов, ежедневные и недельные сводки, объяснимое состояние работы и повторно используемые шаблоны запуска. Это направления развития, а не уже реализованные функции. Сложный Гант, корпоративный чат, видеосвязь, тяжёлый календарь и замена CRM не являются текущим приоритетом.',
      data: { target_system: 'Ядро', manages_independent_projects: true, revision_note: 'terminology synchronized with independent project contours' },
    },
    {
      semanticKey: 'editorial.mvp_speed_and_scalability_policy',
      type: 'decision',
      title: 'Скорость MVP и масштабируемость редакционного контура',
      content: '«Ядро» развивается короткими сквозными MVP-этапами. Первый рабочий редакционный контур создаёт одну статью для одной выбранной площадки и производные посты Telegram/VK, после чего останавливается на согласовании. Конечная система должна поддерживать несколько статейных площадок и аккаунтов, но масштабирование добавляется после проверки первого контура. Провайдеры моделей и площадки подключаются через узкие сменные адаптеры без изменения редакционного ядра. Преждевременная универсализация запрещена.',
      data: { target_system: 'Ядро', revision_note: 'terminology synchronized with independent project contours' },
    },
  ];

  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-21', 'internal')").run(sourceId, 'Независимые проектные контуры «Ядра»', `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-21', 'internal', 1)").run(documentId, 'Независимые проектные контуры «Ядра»', decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-21', 'internal', 1)").run(versionId, documentId, 'Независимые проектные контуры «Ядра»', decision, metadata, sourceId, owner).changes);

    for (const entry of entries) {
      const existing = db.prepare("SELECT id,status,data_json,source_id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved')").all(entry.semanticKey);
      const alreadyApplied = existing.find((row) => row.source_id === sourceId);
      if (alreadyApplied) {
        const candidate = db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(alreadyApplied.id);
        assertRow(candidate, { type: entry.type, semantic_key: entry.semanticKey, title: entry.title, content: entry.content, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, entry.semanticKey);
        continue;
      }
      if (existing.some((row) => row.status === 'pending')) throw new Error(`Pending evolution blocks ${entry.semanticKey}`);
      const revision = latestRevision(existing) + 1;
      const candidateId = uuid(`candidate:${entry.semanticKey}:${revision}`);
      const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, entry.semanticKey);
      if (conflict) throw new Error(`Open memory conflict blocks ${entry.semanticKey}`);
      const data = JSON.stringify({ ...entry.data, revision, supersedes_semantic_revision: revision - 1, evidence: { path: decisionPath } });
      created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, '2026-08-21', 'internal', 1)").run(candidateId, entry.type, entry.semanticKey, entry.title, entry.content, data, sourceId, owner).changes);
      const candidate = db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
      if (candidate.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца от 21.08.2026.', reviewedAt, candidateId);
      assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: entry.type, semantic_key: entry.semanticKey, title: entry.title, content: entry.content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, entry.semanticKey);
    }
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, decisionPath, created };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`Applied independent project contours: ${JSON.stringify(applyYadroIndependentProjectContours(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
}
