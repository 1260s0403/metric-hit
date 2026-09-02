import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import {
  METRICHIT_PROJECT_ID,
  YADRO_CONTROL_PLANE_PROJECT_ID,
  abandonContextPack,
} from './structured-memory.mjs';

export const REPAIR_BATCH_KEY = 'core-integrity-repair-2026-09-02-v1';
export const CENTRAL_ORPHAN_PACK_IDS = Object.freeze([
  '16959e6c-dfc8-4a77-a6a6-a659f009bac4',
  'ed7be6fe-c3b3-4b70-98d3-84008818684b',
  'f6a6da02-0e8f-4b55-8d13-91d1e5497855',
  '77d101e0-5570-4ea7-8b00-a4ad4e70b17b',
  '4ebc22af-27e3-4698-b766-594deb5dac6b',
  '57d5c8a6-67b6-4271-a167-2d956662d540',
  'c2cd3bee-21c6-4626-879c-78d4d07aafa4',
  '02376408-cca2-4dd1-8d41-22c0dd0cc508',
  'e03b5948-32bf-4a5e-97a5-19fa5416f163',
  '69865180-b5eb-4fcb-b938-a28d606952fd',
]);
export const PROJECT_ORPHAN_PACK_IDS = Object.freeze([
  '31beea6b-4176-4d96-b775-1d805ce85be4',
]);
export const HISTORICAL_AUDIT_TARGET_IDS = Object.freeze([
  '2a688847-8a74-4ad7-bd6d-ceb448bd0dec', '54f9638a-2801-4892-88d1-2af825fbacb6',
  '7bb5dc68-cd98-434d-8d61-7706eadf85c4', 'e24e3b85-dba1-4a40-aba0-01f722c263a0',
  'e789f4d0-6900-4b28-a61d-301ba692df37', 'e80a9631-fdf3-4db1-8fd6-aee1dcbd7754',
  '04a7492f-43bc-41a6-bcea-faad34b043e8', '0204038d-d8be-4614-a39c-e4dc4796e0bf',
  '021c3561-a4bd-43e1-8f1f-8b497ea8a5a5', '07241804-9235-43e2-b4e2-c9a6baa6bfbc',
  '09959fa0-7a6b-44d1-bbde-d70512f04cb4', '0b5c8bd4-5f2b-41d5-8056-eff4b49e6a70',
  '0db85791-4768-4244-900a-a66a5b8f8e54', '1f6d2453-58ef-4067-b539-bbaf0e805103',
  '26703ab8-fcca-4f91-99b6-f816a69d4c4f', '299678d9-e7fd-4bb6-9d03-bfcea4a4efc3',
  '3817ca9c-b6cb-43df-b2cd-db36044ff3d8', '3a57142a-5c2e-4a10-a1ce-49c4a59df7a4',
  '4f81aa00-a0eb-412f-a16e-a3078a6fef12', '69275352-9ac3-45d6-b78e-798cc514ddfd',
  '6f99d4b2-96aa-4d7c-8f94-6e9e1d7e16f1', '7b16dfed-cfcd-4297-8a6c-e4fe69ba7c56',
  '7ff3b4fe-c6ae-4a1e-9669-a95419f1b3e9', '82548ed2-e684-468a-9f74-c881b4762ca5',
  '930a4777-9da6-4081-b14d-698417022f7b', '952dba2c-f604-409d-92e3-4401690bc3ef',
  '983f6a69-5d8a-4b09-9873-b955d8bb620c', 'a282409e-c445-4b21-8ebf-553592e101ef',
  'a848fe72-1745-47e8-9789-51e18bb4f29c', 'b1c1a284-c22d-4779-9f87-b7d6cf0b8bd4',
  'b9511e41-de9e-4645-b679-e28a18743486', 'bd1d90de-fa84-4ec0-9f3a-9213fad9ac35',
  'c57e153c-b0a4-4e2d-882f-16fc642514f6', 'c6ade459-0084-44b8-8155-08e4d7ff6958',
  'cdbf31da-d362-4d35-bdd8-edf72e8b946a', 'd2194d48-dc0e-443b-b04c-058969086a31',
  'dae15126-792d-4bf3-91e2-dd34fd264bb3', 'dfb4738d-930e-430d-a6bd-8f96420ef4cf',
  'e6ce0fe7-0572-4844-b7c6-62e862e64cdc', 'e783f42b-edd4-4b1f-a379-6eff140eaf65',
  'f110a334-7ec8-42fa-ad38-6b56f1c665b9', 'f52e6e15-f2dc-4075-ace3-6c8f1f42264f',
  'ff4e459d-e8a0-480b-9b82-c98e222a3162',
]);
export const DECISION_MEMORY_TARGET_IDS = Object.freeze([
  '2a642dbe-bcc0-481f-a1a4-1fd9ba81f8d0', '5ce53127-bd88-4bf8-a2a5-c71c862123db',
  '78bbcdee-42bb-42de-acf5-b36e0a51cc43', '7d757f11-c813-4cb0-aaba-22e722bf5836',
  'ba5e32a8-c6e4-43d5-ac8c-58d4321d984e', 'c3e6828c-382a-4f95-ad06-06cf42d19f22',
  'db7e775e-0613-44ef-abf1-50cf7e3c9f5b', 'f64c9898-f60c-46ae-a3f8-6feffcf19d95',
]);
export const SOURCE_TARGET_IDS = Object.freeze([
  '25bdf0ce-16cf-4c01-a295-c6564f559b8c', '4f8d6e9b-7186-4a8f-a879-40f4f3011b58',
  '19d40e2f-ea72-4821-a16f-fcf227e52a20', 'd545bfcf-6153-4352-acb4-aa7456199cfb',
  'cd7ab807-8d66-46ec-a582-de607879a644', 'bd5a5ead-b315-4683-a106-f9966335e54b',
  '1336579f-f86a-41df-a558-9dc7ff3c9c81', '70860a74-0e25-4af8-a068-d7557e09002b',
  '79af0288-abe6-4d6f-a9f7-7e0846b76896', 'dc7996b2-97cd-449b-a9fd-403ef440575d',
  '9a9aa2a5-ac0c-45df-aebc-4e6c2b0e5278', '929c66c8-bdca-4997-a32e-67a0aec89832',
  '2700f875-b4eb-4da2-a007-b493d2045138', '4cbf1226-a210-4e77-a98c-ef688a08b506',
  'a0883773-07ea-4064-a3e0-240271c110ad', 'a07556da-3525-4dfa-a828-cb2116823b9a',
  '6d07f547-569b-42e3-ad5e-7203d1e56ee9', '29581a13-7dc3-429d-a9b7-239fb2620289',
  '7f90b8dd-dadc-4dd9-ae11-8af3db3e5425', 'a93bc88b-7549-4d62-a809-bf19471060bd',
  '4dab05b5-ff1d-422a-af5f-273686b22a83', '3ad72843-a52d-4406-a214-9bd8d5cc20b5',
  'f78e9f39-045e-4cc8-ae55-f028b0d4e127', 'f3505305-ce6d-450d-a38a-6c78ec5ca18b',
  '286f9675-dd64-4bf8-a313-d3664f94a2d2', 'a92bd79e-d70a-4ffb-a093-20a078a4ce0f',
  'd1aae8e5-25ee-491f-ad83-46ff5bee7df6', 'f70ad48f-719b-4a9d-adc4-bcf84f17782e',
  'ef2c57f7-5e30-40cc-a584-06bb6b4c5940', '05897725-52f0-46f6-a2bb-1fab6d0ce7d5',
  'e1857557-009f-463e-a814-6804e9579f1b', '0d3e0e71-f158-4901-aa09-926a86160ca3',
  '49bdacfe-f845-4d42-ab3d-c9d8454f30f7', 'd74f743f-cf8d-4be2-ab7b-2a230f60354b',
  '506effa8-3aee-4b27-a0dc-fca67929e8a7', '13923265-75dc-4514-aade-a2669c50fb38',
  '5ceb7e73-6d7f-46e8-a3ce-98fc13e6db69', '0a137a8b-36e4-4a11-aeb9-990c298ae1e4',
  '626818e6-f826-4f42-aa17-4d6bec9dcd8e', 'eb3beb39-24f8-48a3-a493-bda0c339ee79',
  '169f32fc-4e5a-4812-aeca-a1c383005964', '2660f8ab-3037-47d1-a134-016978cf8cca',
  'ed7fa300-475d-4c0e-a880-b0d1e608af14',
]);
export const CORE_SOURCE_TARGET_IDS = Object.freeze([
  '79af0288-abe6-4d6f-a9fd-403ef440575d', 'dc7996b2-97cd-449b-a9fd-403ef440575d',
  '2700f875-b4eb-4da2-a007-b493d2045138', '4cbf1226-a210-4e77-a98c-ef688a08b506',
  '2660f8ab-3037-47d1-a134-016978cf8cca', 'ed7fa300-475d-4c0e-a880-b0d1e608af14',
]);

