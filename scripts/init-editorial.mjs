import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'editorial', 'editorial.sqlite');
const defaultMigrationsPath = join(repositoryRoot, 'data', 'editorial', 'migrations');
const defaultProjectDatabasePath = join(repositoryRoot, 'data', 'projects', '00000000-0000-4000-a000-000000000102', 'project.sqlite');
const defaultProjectMigrationsPath = join(repositoryRoot, 'data', 'project-migrations', 'editorial');
const defaultProjectId = '00000000-0000-4000-a000-000000000102';
const expectedPipelineProfiles = [
  ['metrichit.editorial.planner.v1', 1, 'planner', 'content-strategy', 'subagent'],
  ['metrichit.editorial.architect.v1', 2, 'architect', 'seo-strategy', 'subagent'],
  ['metrichit.editorial.writer.v1', 3, 'writer', 'copywriting', 'subagent'],
  ['metrichit.editorial.designer.v1', 4, 'designer', 'image', 'subagent'],
  ['metrichit.editorial.validator.v1', 5, 'validator', 'compliance-qa', 'internal_filter'],
];
const EMPTY_TOPIC_HOTFIX = Object.freeze({
  id: 'editorial.empty_topic.autoplanning.v1',
  owner_question: 'prohibited',
  applies_to: 'all_five_isolated_profiles',
  planner: {
    required: true,
    mode: 'background',
    steps: ['scan_published_archive_overlap', 'select_free_priority_hf_marker_from_approved_302_core', 'return_exactly_three_ready_structures'],
  },
});

function hotfixDirective(profileId) {
  return {
    ...EMPTY_TOPIC_HOTFIX,
    profile_id: profileId,
    planner_execution_required: profileId === 'metrichit.editorial.planner.v1',
    downstream_input: profileId === 'metrichit.editorial.planner.v1'
      ? 'produce_three_structures'
      : 'consume_owner_approved_structure_only',
  };
}

export function migrationsFrom(migrationsPath = defaultMigrationsPath) {
  return readdirSync(migrationsPath)
    .filter((name) => /^\d+_[a-z0-9_-]+\.sql$/i.test(name))
    .sort()
    .map((name) => {
      const version = Number.parseInt(name.split('_', 1)[0], 10);
      const sql = readFileSync(join(migrationsPath, name), 'utf8');
      return { version, name, sql, checksum: createHash('sha256').update(sql).digest('hex') };
    });
}

function appliedMigrations(database, tableName = 'schema_migrations') {
  if (!['schema_migrations', 'editorial_schema_migrations'].includes(tableName)) throw new Error('Unsupported migration table');
  const exists = database.prepare(
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
  ).get(tableName);
  if (!exists) return new Map();
  return new Map(database.prepare(`SELECT version, name, checksum FROM ${tableName}`).all()
    .map(({ version, name, checksum }) => [version, { name, checksum }]));
}

function applyMigrations(database, migrations, tableName) {
  const applied = appliedMigrations(database, tableName);
  const seen = new Set();
  const appliedNow = [];
  for (const migration of migrations) {
    if (seen.has(migration.version)) throw new Error(`Duplicate migration version: ${migration.version}`);
    seen.add(migration.version);
    const recorded = applied.get(migration.version);
    if (recorded) {
      if (recorded.name !== migration.name || recorded.checksum !== migration.checksum) {
        throw new Error(`Migration ${migration.name} was modified after being applied`);
      }
      continue;
    }
    database.exec('BEGIN IMMEDIATE');
    try {
      database.exec(migration.sql);
      database.prepare(`INSERT INTO ${tableName} (version, name, checksum) VALUES (?, ?, ?)`)
        .run(migration.version, migration.name, migration.checksum);
      database.exec('COMMIT');
      appliedNow.push(migration.version);
    } catch (error) {
      database.exec('ROLLBACK');
      throw error;
    }
  }
  return appliedNow;
}

export function initializeEditorialDatabase(databasePath = defaultDatabasePath, options = {}) {
  const migrationsPath = options.migrationsPath ?? defaultMigrationsPath;
  mkdirSync(dirname(databasePath), { recursive: true });
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;');
  try {
    const migrations = migrationsFrom(migrationsPath);
    if (!migrations.length) throw new Error('No editorial migrations found');
    applyMigrations(database, migrations, 'schema_migrations');
    return {
      databasePath,
      applied: database.prepare('SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version').all(),
    };
  } finally {
    database.close();
  }
}

