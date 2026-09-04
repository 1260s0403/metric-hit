PRAGMA foreign_keys = ON;

CREATE TABLE editorial_agent_profiles (
    profile_id TEXT PRIMARY KEY CHECK (profile_id GLOB 'metrichit.editorial.*.v1'),
    pipeline_id TEXT NOT NULL CHECK (pipeline_id = 'metrichit.editorial.pipeline.v1'),
    stage_order INTEGER NOT NULL CHECK (stage_order BETWEEN 1 AND 5),
    stage_name TEXT NOT NULL CHECK (stage_name IN ('planner', 'architect', 'writer', 'designer', 'validator')),
    capability TEXT NOT NULL CHECK (capability IN ('content-strategy', 'seo-strategy', 'copywriting', 'image', 'compliance-qa')),
    profile_kind TEXT NOT NULL CHECK (profile_kind IN ('subagent', 'internal_filter')),
    isolation_key TEXT NOT NULL UNIQUE,
    execution_mode TEXT NOT NULL DEFAULT 'isolated_sequential'
      CHECK (execution_mode = 'isolated_sequential'),
    policy_json TEXT NOT NULL CHECK (json_valid(policy_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (pipeline_id, stage_order),
    UNIQUE (pipeline_id, stage_name)
) STRICT;

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

INSERT INTO editorial_agent_profiles
  (profile_id, pipeline_id, stage_order, stage_name, capability, profile_kind,
   isolation_key, execution_mode, policy_json, status)
VALUES
  ('metrichit.editorial.planner.v1', 'metrichit.editorial.pipeline.v1', 1, 'planner', 'content-strategy', 'subagent',
   'editorial.pipeline.v1.stage.1.planner', 'isolated_sequential',
   '{"semantic_core":{"source":"content.metrichit_semantic_core","keyword_count":302,"selection":"full_current_approved_non_navigation"},"zonal_distribution":{"applies_only_to":["new_articles","new_longreads"],"excluded_platforms":["telegram"],"h1":"shortest_base_query_2_3_words","h2":"commercial_modifiers_buy_order_price","lsi":{"role":"non_targeted_professional_lexicon","outside_core_allowed":true,"allowed_zones":["h3","unordered_lists"],"prohibited_zones":["h1","h2"]}},"geo_gate":{"cluster":"geo_candidates_after_demand_validation","keyword_count":37,"required_execution_card_flag":"geo_demand_owner_confirmed","required_value":true,"without_flag":"fail_closed"}}', 'active'),
  ('metrichit.editorial.architect.v1', 'metrichit.editorial.pipeline.v1', 2, 'architect', 'seo-strategy', 'subagent',
   'editorial.pipeline.v1.stage.2.architect', 'isolated_sequential',
   '{"semantic_core":{"source":"content.metrichit_semantic_core","keyword_count":302,"selection":"full_current_approved_non_navigation"},"zonal_distribution":{"applies_only_to":["new_articles","new_longreads"],"excluded_platforms":["telegram"],"h1":"shortest_base_query_2_3_words","h2":"commercial_modifiers_buy_order_price","lsi":{"role":"non_targeted_professional_lexicon","outside_core_allowed":true,"allowed_zones":["h3","unordered_lists"],"prohibited_zones":["h1","h2"]}},"geo_gate":{"cluster":"geo_candidates_after_demand_validation","keyword_count":37,"required_execution_card_flag":"geo_demand_owner_confirmed","required_value":true,"without_flag":"fail_closed"}}', 'active'),
  ('metrichit.editorial.writer.v1', 'metrichit.editorial.pipeline.v1', 3, 'writer', 'copywriting', 'subagent',
   'editorial.pipeline.v1.stage.3.writer', 'isolated_sequential',
   '{"semantic_core":{"source":"content.metrichit_semantic_core","keyword_count":302,"selection":"full_current_approved_non_navigation"},"zonal_distribution":{"applies_only_to":["new_articles","new_longreads"],"excluded_platforms":["telegram"],"h1":"shortest_base_query_2_3_words","h2":"commercial_modifiers_buy_order_price","lsi":{"role":"non_targeted_professional_lexicon","outside_core_allowed":true,"allowed_zones":["h3","unordered_lists"],"prohibited_zones":["h1","h2"]}},"geo_gate":{"cluster":"geo_candidates_after_demand_validation","keyword_count":37,"required_execution_card_flag":"geo_demand_owner_confirmed","required_value":true,"without_flag":"fail_closed"}}', 'active'),
  ('metrichit.editorial.designer.v1', 'metrichit.editorial.pipeline.v1', 4, 'designer', 'image', 'subagent',
   'editorial.pipeline.v1.stage.4.designer', 'isolated_sequential',
   '{"semantic_core":{"source":"content.metrichit_semantic_core","keyword_count":302,"selection":"full_current_approved_non_navigation"},"zonal_distribution":{"applies_only_to":["new_articles","new_longreads"],"excluded_platforms":["telegram"],"h1":"shortest_base_query_2_3_words","h2":"commercial_modifiers_buy_order_price","lsi":{"role":"non_targeted_professional_lexicon","outside_core_allowed":true,"allowed_zones":["h3","unordered_lists"],"prohibited_zones":["h1","h2"]}},"geo_gate":{"cluster":"geo_candidates_after_demand_validation","keyword_count":37,"required_execution_card_flag":"geo_demand_owner_confirmed","required_value":true,"without_flag":"fail_closed"}}', 'active'),
  ('metrichit.editorial.validator.v1', 'metrichit.editorial.pipeline.v1', 5, 'validator', 'compliance-qa', 'internal_filter',
   'editorial.pipeline.v1.stage.5.validator', 'isolated_sequential',
   '{"semantic_core":{"source":"content.metrichit_semantic_core","keyword_count":302,"selection":"full_current_approved_non_navigation"},"zonal_distribution":{"applies_only_to":["new_articles","new_longreads"],"excluded_platforms":["telegram"],"h1":"shortest_base_query_2_3_words","h2":"commercial_modifiers_buy_order_price","lsi":{"role":"non_targeted_professional_lexicon","outside_core_allowed":true,"allowed_zones":["h3","unordered_lists"],"prohibited_zones":["h1","h2"]}},"geo_gate":{"cluster":"geo_candidates_after_demand_validation","keyword_count":37,"required_execution_card_flag":"geo_demand_owner_confirmed","required_value":true,"without_flag":"fail_closed"}}', 'active');
