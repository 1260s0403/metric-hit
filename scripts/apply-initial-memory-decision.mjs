import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/initial-memory-approval-2026-08-13.md';
const reviewedAt = '2026-08-13T00:00:00.000Z';
const owner = 'owner';

const approvedInitialKeys = [
  'product.project_configuration',
  'billing.click_based_prepayment',
  'pricing.current_tiers',
  'bonus.new_user_test_clicks',
  'resource.landing',
  'resource.account',
  'channel.telegram_public',
  'channel.telegram_support',
  'naming.landing_vs_account',
  'editorial.no_guarantees',
  'editorial.no_fabricated_metrics',
  'editorial.protect_client_identifiers',
  'editorial.no_antifraud_details',
  'editorial.separate_evidence_and_hypotheses',
  'editorial.one_intent_one_cta',
  'editorial.publication_requires_confirmation',
  'editorial.telegram_short_professional',
  'editorial.value_before_product',
  'editorial.longform_separate_workstream',
  'publication.dzen_articles_2026_08_13',
  'publication.sostav_first_article',
  'publication.telegram_confirmed_set',
  'publication.vk_welcome_post',
];

const rejectionReasons = new Map([
  [
    'analytics.utm_registration_click',
    'Ошибочно представлен как текущее состояние. Функциональность не реализована; перенесена в план работ.',
  ],
  [
    'publication.avito_saint_petersburg',
    'Неполный факт: владелец подтвердил пять активных объявлений Avito в пяти городах.',
  ],
]);

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-memory-decision:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

function applyOutcome(database, semanticKey, status, reviewNote) {
  const candidate = database.prepare(
    'SELECT * FROM memory_candidates WHERE semantic_key = ?',
  ).get(semanticKey);
  if (!candidate) throw new Error(`Initial candidate not found: ${semanticKey}`);

  if (candidate.status === 'pending') {
    database.prepare(`
      UPDATE memory_candidates
      SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?,
          updated_at = ?, version = version + 1
      WHERE id = ?
    `).run(status, owner, reviewedAt, reviewNote, reviewedAt, candidate.id);
  }

  const terminal = database.prepare(
    'SELECT * FROM memory_candidates WHERE id = ?',
  ).get(candidate.id);
  assertFields(terminal, {
    status,
    reviewed_by: owner,
    reviewed_at: reviewedAt,
    review_note: reviewNote,
  }, `candidate ${semanticKey}`);
}