function verifyPipelineProfiles(database, { hotfix = false } = {}) {
  const profiles = database.prepare(`SELECT profile_id,stage_order,stage_name,capability,profile_kind,
    pipeline_id,execution_mode,policy_json,status FROM editorial_agent_profiles ORDER BY stage_order`).all();
  if (profiles.length !== expectedPipelineProfiles.length) throw new Error('Editorial pipeline must contain exactly five profiles');
  profiles.forEach((profile, index) => {
    const expected = expectedPipelineProfiles[index];
    if ([profile.profile_id, profile.stage_order, profile.stage_name, profile.capability, profile.profile_kind]
      .some((value, field) => value !== expected[field])) throw new Error(`Editorial pipeline profile ${index + 1} differs`);
    if (profile.pipeline_id !== 'metrichit.editorial.pipeline.v1' || profile.execution_mode !== 'isolated_sequential' || profile.status !== 'active') {
      throw new Error(`Editorial pipeline profile ${profile.profile_id} is not active and isolated`);
    }
    const policy = JSON.parse(profile.policy_json);
    if (policy.semantic_core?.keyword_count !== 302
      || JSON.stringify(policy.zonal_distribution?.applies_only_to) !== JSON.stringify(['new_articles', 'new_longreads'])
      || !policy.zonal_distribution?.excluded_platforms?.includes('telegram')
      || policy.zonal_distribution?.lsi?.role !== 'non_targeted_professional_lexicon'
      || policy.zonal_distribution?.lsi?.outside_core_allowed !== true
      || JSON.stringify(policy.zonal_distribution?.lsi?.allowed_zones) !== JSON.stringify(['h3', 'unordered_lists'])
      || JSON.stringify(policy.zonal_distribution?.lsi?.prohibited_zones) !== JSON.stringify(['h1', 'h2'])
      || policy.geo_gate?.keyword_count !== 37
      || policy.geo_gate?.required_execution_card_flag !== 'geo_demand_owner_confirmed'
      || policy.geo_gate?.required_value !== true) throw new Error(`Editorial pipeline policy differs for ${profile.profile_id}`);
  });
  return hotfix ? profiles.map((profile) => ({ ...profile, hotfix: hotfixDirective(profile.profile_id) })) : profiles;
}

export function updateEditorialInfrastructure(databasePath = defaultProjectDatabasePath, options = {}) {
  const resolvedDatabasePath = resolve(databasePath);
  if (!existsSync(resolvedDatabasePath)) throw new Error('Managed project database does not exist');
  const migrationsPath = options.migrationsPath ?? defaultProjectMigrationsPath;
  const projectId = options.projectId ?? defaultProjectId;
  const database = new DatabaseSync(resolvedDatabasePath);
  database.exec('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;');
  try {
    const identity = database.prepare('SELECT project_id,storage_format FROM project_storage_metadata WHERE singleton=1').get();
    const identityCount = database.prepare('SELECT count(*) count FROM project_storage_metadata').get().count;
    if (identityCount !== 1 || identity?.project_id !== projectId || identity?.storage_format !== 1) {
      throw new Error('Editorial infrastructure target is not the requested managed project');
    }
    const migrations = migrationsFrom(migrationsPath);
    if (!migrations.length) throw new Error('No editorial project migrations found');
    const appliedNow = applyMigrations(database, migrations, 'editorial_schema_migrations');
    const profiles = verifyPipelineProfiles(database, { hotfix: options.hotfix === true });
    if (database.prepare('PRAGMA integrity_check').get().integrity_check !== 'ok') throw new Error('Project database integrity check failed');
    if (database.prepare('PRAGMA foreign_key_check').get()) throw new Error('Project database foreign-key check failed');
    return {
      databasePath: resolvedDatabasePath, projectId, appliedNow,
      applied: database.prepare('SELECT version,name,checksum,applied_at FROM editorial_schema_migrations ORDER BY version').all(),
      pipelineId: 'metrichit.editorial.pipeline.v1', profiles,
    };
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  try {
    const values = process.argv.slice(2);
    const updateMode = values.includes('--update-infrastructure');
    const hotfixMode = values.includes('--hotfix');
    const databaseFlag = Math.max(values.indexOf('--db'), values.indexOf('--project-db'));
    const explicitPath = databaseFlag >= 0 ? values[databaseFlag + 1] : values.find((value) => !value.startsWith('--'));
    if (updateMode) {
      const result = updateEditorialInfrastructure(explicitPath ? resolve(explicitPath) : defaultProjectDatabasePath, { hotfix: hotfixMode });
      console.log(`Editorial infrastructure updated: ${result.databasePath}`);
      console.log(`Project migrations: ${result.applied.map(({ version }) => version).join(', ')}`);
      console.log(`Pipeline profiles: ${result.profiles.map(({ profile_id }) => profile_id).join(', ')}`);
      if (hotfixMode) console.log(`Hotfix applied: ${EMPTY_TOPIC_HOTFIX.id}`);
    } else {
      const result = initializeEditorialDatabase(explicitPath ? resolve(explicitPath) : defaultDatabasePath);
      console.log(`Editorial database initialized: ${result.databasePath}`);
      console.log(`Migrations applied: ${result.applied.map(({ version }) => version).join(', ')}`);
    }
  } catch (error) {
    console.error(`init-editorial: ${error.message}`);
    process.exitCode = 1;
  }
}
