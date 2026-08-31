import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import {
  SEMANTIC_CORE_REFERENCE_KEY, SCOPE_IDS, closeContextPack, compileContextPack,
  compileDeterministicContext, createTaskScope, loadReferencedMemory, registerScopedRecord,
  resolveScopedMemory, routeTask, supersedeScopedRecord,
} from '../scripts/structured-memory.mjs';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-structured-memory-'));
  const databasePath = join(directory, 'memory.sqlite');
  execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
  const database = new DatabaseSync(databasePath);
  const fixtureSourceId = '10000000-0000-4000-a000-000000000001';
  const fixtureArticlePolicyId = '10000000-0000-4000-a000-000000000002';
  const fixtureTenChatPolicyId = '10000000-0000-4000-a000-000000000003';
  const fixtureTelegramPolicyId = '10000000-0000-4000-a000-000000000004';
  const fixturePfPolicyId = '10000000-0000-4000-a000-000000000005';
  database.prepare(`INSERT INTO sources(id,type,title,content,status,author,created_at,updated_at,version)
    VALUES (?,'test','Fixture editorial source','Fixture source','active','owner',?,?,1)`)
    .run(fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixtureArticlePolicyId, 'editorial_rule', 'content.editorial_article_preparation_policy',
    'Правила подготовки статей MetricHit',
    'В статье четыре естественные ссылки на https://go.mtrhit.ru/: в начале, две внутри и в финале/CTA. Статья оригинальна.',
    JSON.stringify({ applies_to: ['articles'], landing: 'https://go.mtrhit.ru/',
      landing_link_distribution: ['beginning', 'body_1', 'body_2', 'final_cta'] }),
    fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixtureTenChatPolicyId, 'editorial_rule', 'editorial.tenchat_format_and_search_policy',
    'Редакционное правило TenChat: объём и поисковая подача',
    'TenChat: максимум 7 000 знаков, цель 4 000–5 500, один интент, естественный ключ в заголовке и начале, 2–4 ссылки без спама.',
    JSON.stringify({ platform: 'TenChat', maximum_characters: 7000, target_characters: { minimum: 4000, maximum: 5500 },
      primary_search_intents: 1, primary_keyword_placement: ['title', 'opening'], prohibited: ['link_spam'] }),
    fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixtureTelegramPolicyId, 'editorial_rule', 'editorial.telegram_short_professional',
    'Формат Telegram', 'Только Telegram.', JSON.stringify({ channel: 'telegram' }),
    fixtureSourceId, '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`INSERT INTO memory_candidates
    (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,version)
    VALUES (?,?,?,?,?,?,'pending',?,'owner',?,?,1)`).run(
    fixturePfPolicyId, 'editorial_rule', 'content.public_pf_positive_framing',
    'Позитивная подача ПФ', 'Публичный материал о ПФ раскрывает практическую пользу.',
    JSON.stringify({ applies_to: ['public_articles'] }), fixtureSourceId,
    '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?
    WHERE id IN (?,?,?,?)`)
    .run('2026-08-31T00:00:00.000Z', fixtureArticlePolicyId, fixtureTenChatPolicyId, fixtureTelegramPolicyId, fixturePfPolicyId);
  database.prepare(`INSERT INTO tasks
    (id,type,title,content,data_json,status,author,created_at,updated_at,version)
    VALUES (?,'knowledge_task',?,?,?,'pending','owner',?,?,1)`).run(
    '10000000-0000-4000-a000-000000000006', 'Статьи: ключевые ВЧ-запросы в главном заголовке',
    'В главном заголовке H1 обязательно использовать «накрутка ПФ» или «накрутка поведенческого фактора».',
    JSON.stringify({ project_id: '00000000-0000-4000-a000-000000000102' }),
    '2026-08-31T00:00:00.000Z', '2026-08-31T00:00:00.000Z');
  database.close();
  return { directory, databasePath };
}

