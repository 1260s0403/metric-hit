PRAGMA foreign_keys = ON;

UPDATE editorial_memory
SET status = 'archived'
WHERE semantic_key IN (
  SELECT superseded.value
  FROM memory_candidates AS policy,
       json_each(policy.data_json, '$.supersedes_editorial_rules') AS superseded
  WHERE policy.status = 'approved'
    AND policy.semantic_key = 'content.editorial_directness_policy'
);
