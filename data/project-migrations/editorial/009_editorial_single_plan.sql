DROP TRIGGER editorial_agent_profiles_prevent_update;
UPDATE editorial_agent_profiles SET policy_json=json_set(policy_json,
  '$.planning', json_object('structure_count',1,'owner_selection_gate',json('false'),'owner_topic_priority',json('true'),'repeatable_h1',json('true')),
  '$.routing', CASE stage_name
    WHEN 'planner' THEN json_object('package','planning','phase','single_internal_structure','owner_selection_gate',json('false'),'output','planning_package')
    WHEN 'architect' THEN json_object('package','planning','phase','selected_structure_spec','depends_on','internal_selected_structure','output','article_spec')
    ELSE json_extract(policy_json,'$.routing') END);
CREATE TRIGGER editorial_agent_profiles_prevent_update
BEFORE UPDATE ON editorial_agent_profiles
BEGIN
  SELECT RAISE(ABORT, 'editorial agent profiles are migration-controlled');
END;
