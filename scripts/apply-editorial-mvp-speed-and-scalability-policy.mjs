import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-mvp-speed-and-scalability-policy-2026-08-14.md';
const semanticKey = 'editorial.mvp_speed_and_scalability_policy';
const owner = 'owner';
const reviewedAt = '2026-08-14T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-editorial-mvp-policy:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyEditorialMvpSpeedAndScalabilityPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Editorial MVP decision contains U+FFFD');

  const title = 'Скорость MVP и масштабируемость редакционного контура';
  const candidateContent = 'MetricHit OS развивается короткими сквозными MVP-этапами. Первый рабочий контур создаёт одну статью для одной выбранной площадки и производные посты Telegram/VK, после чего останавливается на согласовании. Конечная система должна поддерживать несколько статейных площадок и аккаунтов, но масштабирование добавляется после проверки первого контура. Провайдеры моделей и площадки подключаются через узкие сменные адаптеры без изменения редакционного ядра. Преждевременная универсализация запрещена.';
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-14',
  });
  const candidateData = JSON.stringify({
    delivery: 'short_vertical_mvp',
    first_contour: ['one_article', 'telegram_derivative', 'vk_derivative', 'owner_approval_stop'],
    future_scale: ['multiple_article_platforms', 'multiple_accounts'],
    extension_style: 'narrow_replaceable_adapters',
    premature_generalization: 'forbidden',
    evidence: { path: decisionPath },
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
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
      VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-14', 'internal', 1)
    `).run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);

    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate?.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1
        WHERE id=?
      `).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 14.08.2026.', reviewedAt, candidateId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), {
      type: 'decision', semantic_key: semanticKey, title, content: candidateContent,
      data_json: candidateData, status: 'approved', source_id: sourceId, author: owner,
      valid_at: '2026-08-14', access_level: 'internal', reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'editorial MVP policy candidate');
    assertFields(database.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), {
      type: 'owner_decision', title, content: `Repository file: ${decisionPath}`,
      data_json: metadata, status: 'active', author: owner, valid_at: '2026-08-14',
      access_level: 'internal', version: 1,
    }, 'editorial MVP policy source');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), {
      type: 'owner_decision', title, content, data_json: metadata, status: 'active', source_id: sourceId,
      author: owner, valid_at: '2026-08-14', access_level: 'internal', version: 1,
    }, 'editorial MVP policy document');
    assertFields(database.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), {
      document_id: documentId, type: 'owner_decision', title, content, data_json: metadata,
      status: 'active', source_id: sourceId, author: owner, valid_at: '2026-08-14',
      access_level: 'internal', version: 1,
    }, 'editorial MVP policy document version');
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
  const result = applyEditorialMvpSpeedAndScalabilityPolicy(
    process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath,
  );
  console.log(`Applied editorial MVP policy to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
}
