import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/sostav-nakrutka-pf-publication-2026-08-29.md';
const semanticKey = 'publication.sostav_nakrutka_pf_2026_08_29';
const owner = 'owner';
const reviewedAt = '2026-08-29T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-sostav-publication:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

export function applySostavNakrutkaPfPublication(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Публикация «Накрутка ПФ» на Sostav / SBlogs';
  const content = 'Подтверждённая владельцем публикация статьи «Накрутка ПФ» на Sostav / SBlogs от 29.08.2026. Публичный URL: unknown / not_provided. Финальная локальная версия: work/articles/published/2026-08-29-sostav-nakrutka-pf.md.';
  const data = JSON.stringify({ platform: 'Sostav / SBlogs', publication_date: '2026-08-29', publication_status: 'confirmed', confirmation_basis: 'owner_confirmation', public_url: 'unknown/not_provided', final_article_path: 'work/articles/published/2026-08-29-sostav-nakrutka-pf.md', evidence: { path: decisionPath } });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-29' });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-29', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'publication_state', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым подтверждением владельца MetricHit от 29.08.2026.', reviewedAt, candidateId);
    const stored = database.prepare('SELECT type, semantic_key, title, content, data_json, status, reviewed_by, reviewed_at FROM memory_candidates WHERE id = ?').get(candidateId);
    if (!stored || stored.type !== 'publication_state' || stored.semantic_key !== semanticKey || stored.title !== title || stored.content !== content || stored.data_json !== data || stored.status !== 'approved' || stored.reviewed_by !== owner || stored.reviewed_at !== reviewedAt) throw new Error('Stored publication confirmation differs');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied Sostav publication: ${JSON.stringify(applySostavNakrutkaPfPublication(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