function hash(value) {
  return createHash('sha256').update(value).digest('hex');
}

function deterministicUuid(value) {
  const hex = hash(value).slice(0, 32).split('');
  hex[12] = '5';
  hex[16] = ['8', '9', 'a', 'b'][Number.parseInt(hex[16], 16) % 4];
  return `${hex.slice(0, 8).join('')}-${hex.slice(8, 12).join('')}-${hex.slice(12, 16).join('')}-${hex.slice(16, 20).join('')}-${hex.slice(20).join('')}`;
}

function assignmentExists(database, table, entityId) {
  return Boolean(database.prepare(`SELECT 1 FROM audit_log
    WHERE type IN ('project_scope_assignment','project_scope_assignment_correction')
      AND json_extract(data_json,'$.table')=? AND json_extract(data_json,'$.entityId')=?
    LIMIT 1`).get(table, entityId));
}

function requireCount(label, rows, expected) {
  if (rows.length !== expected) throw new Error(`${label}: expected ${expected}, found ${rows.length}`);
  return rows;
}

function assignmentTargets(centralDatabase, projectDatabase) {
  const targets = [];
  const add = (table, id, projectId, basis) => targets.push({ table, id, projectId, basis });
  const unassigned = (table, id) => !assignmentExists(centralDatabase, table, id);

  const historicalAudit = requireCount('unassigned historical audit targets', HISTORICAL_AUDIT_TARGET_IDS.map((id) => {
    const row = centralDatabase.prepare(`SELECT id FROM audit_log
      WHERE id=? AND type IN ('knowledge_entry_change','project_change','task_change')`).get(id);
    if (!row || !unassigned('audit_log', row.id)) throw new Error(`historical audit target changed: ${id}`);
    return row;
  }), 43);
  const projectAudit = historicalAudit.filter((row) => projectDatabase.prepare(
    'SELECT 1 FROM audit_log WHERE id=?',
  ).get(row.id));
  requireCount('project-materialized historical audit targets', projectAudit, 42);
  const projectAuditIds = new Set(projectAudit.map((row) => row.id));
  for (const row of historicalAudit) add('audit_log', row.id,
    projectAuditIds.has(row.id) ? METRICHIT_PROJECT_ID : YADRO_CONTROL_PLANE_PROJECT_ID,
    projectAuditIds.has(row.id) ? 'present_in_verified_project_materialization' : 'control_plane_history');

  const editorialDecision = requireCount('unassigned editorial decision targets', centralDatabase.prepare(`
    SELECT id FROM decisions WHERE type='editorial_policy' ORDER BY id`).all()
    .filter((row) => unassigned('decisions', row.id)), 1);
  for (const row of editorialDecision) add('decisions', row.id, METRICHIT_PROJECT_ID, 'editorial_policy_type');

  const projectTypes = requireCount('unassigned project memory targets', centralDatabase.prepare(`
    SELECT id,type FROM memory_candidates
    WHERE status='approved' AND type IN ('commercial_terms','editorial_rule','publication_state')
    ORDER BY id`).all().filter((row) => unassigned('memory_candidates', row.id)), 52);
  for (const row of projectTypes) add('memory_candidates', row.id, METRICHIT_PROJECT_ID,
    `managed_project_memory_type:${row.type}`);

  const unassignedDecisions = requireCount('unassigned decision memory targets', DECISION_MEMORY_TARGET_IDS.map((id) => {
    const row = centralDatabase.prepare(`SELECT id,semantic_key,data_json FROM memory_candidates
      WHERE id=? AND status='approved' AND type='decision'`).get(id);
    if (!row || !unassigned('memory_candidates', row.id)
      || JSON.parse(row.data_json).belongs_to === 'central_core') {
      throw new Error(`decision memory target changed: ${id}`);
    }
    return row;
  }), 8);
  for (const row of unassignedDecisions) {
    const isEditorial = row.semantic_key === 'editorial.registry_current_state'
      || row.semantic_key === 'content.editorial_search_result_scope';
    const isCore = row.semantic_key === 'operations.server_strategy_workflow'
      || row.semantic_key === 'operations.marketing_skills_evaluation_and_installation';
    if (!isEditorial && !isCore) throw new Error(`unknown ownership for decision ${row.id}`);
    add('memory_candidates', row.id, isEditorial ? METRICHIT_PROJECT_ID : YADRO_CONTROL_PLANE_PROJECT_ID,
      `approved_semantic_scope:${row.semantic_key}`);
  }
  const coreSourceIds = new Set(CORE_SOURCE_TARGET_IDS);
  const unassignedSources = requireCount('unassigned source targets', SOURCE_TARGET_IDS.map((id) => {
    const row = centralDatabase.prepare('SELECT id FROM sources WHERE id=?').get(id);
    if (!row || !unassigned('sources', row.id)) throw new Error(`source target changed: ${id}`);
    return row;
  }), 43);
  for (const row of unassignedSources) {
    add('sources', row.id, coreSourceIds.has(row.id)
      ? YADRO_CONTROL_PLANE_PROJECT_ID : METRICHIT_PROJECT_ID,
    coreSourceIds.has(row.id) ? 'exact_control_plane_source_manifest' : 'exact_metrichit_source_manifest');
  }
  requireCount('all ownership repair targets', targets, 147);
  return targets;
}

