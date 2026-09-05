DROP TRIGGER editorial_agent_profiles_prevent_update;
DROP TRIGGER editorial_agent_profiles_prevent_delete;
ALTER TABLE editorial_agent_profiles RENAME TO editorial_agent_profiles_007;

CREATE TABLE editorial_agent_profiles (
    profile_id TEXT PRIMARY KEY CHECK (profile_id GLOB 'metrichit.editorial.*.v1'),
    pipeline_id TEXT NOT NULL CHECK (pipeline_id = 'metrichit.editorial.pipeline.v1'),
    stage_order INTEGER NOT NULL CHECK (stage_order BETWEEN 1 AND 5),
    stage_name TEXT NOT NULL CHECK (stage_name IN ('planner', 'architect', 'writer', 'designer', 'validator')),
    capability TEXT NOT NULL CHECK (capability IN ('content-strategy', 'seo-strategy', 'copywriting', 'image', 'compliance-qa')),
    profile_kind TEXT NOT NULL CHECK (profile_kind IN ('subagent', 'internal_filter')),
    isolation_key TEXT NOT NULL UNIQUE,
    execution_mode TEXT NOT NULL DEFAULT 'isolated_dag'
      CHECK (execution_mode IN ('isolated_sequential', 'isolated_dag')),
    policy_json TEXT NOT NULL CHECK (json_valid(policy_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (pipeline_id, stage_order),
    UNIQUE (pipeline_id, stage_name)
) STRICT;

INSERT INTO editorial_agent_profiles
  (profile_id, pipeline_id, stage_order, stage_name, capability, profile_kind,
   isolation_key, execution_mode, policy_json, status, created_at, updated_at)
SELECT profile_id, pipeline_id, stage_order, stage_name, capability, profile_kind,
  isolation_key, 'isolated_dag',
  json_set(policy_json, '$.routing',
    CASE stage_name
      WHEN 'planner' THEN json_object('package','planning','phase','structure_options','owner_selection_gate',json('true'),'output','planning_package')
      WHEN 'architect' THEN json_object('package','planning','phase','selected_structure_spec','depends_on','owner_selected_structure','output','article_spec')
      WHEN 'writer' THEN json_object('depends_on','article_spec','sole_text_assembler',json('true'),'output','article_text')
      WHEN 'designer' THEN json_object('depends_on','article_text_hash','parallel_after','article_text','read_only',json('false'),'output','media_staging','staging_separate',json('true'))
      WHEN 'validator' THEN json_object('depends_on','article_text_hash','parallel_after','article_text','read_only',json('true'),'output','qa_evidence','final_hashes_required',json('true'))
    END),
  status, created_at, updated_at
FROM editorial_agent_profiles_007;

DROP TABLE editorial_agent_profiles_007;

CREATE INDEX editorial_agent_profiles_pipeline_idx
ON editorial_agent_profiles (pipeline_id, status, stage_order);

CREATE TRIGGER editorial_agent_profiles_prevent_update
BEFORE UPDATE ON editorial_agent_profiles
BEGIN
    SELECT RAISE(ABORT, 'editorial agent profiles are migration-controlled');
END;

CREATE TRIGGER editorial_agent_profiles_prevent_delete
BEFORE DELETE ON editorial_agent_profiles
BEGIN
    SELECT RAISE(ABORT, 'editorial agent profiles are migration-controlled');
END;
