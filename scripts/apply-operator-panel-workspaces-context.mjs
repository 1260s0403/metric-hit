import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/operator-panel-workspaces-2026-08-18.md';
const semanticKey = 'ui.operator_panel_workspace_screens';
const owner = 'owner';
const reviewedAt = '2026-08-18T18:00:00.000Z';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-operator-panel-workspaces:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyOperatorPanelWorkspacesContext(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const title = 'Утверждённые рабочие экраны operator panel';
  const content = 'В продолжение утверждённого Codex Desktop-like направления реализованы: универсальная локальная рабочая область подпроекта с верхним меню и обзором; «Активность» с audit-потоком, рабочими фильтрами проекта и периода и правой панелью подробностей без изменения размеров строк; глобальный «Поиск» с двухколоночной областью, фильтрами типа/проекта/статуса, сбросом, сортировкой и переходом к первоисточнику. Глобальная левая навигация сохранена, кроме переноса «Поиска» в конец списка. Проверенные поставки: f82b183, 90184ae, 8a3a2cf, 7f84099, 335e336, a20c15b.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-18' });
  const data = JSON.stringify({ visual_direction: 'codex_desktop_like_dark_monochrome', accepted_screens: ['scoped_subproject_workspace', 'activity_audit_workspace', 'global_search_workspace'], sidebar_change: 'search_last_only', subproject_workspace: { reusable_for_any_subproject: true, sections: ['local_top_menu', 'overview'] }, activity: { filters: ['type', 'project', 'period'], details: 'right_drawer_without_row_resize' }, global_search: { layout: 'two_column', filters: ['type', 'project', 'status'], interactions: ['reset', 'sort', 'source_navigation'] }, verified_commits: ['f82b183', '90184ae', '8a3a2cf', '7f84099', '335e336', 'a20c15b'], evidence: { path: decisionPath } });
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const candidateId = uuid(`candidate:${semanticKey}`);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = db.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-18', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-18', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-18', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-18', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate?.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Синхронизировано по прямым утверждениям владельца в Strategy-чате 18.08.2026.', reviewedAt, candidateId);
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'operator panel workspace candidate');
    db.exec('COMMIT');
    return { databasePath, semanticKey, created };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied operator panel workspace context: ${JSON.stringify(applyOperatorPanelWorkspacesContext(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
