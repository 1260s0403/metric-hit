import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/publication-links-sostav-oborot-2026-08-29.md';
const owner = 'owner';
const reviewedAt = '2026-08-29T15:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-publication-links:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyPublicationLinksSostavOborot(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation_with_owner_provided_public_url', decision_date: '2026-08-29', independent_fetch: 'not_confirmed_safe_index_limitation' });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const publications = [
    {
      semanticKey: 'publication.sostav_nakrutka_pf_2026_08_29', revision: 2,
      title: 'Публикация «Накрутка ПФ» на Sostav / SBlogs',
      content: 'Подтверждённая владельцем публикация статьи «Накрутка ПФ» на Sostav / SBlogs от 29.08.2026. Публичный URL, переданный владельцем: https://www.sostav.ru/blogs/293151/104675. Независимая внешняя проверка не проводилась.',
      data: { platform: 'Sostav / SBlogs', publication_date: '2026-08-29', publication_status: 'confirmed', confirmation_basis: 'owner_confirmation_with_owner_provided_public_url', public_url: 'https://www.sostav.ru/blogs/293151/104675', final_article_path: 'work/articles/published/2026-08-29-sostav-nakrutka-pf.md', revision: 2, supersedes_semantic_revision: 1, evidence: { path: decisionPath, independent_fetch: 'not_confirmed_safe_index_limitation' } },
    },
    {
      semanticKey: 'publication.oborot_nakrutka_pf_business_2026_08_29', revision: 1,
      title: 'Публикация «Накрутка ПФ: как бизнесу управлять поисковым продвижением и бюджетом» на Oborot.ru',
      content: 'Подтверждённая владельцем публикация статьи «Накрутка ПФ: как бизнесу управлять поисковым продвижением и бюджетом» на Oborot.ru от 29.08.2026. Публичный URL, переданный владельцем: https://oborot.ru/blogs/nakrutka-pf-i277755.html. Независимая внешняя проверка не проводилась.',
      data: { platform: 'Oborot.ru', publication_date: '2026-08-29', publication_status: 'confirmed', confirmation_basis: 'owner_confirmation_with_owner_provided_public_url', public_url: 'https://oborot.ru/blogs/nakrutka-pf-i277755.html', final_article_path: 'work/articles/published/2026-08-29-oborot-nakrutka-pf-business.md', revision: 1, evidence: { path: decisionPath, independent_fetch: 'not_confirmed_safe_index_limitation' } },
    },
  ];

  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    for (const publication of publications) {
      const candidateId = stableUuid(`candidate:${publication.semanticKey}:revision:${publication.revision}`);
      const duplicate = database.prepare(`SELECT id FROM memory_candidates WHERE semantic_key = ? AND status IN ('pending', 'approved') AND coalesce(json_extract(data_json, '$.revision'), 0) = ? AND id <> ?`).get(publication.semanticKey, publication.revision, candidateId);
      if (duplicate) throw new Error(`Semantic duplicate blocks ${publication.semanticKey} revision ${publication.revision}`);
    }
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-29', 'internal')").run(sourceId, 'Подтверждение ссылок публикаций Sostav и Oborot', `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(documentId, 'Подтверждение ссылок публикаций Sostav и Oborot', decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(versionId, documentId, 'Подтверждение ссылок публикаций Sostav и Oborot', decision, metadata, sourceId, owner).changes);
    for (const publication of publications) {
      const candidateId = stableUuid(`candidate:${publication.semanticKey}:revision:${publication.revision}`);
      const data = JSON.stringify(publication.data);
      created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'publication_state', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(candidateId, publication.semanticKey, publication.title, publication.content, data, sourceId, owner).changes);
      const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(candidateId);
      if (candidate?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым подтверждением владельца и переданным им публичным URL от 29.08.2026; независимый fetch не подтверждён.', reviewedAt, candidateId);
      assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), { type: 'publication_state', semantic_key: publication.semanticKey, title: publication.title, content: publication.content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, `${publication.semanticKey} candidate`);
    }
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId };
  } catch (error) {
    database.exec('ROLLBACK'); throw error;
  } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied publication links: ${JSON.stringify(applyPublicationLinksSostavOborot(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
