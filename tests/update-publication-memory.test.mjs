import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { sostavFirstArticleUpdate, updatePublicationMemory } from '../scripts/update-publication-memory.mjs';

test('publication memory update supersedes the existing revision and is idempotent', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-publication-update-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const database = new DatabaseSync(databasePath);
    database.exec("INSERT INTO sources(id,type,title,content,status,author,access_level) VALUES ('10000000-0000-4000-a000-000000000001','owner_decision','Legacy source','Legacy','active','owner','internal');");
    database.exec("INSERT INTO memory_candidates(id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES ('10000000-0000-4000-a000-000000000002','publication_state','publication.sostav_first_article','Legacy','Legacy','{}','pending','10000000-0000-4000-a000-000000000001','owner','2026-08-12','internal',1);");
    database.exec("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-08-12T00:00:00.000Z' WHERE id='10000000-0000-4000-a000-000000000002';");
    database.close();

    const first = updatePublicationMemory(databasePath, sostavFirstArticleUpdate);
    const second = updatePublicationMemory(databasePath, sostavFirstArticleUpdate);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    const candidates = readOnly.prepare(`SELECT title,content,data_json,status FROM memory_candidates
      WHERE semantic_key='publication.sostav_first_article' ORDER BY coalesce(json_extract(data_json, '$.revision'), 0) DESC`).all();
    assert.equal(candidates.length, 2);
    const current = candidates[0];
    const data = JSON.parse(current.data_json);
    assert.equal(current.status, 'approved');
    assert.equal(current.title, sostavFirstArticleUpdate.title);
    assert.match(current.content, /17:51:40/);
    assert.equal(data.canonical_url, sostavFirstArticleUpdate.canonicalUrl);
    assert.equal(data.published_at, '2026-08-12T17:51:40+03:00');
    assert.equal(data.verified_facts.blog_name, 'MetricHit');
    assert.equal(data.verified_facts.robots, 'index,follow');
    assert.deepEqual(data.supersedes_semantic_revisions, [0]);
    assert.equal(readOnly.prepare(`SELECT count(*) AS count FROM memory_candidates
      WHERE semantic_key='publication.sostav_first_article' AND coalesce(json_extract(data_json, '$.revision'), 0)=1`).get().count, 1);
    readOnly.close();
  } finally {
    try {
      rmSync(directory, { recursive: true, force: true, maxRetries: 2, retryDelay: 25 });
    } catch (error) {
      // Windows may retain a transient SQLite file lock after a closed read-only connection.
      // The fixture lives outside the workspace, so retaining it does not affect repository state.
      if (error?.code !== 'EBUSY') throw error;
    }
  }
});
