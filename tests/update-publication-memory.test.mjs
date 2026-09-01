import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import { oborotEditorialIntegrationUpdate, oborotInternetShopPublicationUpdate, sostavFirstArticleUpdate, tenchatInternetShopPublicationUpdate, updatePublicationMemory } from '../scripts/update-publication-memory.mjs';

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

test('Oborot editorial integration update is idempotent and keeps publishing manual', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-oborot-integration-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const database = new DatabaseSync(databasePath);
    database.exec("INSERT INTO sources(id,type,title,content,status,author,access_level) VALUES ('20000000-0000-4000-a000-000000000001','owner_decision','Legacy Oborot source','Legacy','active','owner','internal');");
    database.exec("INSERT INTO memory_candidates(id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES ('20000000-0000-4000-a000-000000000002','publication_state','publication.oborot_nakrutka_pf_business_2026_08_29','Legacy Oborot','Legacy','{\"revision\":1}','pending','20000000-0000-4000-a000-000000000001','owner','2026-08-29','internal',1);");
    database.exec("INSERT INTO memory_candidates(id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES ('20000000-0000-4000-a000-000000000003','publication_state','publication.oborot_nakrutka_pf_business_2026_08_29','Current Oborot','Current','{\"revision\":2}','pending','20000000-0000-4000-a000-000000000001','owner','2026-08-30','internal',1);");
    database.exec("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-08-29T00:00:00.000Z' WHERE id='20000000-0000-4000-a000-000000000002';");
    database.exec("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-08-30T00:00:00.000Z' WHERE id='20000000-0000-4000-a000-000000000003';");
    database.close();

    const first = updatePublicationMemory(databasePath, oborotEditorialIntegrationUpdate);
    const second = updatePublicationMemory(databasePath, oborotEditorialIntegrationUpdate);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });

    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    const current = readOnly.prepare(`SELECT content,data_json,status FROM memory_candidates
      WHERE semantic_key='publication.oborot_nakrutka_pf_business_2026_08_29'
      ORDER BY coalesce(json_extract(data_json, '$.revision'), 0) DESC LIMIT 1`).get();
    const data = JSON.parse(current.data_json);
    assert.equal(current.status, 'approved');
    assert.match(current.content, /manual-package/);
    assert.equal(data.canonical_url, 'https://oborot.ru/blogs/nakrutka-pf-i277755.html');
    assert.equal(data.verified_facts.editorial_connection, 'verified');
    assert.equal(data.verified_facts.workflow_mode, 'manual-package');
    assert.equal(data.verified_facts.official_publishing_api_exposed, false);
    assert.equal(data.verified_facts.external_publication_requires_owner_approval, true);
    assert.equal(data.verified_facts.session_data_stored, false);
    assert.equal(data.evidence.verification_method, 'owner_authenticated_session_read_only_inspection');
    readOnly.close();
  } finally {
    try {
      rmSync(directory, { recursive: true, force: true, maxRetries: 2, retryDelay: 25 });
    } catch (error) {
      if (error?.code !== 'EBUSY') throw error;
    }
  }
});

test('owner-confirmed Oborot publication is created once without unrelated workflow facts', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-oborot-publication-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const first = updatePublicationMemory(databasePath, oborotInternetShopPublicationUpdate);
    const second = updatePublicationMemory(databasePath, oborotInternetShopPublicationUpdate);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    const current = readOnly.prepare(`SELECT title,content,data_json,status FROM memory_candidates
      WHERE semantic_key='publication.oborot_internet_shop_daily_limit_2026_09_01'`).get();
    const data = JSON.parse(current.data_json);
    assert.equal(current.status, 'approved');
    assert.equal(current.title, 'Статья MetricHit опубликована на Oborot.ru');
    assert.match(current.content, /01\.09\.2026/);
    assert.equal(data.publication_status, 'owner_confirmed');
    assert.equal(data.canonical_url, oborotInternetShopPublicationUpdate.canonicalUrl);
    assert.equal(data.verified_facts.article_title, oborotInternetShopPublicationUpdate.verifiedFacts.article_title);
    assert.deepEqual(data.supersedes_semantic_revisions, []);
    assert.equal(/Chrome|расширен|автоматизац|изображен/iu.test(current.content), false);
    readOnly.close();
  } finally {
    try { rmSync(directory, { recursive: true, force: true, maxRetries: 2, retryDelay: 25 }); }
    catch (error) { if (error?.code !== 'EBUSY') throw error; }
  }
});

test('owner-confirmed TenChat publication records the exact cover asset', () => {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-tenchat-publication-'));
  const databasePath = join(directory, 'memory.sqlite');
  try {
    execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
    const first = updatePublicationMemory(databasePath, tenchatInternetShopPublicationUpdate);
    const second = updatePublicationMemory(databasePath, tenchatInternetShopPublicationUpdate);
    assert.deepEqual(first.created, { sources: 1, documents: 1, versions: 1, candidates: 1 });
    assert.deepEqual(second.created, { sources: 0, documents: 0, versions: 0, candidates: 0 });
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    const current = readOnly.prepare(`SELECT data_json,status FROM memory_candidates
      WHERE semantic_key='publication.tenchat_internet_shop_start_category_2026_09_01'`).get();
    const data = JSON.parse(current.data_json);
    assert.equal(current.status, 'approved');
    assert.equal(data.publication_status, 'owner_confirmed');
    assert.equal(data.canonical_url, tenchatInternetShopPublicationUpdate.canonicalUrl);
    assert.equal(data.verified_facts.local_draft_path, 'work/social/tenchat/drafts/2026-09-01-oborot-nakrutka-pf-internet-shop.md');
    assert.equal(data.verified_facts.cover_asset_sha256, '2d4ac5caf492867520e461b3f2d574280302ee6b134e48aeae38582a30bc51ff');
    assert.deepEqual(data.verified_facts.cover_asset_dimensions, { width: 1536, height: 1024 });
    assert.equal(data.verified_facts.independent_fetch, 'not_performed');
    readOnly.close();
  } finally {
    try { rmSync(directory, { recursive: true, force: true, maxRetries: 2, retryDelay: 25 }); }
    catch (error) { if (error?.code !== 'EBUSY') throw error; }
  }
});
