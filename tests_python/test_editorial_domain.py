from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from metrichit_os.editorial_domain import (
    EditorialDomainError,
    EditorialStore,
    check_editorial_domain,
    initialize_editorial_domain,
)
from metrichit_os import cli
from metrichit_os.project_scope import DEFAULT_PROJECT_ID


OTHER_PROJECT = "20000000-0000-4000-a000-000000000002"


def project_database(tmp_path: Path, project_id: str = DEFAULT_PROJECT_ID) -> Path:
    path = tmp_path / project_id / "project.sqlite"
    path.parent.mkdir(parents=True)
    subprocess.run(
        ["node", "scripts/init-memory.mjs", str(path)],
        check=True,
        capture_output=True,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE project_storage_metadata ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "project_id TEXT NOT NULL UNIQUE,storage_format INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO project_storage_metadata VALUES(1,?,1)", (project_id,)
        )
    return path


def test_migration_is_project_local_seeded_and_idempotent(tmp_path: Path) -> None:
    database = project_database(tmp_path)
    with sqlite3.connect(database) as connection:
        expected_seed_count = connection.execute(
            "SELECT count(DISTINCT semantic_key) FROM memory_candidates "
            "WHERE status='approved' AND (semantic_key LIKE 'editorial.%' "
            "OR semantic_key LIKE 'content.%' OR semantic_key LIKE 'publication.%') "
            "AND semantic_key NOT IN (SELECT value FROM memory_candidates policy, "
            "json_each(policy.data_json, '$.supersedes_editorial_rules') "
            "WHERE policy.status='approved' "
            "AND policy.semantic_key='content.editorial_directness_policy')"
        ).fetchone()[0]
        expected_archived_count = connection.execute(
            "SELECT count(DISTINCT candidate.semantic_key) "
            "FROM memory_candidates candidate "
            "WHERE candidate.status='approved' AND candidate.semantic_key IN ("
            "SELECT value FROM memory_candidates policy, "
            "json_each(policy.data_json, '$.supersedes_editorial_rules') "
            "WHERE policy.status='approved' "
            "AND policy.semantic_key='content.editorial_directness_policy')"
        ).fetchone()[0]
    before = initialize_editorial_domain(database)
    second = initialize_editorial_domain(database)

    assert before["applied_now"] == [1, 2, 3, 4, 5, 6, 7]
    assert second["applied_now"] == []
    assert second["counts"]["memory"] == expected_seed_count
    assert check_editorial_domain(database)["integrity"] == "ok"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT count(*) FROM editorial_schema_migrations"
        ).fetchone()[0] == 7
        profiles = connection.execute(
            "SELECT profile_id,stage_order,capability,profile_kind,execution_mode,policy_json "
            "FROM editorial_agent_profiles ORDER BY stage_order"
        ).fetchall()
        assert [(row[0], row[1], row[2], row[3]) for row in profiles] == [
            ("metrichit.editorial.planner.v1", 1, "content-strategy", "subagent"),
            ("metrichit.editorial.architect.v1", 2, "seo-strategy", "subagent"),
            ("metrichit.editorial.writer.v1", 3, "copywriting", "subagent"),
            ("metrichit.editorial.designer.v1", 4, "image", "subagent"),
            ("metrichit.editorial.validator.v1", 5, "compliance-qa", "internal_filter"),
        ]
        for row in profiles:
            policy = json.loads(row[5])
            assert row[4] == "isolated_sequential"
            assert policy["semantic_core"]["keyword_count"] == 302
            assert policy["zonal_distribution"]["applies_only_to"] == ["new_articles", "new_longreads"]
            assert policy["zonal_distribution"]["lsi"]["allowed_zones"] == ["h3", "unordered_lists"]
            assert policy["zonal_distribution"]["lsi"]["role"] == "non_targeted_professional_lexicon"
            assert policy["geo_gate"]["keyword_count"] == 37
            assert policy["geo_gate"]["required_execution_card_flag"] == "geo_demand_owner_confirmed"
        assert connection.execute(
            "SELECT count(*) FROM editorial_memory WHERE status='archived'"
        ).fetchone()[0] == expected_archived_count