function tenChatContentQa() {
  const digest = 'a'.repeat(64);
  return {
    checks: [
      { id: 'landing_link_distribution', performed: true, passed: true, result: '4 landing links: beginning=1, body=2, final CTA=1.',
        evidence: { url: 'https://go.mtrhit.ru/', exact_count: 4,
          positions: ['beginning', 'body_1', 'body_2', 'final_cta'], natural_anchors: true, link_spam: false } },
      { id: 'originality_source_overlap', performed: true, passed: true,
        result: 'Local deterministic comparison: maximum normalized source overlap 8.5%; no template match.',
        evidence: { method: 'local_deterministic_source_overlap', content_sha256: digest,
          compared_sources: [{ path: 'work/social/tenchat/reference.md', sha256: 'b'.repeat(64), overlap_percent: 8.5 }],
          max_overlap_percent: 8.5, template_match: false } },
      { id: 'h1_high_frequency_query', performed: true, passed: true,
        result: 'H1 contains the approved high-frequency query “накрутка ПФ”.',
        evidence: { heading: 'Накрутка ПФ в Яндексе', matched_query: 'накрутка ПФ' } },
      { id: 'tenchat_character_count', performed: true, passed: true,
        result: '4,812 characters including spaces and punctuation; within 4,000–5,500 target and below 7,000 maximum.',
        evidence: { character_count: 4812, maximum: 7000, target_minimum: 4000, target_maximum: 5500, within_target: true } },
      { id: 'single_search_intent', performed: true, passed: true, result: 'Exactly one primary intent: controlled PF promotion in Yandex.',
        evidence: { intent_count: 1, primary_intent: 'controlled PF promotion in Yandex' } },
      { id: 'natural_primary_keyword', performed: true, passed: true,
        result: 'Primary keyword appears once in H1 and naturally in the opening paragraph.',
        evidence: { primary_keyword: 'накрутка ПФ', in_title: true, in_opening: true, natural: true } },
      { id: 'link_count_and_spam', performed: true, passed: true, result: '4 relevant links; no repeated-anchor or link-spam pattern.',
        evidence: { link_count: 4, minimum: 2, maximum: 4, link_spam: false } },
    ],
    external_checks: {
      plagiarism: { status: 'not_performed', result: 'No third-party plagiarism service was used; no external plagiarism claim is made.' },
      ai_detection: { status: 'unavailable', result: 'No external AI detector result is available; no AI-authorship claim is made.' },
    },
  };
}

function referenceFixture() {
  const result = fixture();
  const projectDatabasePath = join(result.directory, 'project.sqlite');
  const project = new DatabaseSync(projectDatabasePath);
  const keywords = Array.from({ length: 145 }, (_, index) => `keyword-${index + 1}`);
  const content = 'Fixture semantic core with 145 approved non-navigation queries.';
  const dataJson = JSON.stringify({ taxonomy: { fixture: keywords }, keyword_count: keywords.length });
  project.exec(`CREATE TABLE project_storage_metadata (
    singleton INTEGER PRIMARY KEY, project_id TEXT NOT NULL, storage_format INTEGER NOT NULL
  ); CREATE TABLE memory_candidates (
    id TEXT PRIMARY KEY, semantic_key TEXT NOT NULL, title TEXT NOT NULL, content TEXT,
    data_json TEXT, status TEXT NOT NULL
  );`);
  project.prepare('INSERT INTO project_storage_metadata VALUES (1,?,1)').run('00000000-0000-4000-a000-000000000102');
  project.prepare(`INSERT INTO memory_candidates(id,semantic_key,title,content,data_json,status)
    VALUES (?,?,?,?,?,'approved')`).run('fixture-semantic-core', 'content.metrichit_semantic_core',
      'Fixture semantic core', content, dataJson);
  project.close();

  const control = new DatabaseSync(result.databasePath);
  const pointer = control.prepare('SELECT metadata_json FROM scoped_memory_records WHERE semantic_key=?').get(SEMANTIC_CORE_REFERENCE_KEY);
  const metadata = JSON.parse(pointer.metadata_json);
  metadata.candidate_id = 'fixture-semantic-core';
  metadata.content_sha256 = createHash('sha256').update(content).digest('hex');
  metadata.data_json_sha256 = createHash('sha256').update(dataJson).digest('hex');
  control.prepare('UPDATE scoped_memory_records SET metadata_json=? WHERE semantic_key=?')
    .run(JSON.stringify(metadata), SEMANTIC_CORE_REFERENCE_KEY);
  control.close();
  return { ...result, projectDatabasePath, keywords };
}