export function applyInitialMemoryDecision(databasePath = defaultDatabasePath) {
  const absoluteDecisionPath = join(repositoryRoot, decisionPath);
  const bytes = readFileSync(absoluteDecisionPath);
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Decision file contains U+FFFD');
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256,
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-13',
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const taskId = stableUuid('task:analytics.utm_registration_click');
  const avitoCandidateId = stableUuid('candidate:publication.avito_active_ads_2026_08_13');

  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, tasks: 0 };

  try {
    const sourceResult = database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-13', 'internal')
    `).run(
      sourceId,
      'Решение владельца по первоначальным кандидатам памяти от 13.08.2026',
      `Repository file: ${decisionPath}`,
      metadata,
      owner,
    );
    created.sources += Number(sourceResult.changes);
    assertFields(database.prepare('SELECT * FROM sources WHERE id = ?').get(sourceId), {
      data_json: metadata,
      author: owner,
      valid_at: '2026-08-13',
    }, 'owner decision source');

    const documentResult = database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-13', 'internal', 1)
    `).run(
      documentId,
      'Решение владельца по первоначальным кандидатам памяти от 13.08.2026',
      content,
      metadata,
      sourceId,
      owner,
    );
    created.documents += Number(documentResult.changes);
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      content,
      data_json: metadata,
      source_id: sourceId,
      version: 1,
    }, 'owner decision document');

    const versionResult = database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status,
         source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-13', 'internal', 1)
    `).run(
      versionId,
      documentId,
      'Решение владельца по первоначальным кандидатам памяти от 13.08.2026',
      content,
      metadata,
      sourceId,
      owner,
    );
    created.versions += Number(versionResult.changes);
    assertFields(database.prepare('SELECT * FROM document_versions WHERE id = ?').get(versionId), {
      document_id: documentId,
      content,
      data_json: metadata,
      version: 1,
    }, 'owner decision document version');

    for (const semanticKey of approvedInitialKeys) {
      applyOutcome(database, semanticKey, 'approved', 'Одобрено прямым решением владельца MetricHit от 13.08.2026.');
    }
    for (const [semanticKey, reason] of rejectionReasons) {
      applyOutcome(database, semanticKey, 'rejected', reason);
    }

    const taskData = JSON.stringify({
      requirements: [
        'track_incoming_utm_on_landing',
        'implement_registration_click',
        'do_not_modify_mtrhit_ru',
      ],
      due_at: 'unknown',
      origin: 'owner_decision_2026_08_13',
    });
    const taskContent = 'Настроить учёт входящих UTM на лендинге и реализовать цель registration_click, не изменяя mtrhit.ru. Срок владельцем не назначен.';
    const taskResult = database.prepare(`
      INSERT OR IGNORE INTO tasks
        (id, type, title, content, data_json, status, source_id,
         author, valid_at, access_level, version)
      VALUES (?, 'analytics_implementation', ?, ?, ?, 'pending', ?, ?, '2026-08-13', 'internal', 1)
    `).run(
      taskId,
      'Настроить UTM и registration_click без изменения mtrhit.ru',
      taskContent,
      taskData,
      sourceId,
      owner,
    );
    created.tasks += Number(taskResult.changes);
    assertFields(database.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId), {
      content: taskContent,
      data_json: taskData,
      status: 'pending',
      source_id: sourceId,
    }, 'analytics task');

    const avitoContent = 'Подтверждены активные объявления для Новосибирска, Перми, Екатеринбурга, Санкт-Петербурга и Москвы.';
    const avitoData = JSON.stringify({
      platform: 'avito',
      cities: ['Новосибирск', 'Пермь', 'Екатеринбург', 'Санкт-Петербург', 'Москва'],
      active_ads: 5,
      prices_included: false,
      urls: 'unconfirmed_and_excluded',
      evidence: {
        path: decisionPath,
        section: '§ Уточнение по Avito',
      },
      date_marker: '2026-08-13',
      authority: 'direct_owner_confirmation',
    });
    const candidateResult = database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status,
         source_id, author, valid_at, access_level, version)
      VALUES (?, 'publication_state', 'publication.avito_active_ads_2026_08_13',
              'Пять активных объявлений Avito', ?, ?, 'pending', ?, ?,
              '2026-08-13', 'internal', 1)
    `).run(avitoCandidateId, avitoContent, avitoData, sourceId, owner);
    created.candidates += Number(candidateResult.changes);
    applyOutcome(
      database,
      'publication.avito_active_ads_2026_08_13',
      'approved',
      'Одобрено при создании на основании прямого решения владельца MetricHit от 13.08.2026.',
    );
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(avitoCandidateId), {
      type: 'publication_state',
      semantic_key: 'publication.avito_active_ads_2026_08_13',
      title: 'Пять активных объявлений Avito',
      content: avitoContent,
      data_json: avitoData,
      source_id: sourceId,
      status: 'approved',
    }, 'corrected Avito candidate');

    database.exec('COMMIT');
    const counts = Object.fromEntries(database.prepare(`
      SELECT status, count(*) AS count FROM memory_candidates GROUP BY status ORDER BY status
    `).all().map(({ status, count }) => [status, count]));
    return {
      databasePath,
      created,
      counts,
      source: { id: sourceId, path: decisionPath, sha256 },
      document: { id: documentId, versionId, version: 1 },
      taskId,
      avitoCandidateId,
    };
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
  const databasePath = process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath;
  const result = applyInitialMemoryDecision(databasePath);
  console.log(`Applied owner decision to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
  console.log(`Candidate counts: ${JSON.stringify(result.counts)}`);
}

