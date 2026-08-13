import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

import { initializeDatabase } from './init-memory.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const author = 'MetricHit Automation';

const sourceDefinitions = [
  {
    key: 'articles',
    path: 'knowledge/chat-summaries/metrichit-articles-summary.md',
    title: 'MetricHit — статьи и поисковое продвижение: резюме чата',
  },
  {
    key: 'landing',
    path: 'knowledge/chat-summaries/metricHit-landing-summary.md',
    title: 'MetricHit Landing — резюме чата',
  },
  {
    key: 'social',
    path: 'knowledge/chat-summaries/metrichit-social-summary.md',
    title: 'MetricHit Social — резюме чата',
  },
];

const candidateDefinitions = [
  ['product_fact', 'product.project_configuration', 'Настройка проекта MetricHit', 'Пользователь создаёт проект, задаёт сайт, регион, запросы, дневные лимиты и расписание; клики, расходы и позиции контролируются в личном кабинете.', 'articles', '§ 4. Архитектура, технологии, файлы и внешние интеграции', '53', 'unknown', { capabilities: ['site', 'region', 'queries', 'daily_limits', 'schedule', 'clicks', 'costs', 'positions'] }],
  ['commercial_terms', 'billing.click_based_prepayment', 'Модель оплаты MetricHit', 'Используется предоплата и тарификация по фактически выполненным кликам без фиксированной абонентской платы; неиспользованный остаток не сгорает.', 'articles', '§ 4. Архитектура, технологии, файлы и внешние интеграции', '54', 'unknown', { prepayment: true, billing_unit: 'completed_click', subscription_fee: false, balance_expires: false }],
  ['commercial_terms', 'pricing.current_tiers', 'Действующая тарифная сетка', 'Цена клика зависит от суммы пополнения: от 1 000 ₽ — 1,50 ₽; от 15 000 ₽ — 1,20 ₽; от 50 000 ₽ — 0,90 ₽; от 100 000 ₽ — 0,50 ₽; от 150 000 ₽ — 0,35 ₽; от 250 000 ₽ — 0,20 ₽; от 500 000 ₽ — индивидуальные условия.', 'social', '§ 6 → Коммерческие настройки', '346-354', '2026-08-13', { currency: 'RUB', tiers: [[1000, 1.5], [15000, 1.2], [50000, 0.9], [100000, 0.5], [150000, 0.35], [250000, 0.2], [500000, null]], unit: 'RUB_per_click' }],
  ['commercial_terms', 'bonus.new_user_test_clicks', 'Бонус новому пользователю', 'Новый пользователь может один раз получить 1 000 тестовых кликов после регистрации и обращения в Telegram-поддержку с логином; начисление не автоматическое и не требует пополнения.', 'social', '§ 6 → Коммерческие настройки', '334-339', '2026-08-13', { clicks: 1000, once: true, requires_registration: true, requires_support_request: true, automatic: false, requires_deposit: false }],
  ['official_resource', 'resource.landing', 'Официальный лендинг MetricHit', 'Официальный лендинг MetricHit расположен по адресу https://go.mtrhit.ru/.', 'social', '§ 6 → Актуальные адреса', '318-320', '2026-08-13', { url: 'https://go.mtrhit.ru/', role: 'landing' }],
  ['official_resource', 'resource.account', 'Регистрация и личный кабинет MetricHit', 'Регистрация и личный кабинет MetricHit расположены по адресу https://mtrhit.ru/.', 'social', '§ 6 → Актуальные адреса', '318-321', '2026-08-13', { url: 'https://mtrhit.ru/', role: 'registration_and_account' }],
  ['official_channel', 'channel.telegram_public', 'Официальный Telegram-канал MetricHit', 'Официальный публичный Telegram-канал MetricHit: https://t.me/mtr_hit.', 'social', '§ 6 → Актуальные адреса', '318-322', '2026-08-13', { platform: 'telegram', url: 'https://t.me/mtr_hit', role: 'public_channel' }],
  ['official_channel', 'channel.telegram_support', 'Telegram-поддержка MetricHit', 'Официальный контакт Telegram-поддержки MetricHit: https://t.me/Metric_Hit.', 'social', '§ 6 → Актуальные адреса', '318-323', '2026-08-13', { platform: 'telegram', url: 'https://t.me/Metric_Hit', handle: '@Metric_Hit', role: 'support' }],
  ['decision', 'naming.landing_vs_account', 'Разделять лендинг и личный кабинет', 'go.mtrhit.ru следует называть сайтом или лендингом; личный кабинет и регистрация находятся на mtrhit.ru.', 'social', '§ 7. Принятые решения и причины', '388-391', '2026-08-13', { landing_domain: 'go.mtrhit.ru', account_domain: 'mtrhit.ru' }],
  ['analytics_decision', 'analytics.utm_registration_click', 'Актуальная схема аналитики: UTM и registration_click', 'Актуальный вариант — отслеживать источники входящими UTM-метками и, при подтверждении владельца, использовать только цель registration_click; mtrhit.ru не изменять, завершённую регистрацию не имитировать.', 'landing', '§ 8. Незавершённые задачи', '124-125', '2026-08-12', { attribution: 'incoming_utm', goal: 'registration_click', modify_account_domain: false, registration_complete: false, confirmation_required: true }],
  ['editorial_rule', 'editorial.no_guarantees', 'Не давать недоказуемых гарантий', 'Не обещать гарантированный ТОП, полную безопасность, отсутствие фильтров или универсальный быстрый результат.', 'articles', '§ 7. Действующие правила и ограничения', '101', 'unknown', { prohibited_claims: ['guaranteed_top', 'complete_safety', 'no_filters', 'universal_fast_result'] }],
  ['editorial_rule', 'editorial.no_fabricated_metrics', 'Не выдумывать показатели и результаты', 'Не публиковать выдуманные показатели, отзывы, сроки, бюджеты, клики, заявки, выручку или окупаемость; клиентские цифры на скриншотах нельзя улучшать.', 'social', '§ 8. Действующие правила и ограничения', '420-423', '2026-08-13', { fabricated_data_prohibited: true, screenshot_number_manipulation_prohibited: true }],
  ['editorial_rule', 'editorial.protect_client_identifiers', 'Скрывать клиентские идентификаторы', 'Клиентские домены, запросы и иные идентифицирующие данные следует скрывать без явного разрешения на публикацию.', 'social', '§ 8. Действующие правила и ограничения', '430-433', '2026-08-13', { redact_without_permission: ['domains', 'queries', 'identifiers'] }],
  ['editorial_rule', 'editorial.no_antifraud_details', 'Не раскрывать детали обхода защит', 'Не раскрывать сведения, которые могут помогать обходить защитные или антифрод-системы либо компрометировать инфраструктуру.', 'social', '§ 8. Действующие правила и ограничения', '425-428', '2026-08-13', { prohibited: ['anti_fraud_bypass_details', 'infrastructure_compromise_details'] }],
  ['editorial_rule', 'editorial.separate_evidence_and_hypotheses', 'Разделять факты и гипотезы', 'В материалах необходимо разделять официальные сведения, наблюдения команды и авторские гипотезы.', 'articles', '§ 7. Действующие правила и ограничения', '104', 'unknown', { categories: ['official_information', 'team_observations', 'author_hypotheses'] }],
  ['editorial_rule', 'editorial.one_intent_one_cta', 'Один материал — один интент и CTA', 'Одна статья должна иметь один основной интент и один CTA; материалы для разных площадок должны быть оригинальными, а не механическими копиями.', 'articles', '§ 7. Действующие правила и ограничения', '105', 'unknown', { primary_intents: 1, primary_ctas: 1, cross_platform_originality_required: true }],
  ['editorial_rule', 'editorial.publication_requires_confirmation', 'Публикация требует подтверждения', 'Статью нельзя считать опубликованной без прямого подтверждения владельца или проверяемой ссылки.', 'articles', '§ 7. Действующие правила и ограничения', '108', '2026-08-13', { accepted_evidence: ['owner_confirmation', 'verifiable_url'] }],
  ['editorial_rule', 'editorial.telegram_short_professional', 'Формат Telegram: кратко и профессионально', 'Материалы Telegram должны быть короткими, профессиональными и информативными; длинный формат допустим только когда он оправдан темой.', 'social', '§ 8. Действующие правила и ограничения', '400-403', '2026-08-13', { channel: 'telegram', style: ['concise', 'professional', 'informative'] }],
  ['editorial_rule', 'editorial.value_before_product', 'Практическая польза перед продуктом', 'Контент должен сначала приносить практическую пользу и только затем показывать продукт.', 'social', '§ 8. Действующие правила и ограничения', '405-408', '2026-08-13', { priority: ['practical_value', 'product'] }],
  ['decision', 'editorial.longform_separate_workstream', 'Длинные статьи ведутся отдельно от SMM', 'Полноформатные статьи вынесены в отдельный рабочий контур, чтобы разделить оперативный SMM и редакционную работу.', 'social', '§ 7. Принятые решения и причины', '383-386', '2026-08-13', { social_scope: 'short_form', longform_scope: 'separate_workstream' }],
  ['publication_state', 'publication.dzen_articles_2026_08_13', 'Три подтверждённые статьи в Дзене', 'На 13 августа 2026 года подтверждены три опубликованные статьи MetricHit в Дзене: о поведенческих факторах, популярных запросах и распределении запросов по страницам.', 'articles', '§ 3.3. Реестр статей', '44-48', '2026-08-13', { platform: 'dzen', publications: [{ date: '2026-08-11', url: 'https://dzen.ru/a/ansfBOH4cwwyLWEA' }, { date: '2026-08-12', url: 'https://dzen.ru/a/antQlAKap3R6bj1V' }, { date: '2026-08-13', url: 'https://dzen.ru/a/an2_q3WK_zXvqrLz' }] }],
  ['publication_state', 'publication.sostav_first_article', 'Первая статья MetricHit опубликована в Sostav', 'Статья «SEO вывело сайт в ТОП, а продажи не выросли: где ломается воронка» опубликована в Sostav/SBlogs 12 августа 2026 года.', 'articles', '§ 3.3. Реестр статей', '44-49', '2026-08-12', { platform: 'sostav_sblogs', url: 'https://www.sostav.ru/blogs/293151/101025', published: true }],
  ['publication_state', 'publication.telegram_confirmed_set', 'Подтверждённые публикации Telegram', 'В Telegram-канале подтверждены семь основных постов со ссылками, навигационный закреп и короткий материал о трёх обновлениях Яндекса.', 'social', '§ 4.1. Telegram — опубликованные', '185-202', '2026-08-13', { platform: 'telegram', linked_post_ids: [6, 7, 8, 9, 10, 11, 13], navigation_pinned: true, yandex_updates_post: true }],
  ['publication_state', 'publication.vk_welcome_post', 'Приветственный пост VK опубликован и закреплён', 'В сообществе VK опубликован и закреплён приветственный пост о MetricHit.', 'social', '§ 4.4. VK — опубликованные', '224-228', '2026-08-13', { platform: 'vk', post: 'welcome', published: true, pinned: true, public_url: 'unknown' }],
  ['publication_state', 'publication.avito_saint_petersburg', 'Объявление Avito в Санкт-Петербурге опубликовано', 'Подтверждена публикация второго объявления MetricHit на Avito для Санкт-Петербурга; публичная ссылка не зафиксирована.', 'social', '§ 3 → Avito', '166-176', '2026-08-13', { platform: 'avito', city: 'Санкт-Петербург', published: true, public_url: 'unknown' }],
];

