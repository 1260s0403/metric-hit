PRAGMA foreign_keys = ON;

INSERT INTO scoped_memory_records(
    id, semantic_key, scope_id, layer, record_type, lifecycle_status,
    title, content, source_ref, valid_from, supersedes_id, rule_effect,
    task_types_json, metadata_json, created_at, updated_at
)
SELECT
    'memory:editorial:semantic-core-reference',
    'content.metrichit_semantic_core.reference',
    'scope:subproject:editorial',
    'permanent',
    'fact',
    'active',
    'Семантическое ядро MetricHit — ссылка',
    'Утверждено 145 не-навигационных запросов. Полная taxonomy открывается только по явному запросу editorial/research и читается из authoritative MetricHit project.sqlite.',
    'project://00000000-0000-4000-a000-000000000102/memory_candidates/815f4ed2-1ff9-4187-a19f-e6b4fdbe7069',
    '2026-08-31T10:40:00.000Z',
    NULL,
    NULL,
    '["editorial","research"]',
    '{"reference_type":"approved_memory_candidate","project_id":"00000000-0000-4000-a000-000000000102","candidate_id":"815f4ed2-1ff9-4187-a19f-e6b4fdbe7069","candidate_semantic_key":"content.metrichit_semantic_core","keyword_count":145,"content_sha256":"f63300211663cf88d3097a053c3d5398fe3504ecd29cccecc79e66331fcd4518","data_json_sha256":"cad054878d4e628fae3dfc9cde462454117b16d6cd6072dbf1ce095c30e11e34","authority":"project_sqlite","legacy_duplicate_policy":"audit_only"}',
    '2026-08-31T10:40:00.000Z',
    '2026-08-31T10:40:00.000Z'
WHERE NOT EXISTS (
    SELECT 1 FROM sqlite_master
    WHERE type = 'table' AND name = 'project_storage_metadata'
);