def test_wrong_project_identity_and_modified_migration_fail_closed(tmp_path: Path) -> None:
    database = project_database(tmp_path)
    with pytest.raises(EditorialDomainError, match="requested managed project"):
        initialize_editorial_domain(database, project_id=OTHER_PROJECT)

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    source = Path("data/project-migrations/editorial/001_editorial_domain.sql")
    target = migrations / source.name
    target.write_bytes(source.read_bytes())
    initialize_editorial_domain(database, migrations_path=migrations)
    target.write_text(target.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8")
    with pytest.raises(EditorialDomainError, match="modified"):
        initialize_editorial_domain(database, migrations_path=migrations)


def test_v2_upgrade_classifies_existing_materials_without_data_loss(tmp_path: Path) -> None:
    database = project_database(tmp_path)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    canonical = Path("data/project-migrations/editorial")
    for name in ("001_editorial_domain.sql", "002_archive_superseded_rules.sql"):
        (migrations / name).write_bytes((canonical / name).read_bytes())
    initialize_editorial_domain(database, migrations_path=migrations)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO editorial_topics(id,idempotency_key,title,primary_intent) VALUES(?,?,?,?)",
            ("10000000-0000-4000-a000-000000000001", "legacy-topic", "Legacy", "education"),
        )
        connection.execute(
            "INSERT INTO editorial_materials(id,idempotency_key,topic_id,material_type,title) VALUES(?,?,?,?,?)",
            ("10000000-0000-4000-a000-000000000002", "legacy-article",
             "10000000-0000-4000-a000-000000000001", "article", "Legacy article"),
        )
        connection.execute(
            "INSERT INTO editorial_materials(id,idempotency_key,topic_id,parent_material_id,material_type,title) "
            "VALUES(?,?,?,?,?,?)",
            ("10000000-0000-4000-a000-000000000003", "legacy-post",
             "10000000-0000-4000-a000-000000000001",
             "10000000-0000-4000-a000-000000000002", "telegram_post", "Legacy post"),
        )
    for name in (
        "003_editorial_directions.sql", "004_editorial_direction_integrity.sql",
        "005_editorial_material_workflow.sql", "006_editorial_legacy_workflow_compatibility.sql",
    ):
        (migrations / name).write_bytes((canonical / name).read_bytes())

    upgraded = initialize_editorial_domain(database, migrations_path=migrations)
    replay = initialize_editorial_domain(database, migrations_path=migrations)

    assert upgraded["applied_now"] == [3, 4, 5, 6]
    assert replay["applied_now"] == []
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT material_type,direction FROM editorial_materials ORDER BY material_type"
        ).fetchall() == [("article", "articles"), ("telegram_post", "social")]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_registry_links_article_derivatives_publication_and_results(tmp_path: Path) -> None:
    database = project_database(tmp_path)
    initialize_editorial_domain(database)
    store = EditorialStore(database)
    topic = store.create_topic(
        idempotency_key="topic-pf-guide",
        title="Гайд по ПФ",
        primary_intent="обучение",
        primary_query="накрутка пф",
        cluster_name="education",
        priority=80,
    )
    assert store.create_topic(
        idempotency_key="topic-pf-guide",
        title="Гайд по ПФ",
        primary_intent="обучение",
        primary_query="накрутка пф",
        cluster_name="education",
        priority=80,
    )["idempotent_replay"] is True
    article = store.create_material(
        idempotency_key="article-pf-guide",
        topic_id=topic["id"],
        material_type="article",
        title="Накрутка ПФ: практический гайд",
        content_ref="work/articles/drafts/pf-guide.md",
        direction="articles",
    )
    telegram = store.create_material(
        idempotency_key="telegram-pf-guide",
        topic_id=topic["id"],
        parent_material_id=article["id"],
        material_type="telegram_post",
        title="Короткий гайд по ПФ",
        direction="social",
    )
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="cannot invalidate"):
            connection.execute(
                "UPDATE editorial_materials SET material_type='brief' WHERE id=?",
                (article["id"],),
            )
    with pytest.raises(sqlite3.IntegrityError, match="articles parent"):
        store.create_material(
            idempotency_key="bad-derived",
            topic_id=topic["id"],
            parent_material_id=telegram["id"],
            material_type="vk_post",
            title="Invalid derivative",
        )

    with pytest.raises(EditorialDomainError, match="owner_confirmed_by"):
        store.record_publication(
            idempotency_key="telegram-publication",
            material_id=telegram["id"],
            platform="telegram",
            published_at="2026-08-28T12:00:00Z",
        )
    store.transition_material(
        material_id=telegram["id"], to_stage="plan", actor="editor",
        plan_ref="work/social/plans/pf-guide.md",
    )
    store.transition_material(
        material_id=telegram["id"], to_stage="draft", actor="writer",
        content_ref="work/social/drafts/pf-guide.md",
    )
    store.transition_material(
        material_id=telegram["id"], to_stage="review", actor="writer",
        review_requested_by="owner",
    )
    publication = store.record_publication(
        idempotency_key="telegram-publication",
        material_id=telegram["id"],
        platform="telegram",
        published_at="2026-08-28T12:00:00Z",
        url="https://t.me/mtr_hit/100",
        account_ref="metric-hit-main",
    )
    result = store.record_result(
        idempotency_key="telegram-views-day-1",
        publication_id=publication["id"],
        metric_name="views",
        metric_value=125,
        unit="count",
        observed_at="2026-08-29T12:00:00Z",
        source="manual",
    )

    assert publication["confirmation_kind"] == "verified_url"
    assert result["metric_value"] == 125.0
    assert store.status_audit(telegram["id"])[-1]["to_stage"] == "result"
    context = store.context(direction="social", query="ПФ", topic_id=topic["id"], limit=5)
    assert context["scope"] == "editorial"
    assert context["direction"] == "social"
    assert {item["id"] for item in context["materials"]} == {
        article["id"], telegram["id"],
    }
    assert context["publications"][0]["id"] == publication["id"]
    assert context["results"][0]["id"] == result["id"]
    assert len(context["memory"]) <= 5
    assert telegram["direction"] == "social"
    assert article["direction"] == "articles"

    articles = store.context(direction="articles", query="ПФ", topic_id=topic["id"], limit=5)
    assert {item["id"] for item in articles["materials"]} == {article["id"]}
    assert articles["publications"] == []


