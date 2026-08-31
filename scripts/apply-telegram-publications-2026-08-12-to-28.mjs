import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/telegram-publications-2026-08-12-to-28.md';
const owner = 'owner';
const reviewedAt = '2026-08-31T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-telegram-publications:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

function section(document, number) {
  const marker = `## ${number}. `;
  const start = document.indexOf(marker);
  if (start < 0) throw new Error(`Missing post ${number} in decision`);
  const next = document.indexOf('\n## ', start + marker.length);
  const value = document.slice(start, next < 0 ? document.length : next).trim();
  return value.slice(value.indexOf('\n') + 1).trim();
}

function assetMetadata(assetPath) {
  if (!assetPath) return null;
  const absolutePath = join(repositoryRoot, assetPath);
  if (!existsSync(absolutePath)) throw new Error(`Missing Telegram asset: ${assetPath}`);
  const bytes = readFileSync(absolutePath);
  return { path: assetPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), media_type: 'image/png' };
}

export function applyTelegramPublications20260812To28(databasePath = defaultDatabasePath) {
  const decisionBytes = readFileSync(join(repositoryRoot, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(decisionBytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const metadata = JSON.stringify({ path: decisionPath, bytes: decisionBytes.length, sha256: createHash('sha256').update(decisionBytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-31' });
  const definitions = [
    ['publication.telegram_2026_08_12_navigation', 'Навигация по каналу MetricHit', '2026-08-12', true, null],
    ['publication.telegram_2026_08_13_yandex_updates', 'Три обновления Яндекса, которые стоит знать', '2026-08-13', false, null],
    ['publication.telegram_2026_08_17_work_restored', 'Работа MetricHit восстановлена', '2026-08-17', false, 'work/social/telegram/assets/2026-08-17-work-restored.png'],
    ['publication.telegram_2026_08_19_bonus_20_percent', '+20% к пополнению баланса', '2026-08-19', false, 'work/social/telegram/assets/2026-08-19-bonus-20-percent.png'],
    ['publication.telegram_2026_08_20_positions_declined', 'Позиции просели: что проверить до изменения ПФ', '2026-08-20', false, 'work/social/telegram/assets/2026-08-20-positions-declined-checks.png'],
    ['publication.telegram_2026_08_25_infrastructure_expanded', 'MetricHit расширил инфраструктуру', '2026-08-25', false, 'work/social/telegram/assets/2026-08-25-infrastructure-expanded.png'],
    ['publication.telegram_2026_08_27_prices_reduced', 'Масштаб вырос. Цена за клик снизилась!', '2026-08-27', false, 'work/social/telegram/assets/2026-08-27-prices-reduced.png'],
    ['publication.telegram_2026_08_27_new_tariff_applied', 'Новая тарификация применена ко всем пользователям', '2026-08-27', false, null],
    ['publication.telegram_2026_08_28_bonus_15_percent', 'Вы просили — мы услышали', '2026-08-28', false, 'work/social/telegram/assets/2026-08-28-bonus-15-percent.png'],
  ].map(([semanticKey, title, publicationDate, pinned, assetPath], index) => ({ semanticKey, title, publicationDate, pinned, assetPath, order: index + 1, content: section(decision, index + 1) }));
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    for (const post of definitions) {
      const candidateId = stableUuid(`candidate:${post.semanticKey}:revision:1`);
      const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(post.semanticKey, candidateId);
      if (duplicate) throw new Error(`Semantic duplicate blocks ${post.semanticKey}`);
      const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND candidate_id=?").get(candidateId);
      if (conflict) throw new Error(`Open memory conflict blocks ${post.semanticKey}`);
    }
    const summaryId = stableUuid('candidate:publication.telegram_confirmed_set:revision:2');
    const priorSummary = database.prepare("SELECT id, coalesce(json_extract(data_json, '$.revision'), 0) AS revision FROM memory_candidates WHERE semantic_key='publication.telegram_confirmed_set' AND status IN ('pending','approved') AND id<>?").all(summaryId);
    if (priorSummary.some((row) => Number(row.revision) !== 0)) throw new Error('Unexpected Telegram publication-set revision');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?,'owner_decision',?,?,?,'active',?,'2026-08-31','internal')").run(sourceId, 'Подтверждённые Telegram-публикации 12–28 августа 2026', `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'owner_decision',?,?,?,'active',?,?,'2026-08-31','internal',1)").run(documentId, 'Подтверждённые Telegram-публикации 12–28 августа 2026', decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,?,'owner_decision',?,?,?,'active',?,?,'2026-08-31','internal',1)").run(versionId, documentId, 'Подтверждённые Telegram-публикации 12–28 августа 2026', decision, metadata, sourceId, owner).changes);
    for (const post of definitions) {
      const candidateId = stableUuid(`candidate:${post.semanticKey}:revision:1`);
      const data = JSON.stringify({ platform: 'telegram', publication_date: post.publicationDate, publication_status: 'confirmed', confirmation_basis: 'owner_confirmation', publication_order: post.order, pinned: post.pinned, full_text: post.content, asset: assetMetadata(post.assetPath), evidence: { path: decisionPath, section: `§ ${post.order}` }, revision: 1 });
      created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'publication_state',?,?,?,?, 'pending',?,? ,?,'internal',1)").run(candidateId, post.semanticKey, post.title, post.content, data, sourceId, owner, post.publicationDate).changes);
      if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым поручением владельца от 31.08.2026.', reviewedAt, candidateId);
      assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'publication_state', semantic_key: post.semanticKey, title: post.title, content: post.content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, post.semanticKey);
    }
    const summaryContent = 'В Telegram-канале подтверждены семь первоначальных постов со ссылками и девять постов от 12–28 августа 2026. Навигация от 12.08.2026 закреплена; для шести новых постов сохранены приложенные изображения.';
    const summaryData = JSON.stringify({ platform: 'telegram', linked_post_ids: [6, 7, 8, 9, 10, 11, 13], navigation_pinned: true, yandex_updates_post: true, confirmed_publications_2026_08_12_to_28: definitions.map(({ semanticKey, publicationDate, order }) => ({ semantic_key: semanticKey, publication_date: publicationDate, order })), evidence: { path: decisionPath }, revision: 2, supersedes_semantic_revision: 0 });
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'publication_state','publication.telegram_confirmed_set','Подтверждённые публикации Telegram',?,?,'pending',?,?,'2026-08-31','internal',1)").run(summaryId, summaryContent, summaryData, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(summaryId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым поручением владельца от 31.08.2026; дополняет подтверждённый набор Telegram-публикаций.', reviewedAt, summaryId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(summaryId), { type: 'publication_state', semantic_key: 'publication.telegram_confirmed_set', title: 'Подтверждённые публикации Telegram', content: summaryContent, data_json: summaryData, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'Telegram publication-set revision 2');
    assertFields(database.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    database.exec('COMMIT');
    return { databasePath, created, publications: definitions.length };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied Telegram publications: ${JSON.stringify(applyTelegramPublications20260812To28(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
