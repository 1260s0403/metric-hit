import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/product-positioning-and-editorial-directness-2026-08-14.md';
const owner = 'owner';
const reviewedAt = '2026-08-14T00:00:00.000Z';
const supersededRules = [
  'editorial.no_guarantees',
  'editorial.no_fabricated_metrics',
  'editorial.no_antifraud_details',
];

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-product-policy:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

function approveCandidate(database, candidateId, reviewNote) {
  const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId);
  if (!candidate) throw new Error(`Missing candidate: ${candidateId}`);
  if (candidate.status === 'pending') {
    database.prepare(`
      UPDATE memory_candidates
      SET status = 'approved', reviewed_by = ?, reviewed_at = ?, review_note = ?,
          updated_at = ?, version = version + 1
      WHERE id = ?
    `).run(owner, reviewedAt, reviewNote, reviewedAt, candidateId);
  }
}

export function applyProductPositioningAndEditorialDirectness(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (content.includes('\uFFFD')) throw new Error('Decision file contains U+FFFD');
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
  const decisionId = stableUuid('decision:content.editorial_directness_policy');
  const positioningId = stableUuid('candidate:product.positioning');
  const policyId = stableUuid('candidate:content.editorial_directness_policy');
  const positioningTitle = 'Назначение MetricHit';
  const positioningContent = 'MetricHit — сервис накрутки и улучшения поведенческих факторов (ПФ) для продвижения сайтов в поисковой выдаче Яндекса. Пользователь настраивает сайт, регион, поисковые запросы, дневные лимиты и расписание, а затем контролирует выполненные клики, расходы и изменение позиций в личном кабинете. MetricHit используется как инструмент усиления подготовленного сайта и не является гарантией роста позиций или заменой технического SEO, релевантности страниц и коммерческой проработки.';
  const positioningData = JSON.stringify({
    purpose: 'behavioral_factor_manipulation_and_improvement_for_yandex_search_promotion',
    terms: ['накрутка ПФ', 'улучшение ПФ', 'продвижение сайтов в Яндексе'],
    project_configuration_key: 'product.project_configuration',
    evidence: { path: decisionPath },
  });
  const policyTitle = 'Прямая редакционная политика MetricHit';
  const policyContent = 'MetricHit может прямо описывать накрутку и улучшение ПФ для продвижения сайтов в Яндексе. Прямая, включая жёсткую и категоричную, подача разрешена по умолчанию для Telegram, VK и Дзена, а для остальных площадок адаптируется под реальные требования и риск модерации. Неподтверждённые оценки, демонстрационные данные, категоричные тезисы и обсуждение антифрода не блокируются автоматически; решение о допустимости конкретной формулировки принимает владелец. Нельзя создавать заведомо ложное утверждение специально для намеренного введения потенциального клиента в заблуждение ради продажи. Предыдущие общие запреты на гарантии, неподтверждённые показатели и антифрод-детали заменены в противоречащей части.';
  const policyData = JSON.stringify({
    direct_terms_allowed: ['накрутка ПФ', 'накрутка поведенческих факторов', 'улучшение поведенческих факторов', 'продвижение сайтов в Яндексе', 'поведенческое продвижение'],
    default_direct_channels: ['telegram', 'vk', 'dzen'],
    platform_adaptation_required: ['sostav_sblogs', 'oborot_ru', 'timeweb', 'workspace', 'other_external_resources'],
    owner_is_final_reviewer: true,
    automatic_content_blocks: false,
    antifraud_topic_allowed_with_concrete_risk_review: true,
    only_general_factual_boundary: 'no_deliberate_known_falsehood_to_mislead_potential_clients_for_sale',
    supersedes_editorial_rules: supersededRules,
    historical_materials: { posts: ['8', '9', '10'], automatically_prohibited: false, landing_demo_table_automatically_prohibited: false },
    evidence: { path: decisionPath },
  });

  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  const created = { sources: 0, documents: 0, versions: 0, decisions: 0, candidates: 0, conflictsResolved: 0 };
  try {
    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-14', 'internal')
    `).run(sourceId, policyTitle, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(documentId, policyTitle, content, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(versionId, documentId, policyTitle, content, metadata, sourceId, owner).changes);
    created.decisions += Number(database.prepare(`
      INSERT OR IGNORE INTO decisions
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'editorial_policy', ?, ?, ?, 'active', ?, ?, '2026-08-14', 'internal', 1)
    `).run(decisionId, policyTitle, policyContent, policyData, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'product_fact', 'product.positioning', ?, ?, ?, 'pending', ?, ?, '2026-08-14', 'internal', 1)
    `).run(positioningId, positioningTitle, positioningContent, positioningData, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'decision', 'content.editorial_directness_policy', ?, ?, ?, 'pending', ?, ?, '2026-08-14', 'internal', 1)
    `).run(policyId, policyTitle, policyContent, policyData, sourceId, owner).changes);

    const reviewNote = 'Одобрено на основании прямого решения владельца MetricHit от 14.08.2026.';
    approveCandidate(database, positioningId, reviewNote);
    approveCandidate(database, policyId, reviewNote);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(positioningId), {
      type: 'product_fact', semantic_key: 'product.positioning', title: positioningTitle,
      content: positioningContent, data_json: positioningData, source_id: sourceId,
      status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'product positioning candidate');
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(policyId), {
      type: 'decision', semantic_key: 'content.editorial_directness_policy', title: policyTitle,
      content: policyContent, data_json: policyData, source_id: sourceId,
      status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'editorial policy candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      content, data_json: metadata, source_id: sourceId, version: 1,
    }, 'editorial policy document');
    assertFields(database.prepare('SELECT * FROM decisions WHERE id = ?').get(decisionId), {
      content: policyContent, data_json: policyData, source_id: sourceId, status: 'active', version: 1,
    }, 'editorial policy decision');

    const conflicts = database.prepare(`
      SELECT id FROM memory_conflicts
      WHERE status = 'open' AND existing_memory_item_id IN (
        SELECT id FROM memory_items WHERE semantic_key IN (${supersededRules.map(() => '?').join(', ')})
      )
    `).all(...supersededRules);
    for (const { id } of conflicts) {
      created.conflictsResolved += Number(database.prepare(`
        UPDATE memory_conflicts
        SET status = 'resolved', resolution = ?, updated_at = ?, version = version + 1
        WHERE id = ?
      `).run('Разрешено прямым решением владельца от 14.08.2026: действует content.editorial_directness_policy.', reviewedAt, id).changes);
    }
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, decisionId, positioningId, policyId };
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
  const result = applyProductPositioningAndEditorialDirectness(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
  console.log(`Applied product positioning and editorial policy to: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
}