def test_export_import_preserves_editorial_schema_and_content(tmp_path: Path) -> None:
    from metrichit_os.project_storage import ProjectStorage

    source_root = tmp_path / "source"
    source = source_root / DEFAULT_PROJECT_ID / "project.sqlite"
    source.parent.mkdir(parents=True)
    fixture = project_database(tmp_path / "fixture")
    with sqlite3.connect(fixture) as source_connection, sqlite3.connect(source) as target_connection:
        source_connection.backup(target_connection)
    initialize_editorial_domain(source)
    store = EditorialStore(source)
    store.create_topic(
        idempotency_key="portable-topic",
        title="Portable",
        primary_intent="commercial",
    )
    package = tmp_path / "editorial-project.mhproject"
    ProjectStorage(source_root).export_package(DEFAULT_PROJECT_ID, package)
    imported = ProjectStorage(tmp_path / "target").import_package(package)

    assert imported["imported"] is True
    target = Path(imported["database"])
    assert check_editorial_domain(target)["counts"]["topics"] == 1
    with sqlite3.connect(target) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_context_is_bounded_instead_of_loading_the_archive(tmp_path: Path) -> None:
    database = project_database(tmp_path)
    initialize_editorial_domain(database)
    store = EditorialStore(database)
    for index in range(30):
        store.create_topic(
            idempotency_key=f"topic-{index}",
            title=f"Topic {index}",
            primary_intent="education",
            priority=index,
        )
    context = store.context(direction="articles", query="Topic", limit=4)
    assert context["totals"]["topics"] == 30
    assert len(context["topics"]) == 4
    assert context["limit_per_section"] == 4