test('P0/P1: canonical contract, passports and fail-closed ownership are present', () => {
  const { directory, databasePath } = fixture();
  try {
    const specification = readFileSync(resolve('documents/structured-memory.md'), 'utf8');
    assert.match(specification, /147 579 байт/);
    const db = new DatabaseSync(databasePath);
    assert.deepEqual(db.prepare('SELECT id FROM scope_passports ORDER BY id').all().map((row) => row.id),
      [SCOPE_IDS.core, SCOPE_IDS.metrichit, SCOPE_IDS.editorial, SCOPE_IDS.panel].sort());
    assert.equal(db.prepare('SELECT count(*) count FROM scoped_memory_records WHERE scope_id IS NULL').get().count, 0);
    db.close();
    const queued = registerScopedRecord(databasePath, { semanticKey: 'ambiguous.fixture', title: 'Ambiguous', content: 'x' });
    assert.equal(queued.status, 'queued');
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(readOnly.prepare("SELECT count(*) count FROM unresolved_memory_queue WHERE status='pending'").get().count, 1);
    assert.equal(resolveScopedMemory(readOnly, SCOPE_IDS.editorial, 'editorial').records.some((row) => row.semantic_key === 'ambiguous.fixture'), false);
    readOnly.close();
    const task = createTaskScope(databasePath, { taskId: 'fixture-1', parentScopeId: SCOPE_IDS.editorial, name: 'Fixture task', summary: 'Task-local temporary scope.' });
    const taskDb = new DatabaseSync(databasePath, { readOnly: true });
    assert.deepEqual(scopeNames(taskDb, task.id), ['Ядро', 'MetricHit', 'Редакция', 'Fixture task']);
    taskDb.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('P2: inheritance is deterministic, core prohibition is sticky, superseded and sibling memory do not leak', () => {
  const { directory, databasePath } = fixture();
  try {
    const stored = registerScopedRecord(databasePath, {
      id: 'memory:test:old', semanticKey: 'editorial.revision', scopeId: SCOPE_IDS.editorial,
      layer: 'working', recordType: 'decision', title: 'Old', content: 'old',
      sourceRef: 'test', validFrom: '2026-08-30T00:00:00.000Z', taskTypes: ['editorial'],
    });
    assert.equal(stored.status, 'stored');
    supersedeScopedRecord(databasePath, 'memory:test:old', {
      id: 'memory:test:new', semanticKey: 'editorial.revision', scopeId: SCOPE_IDS.editorial,
      layer: 'working', recordType: 'decision', title: 'New', content: 'new', sourceRef: 'test',
      validFrom: '2026-08-31T00:00:00.000Z', taskTypes: ['editorial'],
    });
    const db = new DatabaseSync(databasePath);
    try {
      assert.throws(() => db.prepare(`INSERT INTO scoped_memory_records
        (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,rule_effect,created_at,updated_at)
        VALUES ('memory:test:override','governance.owner_gates',?,'permanent','rule','active','Override','allow','test','2026-08-31','allow','2026-08-31','2026-08-31')`).run(SCOPE_IDS.editorial), /core prohibition/);
      const active = resolveScopedMemory(db, SCOPE_IDS.editorial, 'editorial').records;
      assert.equal(active.find((row) => row.semantic_key === 'editorial.revision').content, 'new');
      assert.equal(active.some((row) => row.semantic_key === 'panel.ux_contract_required'), false);
      const history = resolveScopedMemory(db, SCOPE_IDS.editorial, 'editorial', { includeHistory: true }).records;
      assert.equal(history.some((row) => row.id === 'memory:test:old'), false, 'superseded revision is not selected over its current semantic key');
    } finally { db.close(); }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('P3: router asks one question for material ambiguity and audit stores no prompt or reasoning', () => {
  const { directory, databasePath } = fixture();
  try {
    const db = new DatabaseSync(databasePath);
    const ambiguous = routeTask(db, { text: 'Проверь панель' });
    assert.equal(ambiguous.outcome, 'needs_clarification');
    assert.match(ambiguous.question, /Уточните один scope/);
    db.close();
    const result = compileContextPack(databasePath, { text: 'Проверь панель' });
    assert.equal(result.pack, null);
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    const audit = readOnly.prepare('SELECT * FROM scope_routing_audit').get();
    assert.equal(audit.outcome, 'needs_clarification');
    assert.equal(Object.hasOwn(audit, 'task_text'), false);
    assert.equal(Object.hasOwn(audit, 'reasoning'), false);
    readOnly.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('P4/P5: compiler is stable, smaller than baseline and isolates Editorial from Panel', () => {
  const { directory, databasePath } = fixture();
  try {
    const db = new DatabaseSync(databasePath, { readOnly: true });
    const agents = readFileSync(resolve('AGENTS.md'), 'utf8');
    const editorialCard = { result: 'Материал', scope: ['work/articles'], firstCheck: 'editorial-check', acceptance: ['ready'], forbiddenChanges: ['publication'] };
    const panelCard = { result: 'Панель', scope: ['operator-panel'], firstCheck: 'ui-check', acceptance: ['visible'], forbiddenChanges: ['runtime'] };
    const editorialA = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: agents, taskBrief: editorialCard });
    const editorialB = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: agents, taskBrief: editorialCard });
    const panel = compileDeterministicContext(db, { scopeId: SCOPE_IDS.panel, taskType: 'ui', agentsContent: agents, taskBrief: panelCard });
    assert.deepEqual(editorialA, editorialB);
    assert.deepEqual(editorialA.passports.map((item) => item.name), ['Ядро', 'MetricHit', 'Редакция']);
    assert.deepEqual(panel.passports.map((item) => item.name), ['Ядро', 'MetricHit', 'Панель']);
    assert.equal(editorialA.rules.some((item) => item.semantic_key.startsWith('panel.')), false);
    assert.equal(panel.rules.some((item) => item.semantic_key.startsWith('editorial.')), false);
    assert.deepEqual(editorialA.references.map((item) => item.semantic_key), [SEMANTIC_CORE_REFERENCE_KEY]);
    assert.deepEqual(editorialA.expanded_references, []);
    assert.deepEqual(panel.references, []);
    assert.deepEqual(panel.expanded_references, []);
    assert.equal(editorialA.execution_card.task_type, 'editorial');
    assert.equal(editorialA.execution_card.mandatory_rules.some((item) => item.source === 'AGENTS.md'), true);
    assert.equal(editorialA.execution_card.mandatory_rules.some((item) => item.semantic_key.startsWith('panel.')), false);
    assert.equal(panel.execution_card.mandatory_rules.some((item) => item.semantic_key.startsWith('editorial.')), false);
    assert.ok(Buffer.byteLength(JSON.stringify(editorialA)) < 147579);
    db.close();
    const compiled = compileContextPack(databasePath, { text: 'Подготовь статью MetricHit', taskBrief: {
      result: 'Проверенный материал', scope: ['work/articles'], forbiddenChanges: ['publication'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['context_is_minimal'],
    } });
    assert.equal(compiled.route.scopeId, SCOPE_IDS.editorial);
    assert.equal(compiled.pack.status, 'open');
    assert.equal(compiled.pack.payload.task_brief.result, 'Проверенный материал');
    assert.deepEqual(compiled.pack.payload.task_brief.forbidden_changes, ['publication']);
    assert.match(compiled.pack.payload.execution_card_hash, /^[a-f0-9]{64}$/);
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id), /delivery validation failed/);
    assert.equal(closeContextPack(databasePath, compiled.pack.id, {
      result: 'Материал проверен', checks: ['node --test tests/structured-memory.test.mjs'],
      satisfiedAcceptance: ['context_is_minimal'], scopeCompliance: true, forbiddenChangesObserved: [],
      contentQa: tenChatContentQa(),
    }).status, 'closed');
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(readOnly.prepare('SELECT status FROM context_packs WHERE id=?').get(compiled.pack.id).status, 'closed');
    assert.equal(readOnly.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
    assert.deepEqual(readOnly.prepare('PRAGMA foreign_key_check').all(), []);
    readOnly.close();
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('delivery validation rejects a changed execution card', () => {
  const { directory, databasePath } = fixture();
  try {
    const compiled = compileContextPack(databasePath, { text: 'Исправь Python модуль MetricHit', taskBrief: {
      result: 'Исправление', scope: ['scripts'], firstCheck: 'code-check',
      acceptance: ['fixed'], forbiddenChanges: ['ui'],
    } });
    const database = new DatabaseSync(databasePath);
    const row = database.prepare('SELECT payload_json FROM context_packs WHERE id=?').get(compiled.pack.id);
    const payload = JSON.parse(row.payload_json);
    payload.execution_card.acceptance = ['changed'];
    database.prepare('UPDATE context_packs SET payload_json=? WHERE id=?').run(JSON.stringify(payload), compiled.pack.id);
    database.close();
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, {
      result: 'done', checks: ['code-check'], satisfiedAcceptance: ['changed'],
      scopeCompliance: true, forbiddenChangesObserved: [],
    }), /execution_card_hash_mismatch/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('global execution gate fails closed for incomplete cards and validates all supported task types', () => {
  const { directory, databasePath } = fixture();
  try {
    assert.throws(() => compileContextPack(databasePath, { text: 'Обнови документацию MetricHit' }), /execution card is incomplete/);
    const rejectedDb = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(rejectedDb.prepare("SELECT outcome FROM scope_routing_audit WHERE outcome='rejected'").get().outcome, 'rejected');
    assert.equal(rejectedDb.prepare('SELECT count(*) count FROM context_packs').get().count, 0);
    rejectedDb.close();

    const scenarios = [
      ['editorial', 'Подготовь статью MetricHit', SCOPE_IDS.editorial],
      ['code', 'Исправь Python модуль MetricHit', SCOPE_IDS.metrichit],
      ['docs', 'Обнови документацию MetricHit', SCOPE_IDS.metrichit],
      ['research', 'Исследуй семантическое ядро MetricHit', SCOPE_IDS.editorial],
      ['ui', 'Исправь UI operator panel MetricHit', SCOPE_IDS.panel],
    ];
    for (const [taskType, text, scopeId] of scenarios) {
      const acceptance = [`${taskType}_accepted`];
      const firstCheck = `${taskType}-check`;
      const compiled = compileContextPack(databasePath, { text, taskBrief: {
        result: `${taskType} result`, scope: [`${taskType} scope`], firstCheck,
        acceptance, forbiddenChanges: ['out of scope'],
      } });
      assert.equal(compiled.route.taskType, taskType);
      assert.equal(compiled.route.scopeId, scopeId);
      assert.equal(compiled.pack.payload.execution_card.target_scope, scopeId);
      assert.throws(() => closeContextPack(databasePath, compiled.pack.id, {
        result: 'done', checks: [firstCheck], satisfiedAcceptance: [], scopeCompliance: true, forbiddenChangesObserved: [],
      }), /acceptance_evidence/);
      const closed = closeContextPack(databasePath, compiled.pack.id, {
        result: 'done', checks: [firstCheck], satisfiedAcceptance: acceptance,
        scopeCompliance: true, forbiddenChangesObserved: [],
        contentQa: taskType === 'editorial' ? tenChatContentQa() : null,
      });
      assert.equal(closed.validation.scope_compliant, true);
    }
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('editorial TenChat gate includes approved unscoped requirements and requires exact local content QA', () => {
  const { directory, databasePath } = fixture();
  try {
    const taskBrief = {
      result: 'Проверенный TenChat-материал', scope: ['work/social/tenchat'],
      firstCheck: 'node --test tests/structured-memory.test.mjs',
      acceptance: ['tenchat_ready'], forbiddenChanges: ['publication'],
    };
    const compiled = compileContextPack(databasePath, {
      text: 'Подготовь статью TenChat о накрутке ПФ для MetricHit', taskBrief,
    });
    const card = compiled.pack.payload.execution_card;
    const keys = card.mandatory_rules.map((item) => item.semantic_key);
    assert.ok(keys.includes('content.editorial_article_preparation_policy'));
    assert.ok(keys.includes('content.public_pf_positive_framing'));
    assert.ok(keys.includes('owner.editorial.h1_high_frequency_query'));
    assert.ok(keys.includes('editorial.tenchat_format_and_search_policy'));
    assert.equal(keys.includes('editorial.telegram_short_professional'), false);
    assert.match(card.mandatory_rules.find((item) => item.semantic_key === 'content.editorial_article_preparation_policy').content,
      /четыре естественные ссылки/);
    assert.match(card.mandatory_rules.find((item) => item.semantic_key === 'owner.editorial.h1_high_frequency_query').content,
      /накрутка ПФ.*накрутка поведенческого фактора/);
    assert.deepEqual(card.delivery_qa.checks.map((item) => item.id), [
      'landing_link_distribution', 'originality_source_overlap', 'h1_high_frequency_query',
      'tenchat_character_count', 'single_search_intent', 'natural_primary_keyword', 'link_count_and_spam',
    ]);

    const baseDelivery = {
      result: 'Материал проверен', checks: [taskBrief.firstCheck],
      satisfiedAcceptance: taskBrief.acceptance, scopeCompliance: true, forbiddenChangesObserved: [],
    };
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, baseDelivery), /editorial_content_qa_missing/);
    const incompleteQa = tenChatContentQa();
    incompleteQa.checks = incompleteQa.checks.filter((item) => item.id !== 'originality_source_overlap');
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, { ...baseDelivery, contentQa: incompleteQa }),
      /editorial_content_qa_incomplete:originality_source_overlap/);
    const falseExternalClaim = tenChatContentQa();
    falseExternalClaim.external_checks.plagiarism.status = 'passed';
    assert.throws(() => closeContextPack(databasePath, compiled.pack.id, { ...baseDelivery, contentQa: falseExternalClaim }),
      /editorial_external_check_claim:plagiarism/);
    const closed = closeContextPack(databasePath, compiled.pack.id, { ...baseDelivery, contentQa: tenChatContentQa() });
    assert.equal(closed.status, 'closed');
    assert.equal(closed.validation.content_qa.local_deterministic_checks
      .find((item) => item.id === 'originality_source_overlap').evidence.max_overlap_percent, 8.5);
    assert.equal(closed.validation.content_qa.external_checks.plagiarism.status, 'not_performed');

    const unrelated = compileContextPack(databasePath, { text: 'Исправь UI operator panel MetricHit', taskBrief: {
      result: 'UI', scope: ['operator-panel'], firstCheck: 'ui-check', acceptance: ['visible'], forbiddenChanges: ['editorial'],
    } });
    assert.equal(unrelated.pack.payload.execution_card.mandatory_rules
      .some((item) => item.semantic_key === 'content.editorial_article_preparation_policy'), false);
    assert.equal(unrelated.pack.payload.execution_card.delivery_qa, null);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('semantic core pointer is scoped to editorial/research and full content is explicit and project-authoritative', () => {
  const { directory, databasePath, projectDatabasePath, keywords } = referenceFixture();
  try {
    const db = new DatabaseSync(databasePath, { readOnly: true });
    const card = { result: 'Reference test', scope: ['memory'], firstCheck: 'test', acceptance: ['valid'], forbiddenChanges: ['drift'] };
    const general = compileDeterministicContext(db, { scopeId: SCOPE_IDS.metrichit, taskType: 'general', agentsContent: '', taskBrief: card });
    const editorial = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: '', taskBrief: card });
    const research = compileDeterministicContext(db, {
      scopeId: SCOPE_IDS.editorial, taskType: 'research', includeReferencedContent: true,
      projectDatabasePath, agentsContent: '', taskBrief: card,
    });
    assert.deepEqual(general.references, []);
    assert.deepEqual(general.expanded_references, []);
    assert.equal(JSON.stringify(general).includes('keyword-1'), false);
    assert.equal(editorial.references.length, 1);
    assert.deepEqual(editorial.expanded_references, []);
    assert.equal(JSON.stringify(editorial).includes('keyword-1'), false);
    assert.equal(research.references.length, 1);
    assert.equal(research.expanded_references[0].project_id, '00000000-0000-4000-a000-000000000102');
    assert.deepEqual(research.expanded_references[0].data.taxonomy.fixture, keywords);
    assert.equal(research.expanded_references[0].source_database, 'project.sqlite');
    const explicitEditorial = compileDeterministicContext(db, {
      scopeId: SCOPE_IDS.editorial, taskType: 'editorial', includeReferencedContent: true,
      projectDatabasePath, agentsContent: '', taskBrief: card,
    });
    assert.equal(explicitEditorial.expanded_references[0].data.keyword_count, 145);
    assert.throws(() => compileDeterministicContext(db, {
      scopeId: SCOPE_IDS.metrichit, taskType: 'general', includeReferencedContent: true,
      projectDatabasePath, agentsContent: '', taskBrief: card,
    }), /only for an explicit editorial or research task/);
    db.close();

    const routeDatabase = new DatabaseSync(databasePath, { readOnly: true });
    const route = routeTask(routeDatabase, { text: 'Исследуй семантическое ядро MetricHit' });
    routeDatabase.close();
    assert.equal(route.scopeId, SCOPE_IDS.editorial);
    assert.equal(route.taskType, 'research');
    const explicitRouteDatabase = new DatabaseSync(databasePath, { readOnly: true });
    const explicitResearch = routeTask(explicitRouteDatabase, { text: 'MetricHit', taskType: 'research' });
    explicitRouteDatabase.close();
    assert.equal(explicitResearch.scopeId, SCOPE_IDS.editorial);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

test('authoritative semantic reference fails closed on project content drift', () => {
  const { directory, databasePath, projectDatabasePath } = referenceFixture();
  try {
    const control = new DatabaseSync(databasePath, { readOnly: true });
    const records = resolveScopedMemory(control, SCOPE_IDS.editorial, 'research').records;
    control.close();
    const project = new DatabaseSync(projectDatabasePath);
    project.prepare('UPDATE memory_candidates SET data_json=? WHERE id=?')
      .run('{"taxonomy":{"fixture":[]},"keyword_count":0}', 'fixture-semantic-core');
    project.close();
    assert.throws(() => loadReferencedMemory(projectDatabasePath, records, 'research'), /hash mismatch/);
  } finally { rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }); }
});

function scopeNames(database, scopeId) {
  const names = [];
  let current = scopeId;
  while (current) {
    const row = database.prepare('SELECT name,parent_scope_id FROM scope_passports WHERE id=?').get(current);
    names.push(row.name); current = row.parent_scope_id;
  }
  return names.reverse();
}