const secretPatterns = [
  /\b(?:api[_ -]?key|secret|password|passwd|bearer|authorization)\b\s*[:=]/iu,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/u,
  /\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{16,}\b/u,
];

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-memory-import:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function loadSources() {
  return sourceDefinitions.map((definition) => {
    const absolutePath = join(repositoryRoot, definition.path);
    const bytes = readFileSync(absolutePath);
    const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    if (content.includes('\uFFFD')) throw new Error(`Replacement character found in ${definition.path}`);
    for (const pattern of secretPatterns) {
      if (pattern.test(content)) throw new Error(`Potential secret found in ${definition.path}`);
    }
    return {
      ...definition,
      content,
      bytes: statSync(absolutePath).size,
      sha256: createHash('sha256').update(bytes).digest('hex'),
      sourceId: stableUuid(`source:${definition.path}`),
      documentId: stableUuid(`document:${definition.path}`),
      versionId: stableUuid(`document-version:${definition.path}:1`),
    };
  });
}

function assertExisting(database, table, id, expected) {
  const row = database.prepare(`SELECT * FROM ${table} WHERE id = ?`).get(id);
  if (!row) throw new Error(`${table} row was not created: ${id}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${table}.${column} differs for ${id}`);
  }
}

export function importChatSummaries(databasePath = defaultDatabasePath) {
  initializeDatabase(databasePath);
  const sources = loadSources();
  const sourceByKey = new Map(sources.map((source) => [source.key, source]));
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  const before = {
    sources: database.prepare('SELECT count(*) AS count FROM sources').get().count,
    documents: database.prepare('SELECT count(*) AS count FROM documents').get().count,
    versions: database.prepare('SELECT count(*) AS count FROM document_versions').get().count,
    candidates: database.prepare('SELECT count(*) AS count FROM memory_candidates').get().count,
  };

  try {
    for (const source of sources) {
      const metadata = JSON.stringify({ path: source.path, bytes: source.bytes, sha256: source.sha256, encoding: 'utf-8', secret_scan: 'passed' });
      database.prepare(`
        INSERT OR IGNORE INTO sources
          (id, type, title, content, data_json, status, author, access_level)
        VALUES (?, 'chat_summary_file', ?, ?, ?, 'active', ?, 'internal')
      `).run(source.sourceId, source.title, `Repository file: ${source.path}`, metadata, author);
      assertExisting(database, 'sources', source.sourceId, { title: source.title, data_json: metadata });

      database.prepare(`
        INSERT OR IGNORE INTO documents
          (id, type, title, content, data_json, status, source_id, author, access_level, version)
        VALUES (?, 'chat_summary', ?, ?, ?, 'active', ?, ?, 'internal', 1)
      `).run(source.documentId, source.title, source.content, metadata, source.sourceId, author);
      assertExisting(database, 'documents', source.documentId, { content: source.content, data_json: metadata, source_id: source.sourceId, version: 1 });

      database.prepare(`
        INSERT OR IGNORE INTO document_versions
          (id, document_id, type, title, content, data_json, status, source_id, author, access_level, version)
        VALUES (?, ?, 'chat_summary', ?, ?, ?, 'active', ?, ?, 'internal', 1)
      `).run(source.versionId, source.documentId, source.title, source.content, metadata, source.sourceId, author);
      assertExisting(database, 'document_versions', source.versionId, { document_id: source.documentId, content: source.content, data_json: metadata, version: 1 });
    }

    for (const [type, semanticKey, title, content, sourceKey, section, lines, dateMarker, data] of candidateDefinitions) {
      const source = sourceByKey.get(sourceKey);
      const id = stableUuid(`candidate:${semanticKey}`);
      const dataJson = JSON.stringify({
        ...data,
        evidence: { path: source.path, section, lines },
        date_marker: dateMarker,
        import_status: 'pending_owner_review',
      });
      const validAt = dateMarker === 'unknown' ? null : dateMarker;
      database.prepare(`
        INSERT OR IGNORE INTO memory_candidates
          (id, type, semantic_key, title, content, data_json, status,
           source_id, author, valid_at, access_level, version)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, 'internal', 1)
      `).run(id, type, semanticKey, title, content, dataJson, source.sourceId, author, validAt);
      assertExisting(database, 'memory_candidates', id, {
        type, semantic_key: semanticKey, title, content, data_json: dataJson,
        status: 'pending', source_id: source.sourceId, author,
        valid_at: validAt, access_level: 'internal', version: 1,
      });
    }

    database.exec('COMMIT');
    const after = {
      sources: database.prepare('SELECT count(*) AS count FROM sources').get().count,
      documents: database.prepare('SELECT count(*) AS count FROM documents').get().count,
      versions: database.prepare('SELECT count(*) AS count FROM document_versions').get().count,
      candidates: database.prepare('SELECT count(*) AS count FROM memory_candidates').get().count,
    };
    return {
      databasePath,
      registeredSources: sources.map(({ sourceId: id, title, path, bytes, sha256 }) => ({ id, title, path, bytes, sha256 })),
      registeredDocuments: sources.map(({ documentId: id, versionId, title, path }) => ({ id, versionId, title, path })),
      candidates: candidateDefinitions.map(([type, semanticKey, title, content]) => ({ type, semanticKey, title, content })),
      created: Object.fromEntries(Object.keys(after).map((key) => [key, after[key] - before[key]])),
      totals: after,
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
  const result = importChatSummaries(databasePath);
  console.log(`Imported chat summaries into: ${result.databasePath}`);
  console.log(`Created: ${JSON.stringify(result.created)}`);
  console.log(`Totals: ${JSON.stringify(result.totals)}`);
}