def test_migration_checksum_is_stable() -> None:
    migration = Path("data/project-migrations/editorial/001_editorial_domain.sql")
    assert len(hashlib.sha256(migration.read_bytes()).hexdigest()) == 64


def test_cli_initializes_and_reads_bounded_context(tmp_path: Path, capsys) -> None:
    database = project_database(tmp_path)
    assert cli.run_workflow_command([
        "project-editorial-init", "--db", str(database),
    ]) == 0
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["project_id"] == DEFAULT_PROJECT_ID
    assert cli.run_workflow_command([
        "project-editorial-context", "--db", str(database), "--direction", "articles",
        "--query", "ПФ", "--limit", "3",
    ]) == 0
    context = json.loads(capsys.readouterr().out)
    assert context["scope"] == "editorial"
    assert context["direction"] == "articles"
    assert len(context["memory"]) <= 3

    store = EditorialStore(database)
    topic = store.create_topic(
        idempotency_key="cli-workflow-topic", title="CLI workflow",
        primary_intent="education",
    )
    material = store.create_material(
        idempotency_key="cli-workflow-material", topic_id=topic["id"],
        material_type="article", title="CLI workflow article",
    )
    assert cli.run_workflow_command([
        "project-editorial-transition", "--db", str(database),
        "--material-id", material["id"], "--to-stage", "plan",
        "--actor", "strategist", "--plan-ref", "work/plan.md",
    ]) == 0
    transitioned = json.loads(capsys.readouterr().out)
    assert transitioned["workflow_stage"] == "plan"
    assert cli.run_workflow_command([
        "project-editorial-audit", "--db", str(database),
        "--material-id", material["id"],
    ]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert [event["to_stage"] for event in audit["events"]] == ["idea", "plan"]


def test_cli_records_owner_confirmed_publication(tmp_path: Path, capsys) -> None:
    database = project_database(tmp_path)
    initialize_editorial_domain(database)
    store = EditorialStore(database)
    topic = store.create_topic(idempotency_key="publication-topic", title="Публикация", primary_intent="education")
    material = store.create_material(idempotency_key="publication-material", topic_id=topic["id"], material_type="article", title="Статья для панели")
    store.transition_material(material_id=material["id"], to_stage="plan", actor="editor", plan_ref="work/plan.md")
    store.transition_material(material_id=material["id"], to_stage="draft", actor="editor", content_ref="work/article.md")
    store.transition_material(material_id=material["id"], to_stage="review", actor="editor", review_requested_by="owner")
    assert cli.run_workflow_command([
        "project-editorial-record-publication", "--db", str(database),
        "--idempotency-key", "publication-panel-1", "--material-id", material["id"],
        "--platform", "Oborot", "--published-at", "2026-09-03T10:00:00Z",
        "--url", "https://example.test/article",
    ]) == 0
    publication = json.loads(capsys.readouterr().out)
    assert publication["confirmation_kind"] == "verified_url"
    store.remember(
        semantic_key="publication.semantics.panel-test",
        category="platform",
        title="Семантика публикации",
        content="первый ключ\nвторой ключ",
        source_ref="https://example.test/article",
        direction="articles",
    )
    projection = store.publications_projection()
    assert projection["platforms"][0]["publications"][0] == {
        "title": "Статья для панели", "published_at": "2026-09-03T10:00:00Z",
        "url": "https://example.test/article", "status": "Ссылка проверена",
        "semantics": ["первый ключ", "второй ключ"],
    }


def test_direction_scopes_memory_and_rejects_type_mismatches(tmp_path: Path) -> None:
    database = project_database(tmp_path)
    initialize_editorial_domain(database)
    store = EditorialStore(database)
    store.remember(
        semantic_key="editorial.shared",
        category="rule",
        title="Shared",
        content="Shared rule",
        direction="common",
    )
    store.remember(
        semantic_key="editorial.social-only",
        category="platform",
        title="Social only",
        content="Social rule",
        direction="social",
    )
    topic = store.create_topic(
        idempotency_key="social-topic",
        title="Standalone social topic",
        primary_intent="engagement",
        direction="social",
    )
    social = store.create_material(
        idempotency_key="standalone-social",
        topic_id=topic["id"],
        material_type="telegram_post",
        title="Standalone post",
        direction="social",
    )

    with pytest.raises(sqlite3.IntegrityError, match="topic workflow"):
        store.create_material(
            idempotency_key="wrong-topic-direction",
            topic_id=topic["id"],
            material_type="brief",
            title="Wrongly routed brief",
            direction="articles",
        )

    with pytest.raises(sqlite3.IntegrityError, match="requires articles direction"):
        store.create_material(
            idempotency_key="bad-article-direction",
            topic_id=topic["id"],
            material_type="article",
            title="Bad article",
            direction="social",
        )
    with pytest.raises(EditorialDomainError, match="direction must be"):
        store.context(direction="video")

    social_context = store.context(direction="social", limit=10)
    articles_context = store.context(direction="articles", limit=10)
    assert {item["semantic_key"] for item in social_context["memory"]} >= {
        "editorial.shared", "editorial.social-only",
    }
    assert "editorial.social-only" not in {
        item["semantic_key"] for item in articles_context["memory"]
    }
    assert {item["id"] for item in social_context["materials"]} == {social["id"]}
    assert articles_context["materials"] == []


@pytest.mark.parametrize(
    ("direction", "material_type"),
    (("articles", "article"), ("social", "telegram_post")),
)
def test_material_workflow_is_strict_audited_and_requires_boundary_fields(
    tmp_path: Path, direction: str, material_type: str,
) -> None:
    database = project_database(tmp_path)
    initialize_editorial_domain(database)
    store = EditorialStore(database)
    topic = store.create_topic(
        idempotency_key=f"{direction}-workflow-topic",
        title=f"{direction} workflow",
        primary_intent="education",
        direction=direction,
    )
    material = store.create_material(
        idempotency_key=f"{direction}-workflow-material",
        topic_id=topic["id"],
        material_type=material_type,
        title=f"{direction} workflow material",
        direction=direction,
    )
    assert material["workflow_stage"] == "idea"
    with pytest.raises(EditorialDomainError, match="invalid editorial workflow transition"):
        store.transition_material(
            material_id=material["id"], to_stage="draft", actor="writer",
            content_ref="work/draft.md",
        )
    with pytest.raises(EditorialDomainError, match="plan_ref"):
        store.transition_material(material_id=material["id"], to_stage="plan", actor="strategist")
    store.transition_material(
        material_id=material["id"], to_stage="plan", actor="strategist",
        plan_ref="work/plan.md",
    )
    with pytest.raises(EditorialDomainError, match="content_ref"):
        store.transition_material(material_id=material["id"], to_stage="draft", actor="writer")
    store.transition_material(
        material_id=material["id"], to_stage="draft", actor="writer",
        content_ref="work/draft.md",
    )
    with pytest.raises(EditorialDomainError, match="review_requested_by"):
        store.transition_material(material_id=material["id"], to_stage="review", actor="writer")
    store.transition_material(
        material_id=material["id"], to_stage="review", actor="writer",
        review_requested_by="owner",
    )
    publication = store.record_publication(
        idempotency_key=f"{direction}-workflow-publication",
        material_id=material["id"], platform=direction,
        published_at="2026-08-28T12:00:00Z",
        owner_confirmed_by="owner",
    )
    store.record_result(
        idempotency_key=f"{direction}-workflow-result",
        publication_id=publication["id"], metric_name="views",
        metric_value=1, unit="count", observed_at="2026-08-29T12:00:00Z",
        source="manual",
    )
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM editorial_status_audit WHERE material_id=?", (material["id"],)
            )
    assert [event["to_stage"] for event in store.status_audit(material["id"])] == [
        "idea", "plan", "draft", "review", "published", "result",
    ]