function applyOwnershipAssignments(centralPath, projectPath) {
  const central = new DatabaseSync(centralPath);
  const project = new DatabaseSync(projectPath, { readOnly: true });
  central.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const completed = central.prepare(`SELECT data_json FROM audit_log
      WHERE type='project_scope_assignment' AND json_extract(data_json,'$.batchKey')=?
      ORDER BY id`).all(REPAIR_BATCH_KEY);
    if (completed.length) {
      requireCount('completed ownership repair events', completed, 147);
      central.exec('COMMIT');
      return { selected: 147, applied: 0, replayed: 147,
        manifestSha256: hash(JSON.stringify(completed.map((row) => JSON.parse(row.data_json)))) };
    }
    const targets = assignmentTargets(central, project);
    let applied = 0;
    for (const target of targets) {
      const id = deterministicUuid(`${REPAIR_BATCH_KEY}:${target.table}:${target.id}:${target.projectId}`);
      const data = JSON.stringify({ batchKey: REPAIR_BATCH_KEY, table: target.table,
        entityId: target.id, project_id: target.projectId, basis: target.basis });
      const changes = central.prepare(`INSERT INTO audit_log
        (id,type,title,content,data_json,author,entity_type,entity_id,action,valid_at)
        VALUES (?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(id) DO NOTHING`).run(id, 'project_scope_assignment',
        'Integrity repair ownership assignment', 'Append-only ownership assignment.', data,
        'integrity-repair-executor', 'project_scope_assignment', target.id, 'update').changes;
      applied += changes;
    }
    central.exec('COMMIT');
    return { selected: targets.length, applied, replayed: targets.length - applied,
      manifestSha256: hash(JSON.stringify(targets)) };
  } catch (error) {
    central.exec('ROLLBACK');
    throw error;
  } finally {
    project.close();
    central.close();
  }
}

function abandonExactPacks(databasePath, ids) {
  return ids.map((id) => abandonContextPack(databasePath, id, {
    owner: 'integrity-repair-executor',
    reason: 'Orphaned routed context pack has no active handoff; terminalized without delivery evidence.',
  }));
}

export function repairOrphanContextPacks(centralPath, projectPath) {
  return {
    centralPacks: abandonExactPacks(centralPath, CENTRAL_ORPHAN_PACK_IDS),
    projectPacks: abandonExactPacks(projectPath, PROJECT_ORPHAN_PACK_IDS),
  };
}

export function applyIntegrityRepair(centralPath, projectPath) {
  const ownership = applyOwnershipAssignments(centralPath, projectPath);
  const packs = repairOrphanContextPacks(centralPath, projectPath);
  return { batchKey: REPAIR_BATCH_KEY, ownership, ...packs };
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const centralPath = resolve(process.argv[2] ?? 'data/database/metrichit.db');
  const projectPath = resolve(process.argv[3]
    ?? 'data/projects/00000000-0000-4000-a000-000000000102/project.sqlite');
  console.log(JSON.stringify(applyIntegrityRepair(centralPath, projectPath), null, 2));
}
