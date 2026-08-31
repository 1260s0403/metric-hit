import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';

import {
  SCOPE_IDS, closeContextPack, compileContextPack, compileDeterministicContext, createTaskScope,
  registerScopedRecord, resolveScopedMemory, routeTask, supersedeScopedRecord,
} from '../scripts/structured-memory.mjs';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'metrichit-structured-memory-'));
  const databasePath = join(directory, 'memory.sqlite');
  execFileSync(process.execPath, [resolve('scripts/init-memory.mjs'), databasePath]);
  return { directory, databasePath };
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
    const editorialA = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: agents });
    const editorialB = compileDeterministicContext(db, { scopeId: SCOPE_IDS.editorial, taskType: 'editorial', agentsContent: agents });
    const panel = compileDeterministicContext(db, { scopeId: SCOPE_IDS.panel, taskType: 'ui', agentsContent: agents });
    assert.deepEqual(editorialA, editorialB);
    assert.deepEqual(editorialA.passports.map((item) => item.name), ['Ядро', 'MetricHit', 'Редакция']);
    assert.deepEqual(panel.passports.map((item) => item.name), ['Ядро', 'MetricHit', 'Панель']);
    assert.equal(editorialA.rules.some((item) => item.semantic_key.startsWith('panel.')), false);
    assert.equal(panel.rules.some((item) => item.semantic_key.startsWith('editorial.')), false);
    assert.ok(Buffer.byteLength(JSON.stringify(editorialA)) < 147579);
    db.close();
    const compiled = compileContextPack(databasePath, { text: 'Подготовь статью MetricHit', taskBrief: {
      result: 'Проверенный материал', allowedChanges: ['work/articles'], forbiddenChanges: ['publication'],
      firstCheck: 'node --test tests/structured-memory.test.mjs', acceptance: ['context_is_minimal'],
    } });
    assert.equal(compiled.route.scopeId, SCOPE_IDS.editorial);
    assert.equal(compiled.pack.status, 'open');
    assert.equal(compiled.pack.payload.task_brief.result, 'Проверенный материал');
    assert.deepEqual(compiled.pack.payload.task_brief.forbidden_changes, ['publication']);
    assert.equal(closeContextPack(databasePath, compiled.pack.id).status, 'closed');
    const readOnly = new DatabaseSync(databasePath, { readOnly: true });
    assert.equal(readOnly.prepare('SELECT status FROM context_packs WHERE id=?').get(compiled.pack.id).status, 'closed');
    assert.equal(readOnly.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
    assert.deepEqual(readOnly.prepare('PRAGMA foreign_key_check').all(), []);
    readOnly.close();
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
