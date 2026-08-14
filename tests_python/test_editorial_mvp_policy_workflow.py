import json
import subprocess


def run_node(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", *arguments], check=True, capture_output=True, text=True, encoding="utf-8"
    )


def test_editorial_mvp_policy_workflow_is_idempotent(tmp_path):
    database = tmp_path / "memory.sqlite"
    run_node("scripts/init-memory.mjs", str(database))
    first = run_node("scripts/apply-editorial-mvp-speed-and-scalability-policy.mjs", str(database))
    second = run_node("scripts/apply-editorial-mvp-speed-and-scalability-policy.mjs", str(database))
    assert '"sources":1' in first.stdout
    assert '"candidates":1' in first.stdout
    assert '"sources":0' in second.stdout
    assert '"candidates":0' in second.stdout

    query = """
      import { DatabaseSync } from 'node:sqlite';
      const db = new DatabaseSync(process.argv[1], { readOnly: true });
      const rows = db.prepare(`
        SELECT c.semantic_key, c.status, c.type, c.reviewed_by,
               s.type AS source_type, d.status AS document_status,
               dv.status AS version_status, dv.version
        FROM memory_candidates c
        JOIN sources s ON s.id=c.source_id
        JOIN documents d ON d.source_id=s.id
        JOIN document_versions dv ON dv.document_id=d.id
        WHERE c.semantic_key='editorial.mvp_speed_and_scalability_policy'
      `).all();
      console.log(JSON.stringify(rows)); db.close();
    """
    rows = json.loads(run_node("--input-type=module", "-e", query, str(database)).stdout)
    assert rows == [{
        "semantic_key": "editorial.mvp_speed_and_scalability_policy",
        "status": "approved",
        "type": "decision",
        "reviewed_by": "owner",
        "source_type": "owner_decision",
        "document_status": "active",
        "version_status": "active",
        "version": 1,
    }]
