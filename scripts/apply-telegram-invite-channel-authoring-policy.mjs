import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/telegram-invite-channel-authoring-2026-09-14.md';
const semanticKey = 'editorial.telegram_invite_channel_authoring';
const policyRevision = 4;
const owner = 'owner';
const reviewedAt = '2026-09-14T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-telegram-invite:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

export function applyTelegramInviteChannelAuthoringPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Автор invite-канала Telegram MetricHit';
  const content = 'Invite-канал MetricHit ведёт читателя в основной Telegram-канал и не дублирует длинные разборы. Каждый пост содержит 600–750 знаков в фактически отправляемом тексте, начинаетcя с одного жирного Markdown-заголовка и допускает только вторую жирную строку для основного канала в обязательном футере. Иная разметка, ссылки, эмодзи в теле, стрелки и декоративные списки запрещены. Один пост даёт узнаваемую ситуацию, один полезный принцип и короткую причину продолжить тему в основном канале, не исчерпывая глубокий материал. Каждый пакет имеет бриф и подготовленный визуальный актив; offline-автор не создаёт изображения, а публикация без актива fail-closed блокируется до сети. Автор не придумывает метрики, кейсы, обновления и не раскрывает механику бота. Публикация, запуск бота или расписания, сеть, credentials и привязка канала этим решением не разрешаются.';
  const priorCandidateId = stableUuid(`candidate:${semanticKey}:${policyRevision - 1}`);
  const data = JSON.stringify({ revision: policyRevision, supersedes_candidate_id: priorCandidateId, platform: 'telegram', channel_role: 'invite_to_main_channel', character_count_including_footer: { minimum: 600, maximum: 750, serialized_outbound_text: true }, markdown: { permitted_bold_lines: ['headline', 'main_channel_footer'], pair_count: 2, other_markup_prohibited: true }, visual_deliverable: { required: true, offline_author_generates_files: false, missing_asset_blocks_publication: true }, footer_icons_only: ['📢', '🌐', '💬'], decorative_lists_prohibited: true, structure: ['recognizable_situation', 'one_useful_reframe_or_principle', 'main_channel_bridge'], full_footer: ['**📢 Основной канал MetricHit: https://t.me/mtr_hit**', '', '🌐 Сайт MetricHit: https://go.mtrhit.ru/', '💬 Поддержка в Telegram: https://t.me/Metric_Hit'], prohibited: ['invented_metrics_or_cases', 'unverified_search_updates', 'search_bot_mechanics_disclosure', 'publication_or_runtime_actions'], evidence: { path: decisionPath } });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-14' });
  const sourceId = stableUuid(`source:${decisionPath}:${policyRevision}`); const documentId = stableUuid(`document:${decisionPath}:${policyRevision}`);
  const versionId = stableUuid(`version:${decisionPath}:${policyRevision}`); const candidateId = stableUuid(`candidate:${semanticKey}:${policyRevision}`);
  const database = new DatabaseSync(databasePath); const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const prior = database.prepare("SELECT id,status FROM memory_candidates WHERE id=? AND semantic_key=?").get(priorCandidateId, semanticKey);
    if (!prior || prior.status !== 'approved') throw new Error('Approved Telegram invite authoring revision 3 is required before the final visual-package refinement');
    const duplicate = database.prepare("SELECT id,status,coalesce(json_extract(data_json, '$.revision'), 1) AS revision FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").all(semanticKey, candidateId)
      .filter((row) => row.id !== priorCandidateId && (row.status !== 'approved' || Number(row.revision) >= policyRevision));
    if (duplicate.length) throw new Error('Semantic duplicate or evolution blocks Telegram invite authoring policy');
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error('Open memory conflict blocks Telegram invite authoring policy');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?,'owner_decision',?,?,?,'active',?,'2026-09-14','internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'owner_decision',?,?,?,'active',?,?,'2026-09-14','internal',1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,?, ?,?,?,?,'active',?,?,'2026-09-14','internal',1)").run(versionId, documentId, 'owner_decision', title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'editorial_rule',?,?,?,?,'pending',?,?,'2026-09-14','internal',1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым указанием владельца MetricHit от 14.09.2026.', reviewedAt, candidateId);
    database.exec('COMMIT'); return { databasePath, created, semanticKey, candidateId };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(JSON.stringify(applyTelegramInviteChannelAuthoringPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath)));
