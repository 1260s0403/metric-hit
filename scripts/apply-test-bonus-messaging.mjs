import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/test-bonus-messaging-2026-08-14.md';
const owner = 'owner';
const reviewedAt = '2026-08-14T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-test-bonus-messaging:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyTestBonusMessaging(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Test bonus messaging decision contains U+FFFD');
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-14',
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const candidateId = stableUuid('candidate:content.test_bonus_messaging');
  const title = 'Сообщение тестового бонуса';
  const candidateContent = 'Во внешних рекламных материалах тестовый бонус подаётся через выгоду: 1 000 кликов на тест без пополнения баланса. Основной CTA сначала сообщает выгоду, затем действие: зарегистрироваться и отправить логин в Telegram-поддержку. Слова «один раз» и «только один раз» не повторяются в обычных рекламных CTA. Фактическое ограничение на однократное начисление сохраняется во внутреннем описании условий и при необходимости указывается в FAQ или полных правилах предложения. Базовый факт product.test_bonus не заменять и не удалять.';
  const candidateData = JSON.stringify({
    external_benefit: '1 000 кликов на тест без пополнения баланса',
    cta_order: ['benefit', 'register', 'send_login_to_telegram_support'],
    avoid_in_regular_promotional_cta: ['один раз', 'только один раз'],
    factual_limit_location: ['internal_terms', 'faq', 'full_offer_rules'],
    preserve_base_fact: 'product.test_bonus',
    current_base_fact: 'bonus.new_user_test_clicks',
    evidence: { path: decisionPath },
  });

  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  try {
    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-14', 'internal')
    `).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(documentId, title, content, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(versionId, documentId, title, content, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'editorial_rule', 'content.test_bonus_messaging', ?, ?, ?, 'pending', ?, ?, '2026-08-14', 'internal', 1)
    `).run(candidateId, title, candidateContent, candidateData, sourceId, owner).changes);

    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?, review_note = ?,
            updated_at = ?, version = version + 1
        WHERE id = ?
      `).run(owner, reviewedAt, 'Одобрено на основании прямого решения владельца MetricHit от 14.08.2026.', reviewedAt, candidateId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), {
      type: 'editorial_rule', semantic_key: 'content.test_bonus_messaging', title,
      content: candidateContent, data_json: candidateData, source_id: sourceId,
      status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'test bonus messaging candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      content, data_json: metadata, source_id: sourceId, version: 1,
    }, 'test bonus messaging document');
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
  const result = applyTestBonusMessaging(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
  console.log(`Applied test bonus messaging policy to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
}
