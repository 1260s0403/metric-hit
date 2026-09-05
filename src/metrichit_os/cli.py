from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from .checks import check_editorial_database, check_memory_database
from .chat_continuity import ChatContinuityStore
from .editorial_models import (
    AddMaterialVersionInput,
    AddResearchItemInput,
    AddResearchSourceInput,
    CompleteNoPublishInput,
    CreateDailyPlanInput,
    CreateMaterialInput,
    CreateRunInput,
    CreateTopicProposalInput,
    EditorialMvpRunInput,
    PreparePublicationJobInput,
    RecordApprovalDecisionInput,
    RequestApprovalInput,
)
from .editorial_domain import EditorialDomainError, EditorialStore, initialize_editorial_domain
from .editorial_store import WorkflowError, initialize_workflow_database
from .editorial_mvp import run_editorial_mvp
from .editorial_workflow import EditorialWorkflowService
from .knowledge_store import KnowledgeError, KnowledgeStore
from .handoff import HandoffError, HandoffStore, format_handoff
from .operator_panel import run_operator_panel
from .project_scope import DEFAULT_PROJECT_ID
from .project_migration import (
    apply_approved_decision_ownership_batch,
    apply_approved_final_ownership_batch,
    apply_approved_ownership_batch,
    build_migration_plan,
    materialize_metrichit_project,
    migration_plan_summary,
)
from .project_store import ProjectStore
from .task_router import parse_short_task_command, route_project_task
from .project_storage import ProjectStorage
from .runtime import RoutedKnowledgeStore, RuntimeDatabases
from .services import current_context, editorial_status, memory_summary
from .text_providers import ProviderError


COMMANDS: dict[str, Callable[[], dict[str, object]]] = {
    "check-memory": check_memory_database,
    "check-editorial": check_editorial_database,
    "memory-summary": memory_summary,
    "editorial-status": editorial_status,
}

WRITE_COMMANDS = {
    "create-run": (CreateRunInput, "create_run"),
    "add-research-source": (AddResearchSourceInput, "add_research_source"),
    "add-research-item": (AddResearchItemInput, "add_research_item"),
    "create-topic": (CreateTopicProposalInput, "create_topic_proposal"),
    "create-plan": (CreateDailyPlanInput, "create_daily_plan"),
    "create-material": (CreateMaterialInput, "create_material"),
    "add-material-version": (AddMaterialVersionInput, "add_material_version"),
    "request-approval": (RequestApprovalInput, "request_approval"),
    "record-decision": (RecordApprovalDecisionInput, "record_approval_decision"),
    "prepare-publication-job": (PreparePublicationJobInput, "prepare_publication_job"),
    "no-publish": (CompleteNoPublishInput, "complete_no_publish"),
}


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def workflow_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="metrichit-os")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init-editorial-db")
    initialize.add_argument("--db", required=True)
    mvp = subparsers.add_parser("editorial-mvp-run")
    mvp.add_argument("--db", required=True)
    mvp.add_argument("--idempotency-key", required=True)
    mvp.add_argument("--topic", required=True)
    mvp.add_argument("--primary-query", required=True)
    mvp.add_argument("--article-platform", required=True)
    mvp.add_argument("--account-id", required=True)
    mvp.add_argument("--provider", choices=("fake", "openai"), required=True)
    mvp.add_argument("--simulation", action="store_true")
    panel = subparsers.add_parser("operator-panel")
    panel.add_argument("--db", required=True)
    panel.add_argument("--port", type=int, required=True)
    migration_plan = subparsers.add_parser("project-migration-plan")
    migration_plan.add_argument("--db", required=True)
    migration_plan.add_argument("--summary-only", action="store_true")
    ownership_apply = subparsers.add_parser("project-ownership-apply")
    ownership_apply.add_argument("--db", required=True)
    ownership_apply.add_argument("--expected-source-sha256", required=True)
    ownership_apply.add_argument("--expected-manifest-sha256", required=True)
    ownership_apply.add_argument("--rollback-manifest", required=True)
    ownership_apply.add_argument("--verified-backup-set", required=True)
    decision_ownership_apply = subparsers.add_parser("project-decision-ownership-apply")
    decision_ownership_apply.add_argument("--db", required=True)
    decision_ownership_apply.add_argument("--expected-source-sha256", required=True)
    decision_ownership_apply.add_argument("--expected-manifest-sha256", required=True)
    decision_ownership_apply.add_argument("--rollback-manifest", required=True)
    decision_ownership_apply.add_argument("--verified-backup-set", required=True)
    final_ownership_apply = subparsers.add_parser("project-final-ownership-apply")
    final_ownership_apply.add_argument("--db", required=True)
    final_ownership_apply.add_argument("--expected-source-sha256", required=True)
    final_ownership_apply.add_argument("--expected-manifest-sha256", required=True)
    final_ownership_apply.add_argument("--rollback-manifest", required=True)
    final_ownership_apply.add_argument("--verified-backup-set", required=True)
    migration_apply = subparsers.add_parser("metrichit-project-migration-apply")
    migration_apply.add_argument("--db", required=True)
    migration_apply.add_argument("--expected-source-sha256", required=True)
    migration_apply.add_argument("--expected-manifest-sha256", required=True)
    migration_apply.add_argument("--verified-backup-set", required=True)
    migration_apply.add_argument("--migration-manifest", required=True)
    migration_apply.add_argument("--rollback-manifest", required=True)
    migration_apply.add_argument("--replace-existing", action="store_true")
    migration_apply.add_argument("--activate-runtime", action="store_true")
    project_export = subparsers.add_parser("project-export")
    project_export.add_argument("--project-id", required=True)
    project_export.add_argument("--output", required=True)
    project_export.add_argument("--storage-root")
    project_import = subparsers.add_parser("project-import")
    project_import.add_argument("--package", required=True)
    project_import.add_argument("--storage-root")
    editorial_init = subparsers.add_parser("project-editorial-init")
    editorial_init.add_argument("--db", required=True)
    editorial_init.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    editorial_context = subparsers.add_parser("project-editorial-context")
    editorial_context.add_argument("--db", required=True)
    editorial_context.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    editorial_context.add_argument("--direction", choices=("articles", "social"), required=True)
    editorial_context.add_argument("--query", default="")
    editorial_context.add_argument("--topic-id")
    editorial_context.add_argument("--material-id")
    editorial_context.add_argument("--limit", type=int, default=8)
    editorial_transition = subparsers.add_parser("project-editorial-transition")
    editorial_transition.add_argument("--db", required=True)
    editorial_transition.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    editorial_transition.add_argument("--material-id", required=True)
    editorial_transition.add_argument("--to-stage", choices=("plan", "draft", "review"), required=True)
    editorial_transition.add_argument("--actor", required=True)
    editorial_transition.add_argument("--plan-ref")
    editorial_transition.add_argument("--content-ref")
    editorial_transition.add_argument("--review-requested-by")
    editorial_transition.add_argument("--note")
    editorial_audit = subparsers.add_parser("project-editorial-audit")
    editorial_audit.add_argument("--db", required=True)
    editorial_audit.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    editorial_audit.add_argument("--material-id", required=True)
    editorial_publication = subparsers.add_parser("project-editorial-record-publication")
    editorial_publication.add_argument("--db", required=True)
    editorial_publication.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    editorial_publication.add_argument("--idempotency-key", required=True)
    editorial_publication.add_argument("--material-id", required=True)
    editorial_publication.add_argument("--platform", required=True)
    editorial_publication.add_argument("--published-at", required=True)
    editorial_publication.add_argument("--url")
    editorial_publication.add_argument("--owner-confirmed-by")
    handoff_create = subparsers.add_parser("handoff-create")
    handoff_create.add_argument("--db", required=True)
    handoff_input = handoff_create.add_mutually_exclusive_group(required=True)
    handoff_input.add_argument("--data", help="UTF-8 JSON object")
    handoff_input.add_argument("--stdin", action="store_true")
    task_route = subparsers.add_parser("project-task-route")
    task_route.add_argument("--db", required=True)
    task_route.add_argument("--text", required=True)
    task_route.add_argument("--worktree-root", default="tmp")
    transition = subparsers.add_parser("chat-transition")
    transition.add_argument("--db", required=True)
    transition.add_argument("--scope", required=True)
    transition.add_argument("--branch", required=True)
    transition.add_argument("--canonical-worktree", required=True)
    transition.add_argument("--worktree", required=True)
    transition.add_argument("--head", required=True)
    transition.add_argument("--task")
    transition.add_argument("--context-pack")
    transition.add_argument("--dirty-file", action="append", default=[])
    finish = subparsers.add_parser("chat-finish")
    finish.add_argument("--db", required=True)
    finish.add_argument("--scope", required=True)
    finish.add_argument("--branch", required=True)
    finish.add_argument("--canonical-worktree", required=True)
    finish.add_argument("--worktree", required=True)
    finish.add_argument("--head", required=True)
    finish.add_argument("--context-pack", required=True)
    finish.add_argument("--task")
    editorial_lifecycle = subparsers.add_parser("editorial-lifecycle")
    editorial_lifecycle.add_argument("--operation", choices=("stage", "promote", "finish"), required=True)
    editorial_lifecycle.add_argument("--data", required=True, help="UTF-8 JSON object")
    workspace_prepare = subparsers.add_parser("chat-workspace-prepare")
    workspace_prepare.add_argument("--db", required=True)
    workspace_prepare.add_argument("--scope", required=True)
    workspace_prepare.add_argument("--canonical-worktree", required=True)
    workspace_prepare.add_argument("--worktree-root", required=True)
    workspace_prepare.add_argument("--branch")
    workspace_prepare.add_argument("--base")
    workspace_prepare.add_argument("--task")
    workspace_prepare.add_argument("--context-pack")
    parallel_start = subparsers.add_parser("chat-parallel-start")
    parallel_start.add_argument("--db", required=True)
    parallel_start.add_argument("--text", required=True)
    parallel_start.add_argument("--canonical-worktree", required=True)
    parallel_start.add_argument("--worktree-root", required=True)
    parallel_start.add_argument("--base")
    resume = subparsers.add_parser("chat-resume")
    resume.add_argument("--db", required=True)
    resume.add_argument("--text", required=True)
    handoff_next = subparsers.add_parser("handoff-next")
    handoff_next.add_argument("--db", required=True)
    handoff_next.add_argument("--format", choices=("json", "text"), default="json")
    handoff_claim = subparsers.add_parser("handoff-claim")
    handoff_claim.add_argument("--db", required=True)
    handoff_claim.add_argument("--id", required=True)
    handoff_claim.add_argument("--developer", required=True)
    handoff_integrate = subparsers.add_parser("handoff-integrate")
    handoff_integrate.add_argument("--db", required=True)
    handoff_integrate.add_argument("--id", required=True)
    handoff_integrate.add_argument("--developer", required=True)
    handoff_integrate.add_argument("--expected-base", required=True)
    handoff_integrate.add_argument("--current-base", required=True)
    handoff_integrate.add_argument("--conflict-free", action="store_true")
    handoff_complete = subparsers.add_parser("handoff-complete")
    handoff_complete.add_argument("--db", required=True)
    handoff_complete.add_argument("--id", required=True)
    handoff_complete.add_argument("--commit", required=True)
    handoff_complete.add_argument("--developer", required=True)
    coordinator_claim = subparsers.add_parser("handoff-coordinator-claim")
    coordinator_claim.add_argument("--db", required=True)
    coordinator_claim.add_argument("--id", required=True)
    coordinator_claim.add_argument("--coordinator", required=True)
    delegate_child = subparsers.add_parser("handoff-delegate-child")
    delegate_child.add_argument("--db", required=True)
    delegate_child.add_argument("--id", required=True)
    delegate_child.add_argument("--coordinator", required=True)
    delegate_child.add_argument("--worker", required=True)
    delegate_child.add_argument("--data", required=True)
    worker_claim = subparsers.add_parser("handoff-worker-claim")
    worker_claim.add_argument("--db", required=True)
    worker_claim.add_argument("--id", required=True)
    worker_claim.add_argument("--worker", required=True)
    worker_submit = subparsers.add_parser("handoff-worker-submit")
    worker_submit.add_argument("--db", required=True)
    worker_submit.add_argument("--id", required=True)
    worker_submit.add_argument("--worker", required=True)
    worker_submit.add_argument("--data", required=True)
    coordinator_review = subparsers.add_parser("handoff-coordinator-review")
    coordinator_review.add_argument("--db", required=True)
    coordinator_review.add_argument("--id", required=True)
    coordinator_review.add_argument("--coordinator", required=True)
    coordinator_review.add_argument("--decision", choices=("approve", "reject"), required=True)
    coordinator_review.add_argument("--evidence", required=True, help="JSON list")
    integration_result = subparsers.add_parser("handoff-integration-result")
    integration_result.add_argument("--db", required=True)
    integration_result.add_argument("--id", required=True)
    integration_result.add_argument("--developer", required=True)
    integration_result.add_argument("--commit", required=True)
    integration_result.add_argument("--result", required=True)
    strategy_complete = subparsers.add_parser("handoff-strategy-complete")
    strategy_complete.add_argument("--db", required=True)
    strategy_complete.add_argument("--id", required=True)
    strategy_complete.add_argument("--strategy", required=True)
    strategy_complete.add_argument("--parent-pack", required=True)
    strategy_complete.add_argument("--pack-status", choices=("open", "closed"), required=True)
    strategy_complete.add_argument("--clean-delivery", action="store_true")
    dispatch_next = subparsers.add_parser("dispatcher-next")
    dispatch_next.add_argument("--db", required=True)
    dispatch_claim = subparsers.add_parser("dispatcher-claim-next")
    dispatch_claim.add_argument("--db", required=True)
    dispatch_claim.add_argument("--dispatcher", required=True)
    dispatch_thread = subparsers.add_parser("dispatcher-record-thread")
    dispatch_thread.add_argument("--db", required=True)
    dispatch_thread.add_argument("--id", required=True)
    dispatch_thread.add_argument("--thread-id", required=True)
    dispatch_thread.add_argument("--dispatcher", required=True)
    dispatch_complete = subparsers.add_parser("dispatcher-complete")
    dispatch_complete.add_argument("--db", required=True)
    dispatch_complete.add_argument("--id", required=True)
    dispatch_complete.add_argument("--commit", required=True)
    dispatch_complete.add_argument("--result", required=True)
    dispatch_complete.add_argument("--dispatcher", required=True)
    for name in ("knowledge-add", "knowledge-list", "knowledge-search", "knowledge-to-task"):
        command = subparsers.add_parser(name)
        command.add_argument("--db", required=True)
        if name != "knowledge-to-task":
            command.add_argument("--kind", choices=("artem", "idea"), required=True)
            command.add_argument("--limit", type=int, default=20)
        if name in {"knowledge-add", "knowledge-to-task"}:
            command.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
            command.add_argument("--subproject-id")
        if name == "knowledge-add":
            content = command.add_mutually_exclusive_group(required=True)
            content.add_argument("--text")
            content.add_argument("--stdin", action="store_true")
            command.add_argument("--topic", required=True)
            command.add_argument("--tags")
            command.add_argument("--author", default="owner")
            command.add_argument("--source", default="manual")
            command.add_argument("--status", choices=("active", "converted_to_task", "archived"), default="active")
        if name == "knowledge-search":
            command.add_argument("--query", required=True)
        if name == "knowledge-to-task":
            command.add_argument("--id", required=True)
            command.add_argument("--title")
    for name in WRITE_COMMANDS:
        command = subparsers.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--data", required=True, help="UTF-8 JSON object")
    for name in ("show-run", "next-actions", "audit-trail"):
        command = subparsers.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--run-id", required=True)
    return parser


def run_workflow_command(arguments_list: list[str]) -> int:
    parser = workflow_parser()
    arguments = parser.parse_args(arguments_list)
    if arguments.command == "project-export":
        storage = (
            ProjectStorage(Path(arguments.storage_root))
            if arguments.storage_root
            else ProjectStorage()
        )
        print_json(storage.export_package(arguments.project_id, Path(arguments.output)))
        return 0
    if arguments.command == "project-import":
        storage = (
            ProjectStorage(Path(arguments.storage_root))
            if arguments.storage_root
            else ProjectStorage()
        )
        print_json(storage.import_package(Path(arguments.package)))
        return 0
    if arguments.command == "editorial-lifecycle":
        payload = json.loads(arguments.data)
        if not isinstance(payload, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                                for key, value in payload.items()):
            raise ValueError("--data must contain a JSON object with string values")
        allowed = {
            "stage": {"worktree", "key", "source", "target", "staging"},
            "promote": {"staging", "assets", "artifact-qa"},
            "finish": {"staging", "owner-command", "evidence"},
        }[arguments.operation]
        if set(payload) - allowed:
            raise ValueError("editorial lifecycle data contains unsupported fields")
        script = Path(__file__).resolve().parents[2] / "scripts" / "editorial-lifecycle.mjs"
        command = ["node", str(script), arguments.operation]
        for key, value in payload.items():
            command.extend((f"--{key}", value))
        completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode != 0:
            raise WorkflowError(completed.stderr.strip() or "editorial lifecycle command failed")
        print(completed.stdout, end="")
        return 0
    database_path = Path(arguments.db)
    if arguments.command in {"chat-transition", "chat-finish", "chat-resume", "chat-workspace-prepare", "chat-parallel-start"}:
        databases = RuntimeDatabases.resolve(database_path)
        projects = ProjectStore(databases.central, tuple(path for _, path in databases.projects))
        continuity = ChatContinuityStore(databases.central, projects)
        if arguments.command == "chat-transition":
            print_json(continuity.transition(
                scope_label=arguments.scope, branch=arguments.branch,
                canonical_worktree=arguments.canonical_worktree, execution_worktree=arguments.worktree,
                head=arguments.head, task_name=arguments.task, context_pack_id=arguments.context_pack,
                dirty_files=arguments.dirty_file,
            ))
        elif arguments.command == "chat-finish":
            print_json(continuity.prepare_for_new_chat(
                scope_label=arguments.scope, branch=arguments.branch,
                canonical_worktree=arguments.canonical_worktree,
                execution_worktree=arguments.worktree, head=arguments.head,
                task_name=arguments.task, context_pack_id=arguments.context_pack,
            ))
        elif arguments.command == "chat-workspace-prepare":
            print_json(continuity.prepare_workspace(
                scope_label=arguments.scope, canonical_worktree=arguments.canonical_worktree,
                worktree_root=arguments.worktree_root, branch=arguments.branch, base=arguments.base,
                task_name=arguments.task, context_pack_id=arguments.context_pack,
            ))
        elif arguments.command == "chat-parallel-start":
            print_json(continuity.prepare_parallel_start(
                text=arguments.text, canonical_worktree=arguments.canonical_worktree,
                worktree_root=arguments.worktree_root, base=arguments.base,
            ))
        else:
            print_json(continuity.resume(arguments.text))
        return 0
    if arguments.command == "project-task-route":
        databases = RuntimeDatabases.resolve(database_path)
        projects = ProjectStore(databases.central, tuple(path for _, path in databases.projects))
        project_name, task = parse_short_task_command(arguments.text)
        print_json(route_project_task(projects, project_name=project_name, task=task, worktree_root=arguments.worktree_root))
        return 0
    if arguments.command == "project-editorial-init":
        print_json(initialize_editorial_domain(database_path, project_id=arguments.project_id))
        return 0
    if arguments.command == "project-editorial-context":
        print_json(EditorialStore(database_path, project_id=arguments.project_id).context(
            direction=arguments.direction,
            query=arguments.query,
            topic_id=arguments.topic_id,
            material_id=arguments.material_id,
            limit=arguments.limit,
        ))
        return 0
    if arguments.command == "project-editorial-transition":
        print_json(EditorialStore(database_path, project_id=arguments.project_id).transition_material(
            material_id=arguments.material_id,
            to_stage=arguments.to_stage,
            actor=arguments.actor,
            plan_ref=arguments.plan_ref,
            content_ref=arguments.content_ref,
            review_requested_by=arguments.review_requested_by,
            note=arguments.note,
        ))
        return 0
    if arguments.command == "project-editorial-audit":
        print_json({"events": EditorialStore(
            database_path, project_id=arguments.project_id
        ).status_audit(arguments.material_id)})
        return 0
    if arguments.command == "project-editorial-record-publication":
        print_json(EditorialStore(database_path, project_id=arguments.project_id).record_publication(
            idempotency_key=arguments.idempotency_key, material_id=arguments.material_id,
            platform=arguments.platform, published_at=arguments.published_at,
            url=arguments.url, owner_confirmed_by=arguments.owner_confirmed_by,
        ))
        return 0
    if arguments.command == "init-editorial-db":
        print_json(initialize_workflow_database(database_path))
        return 0
    if arguments.command == "editorial-mvp-run":
        request = EditorialMvpRunInput(
            idempotency_key=arguments.idempotency_key,
            topic=arguments.topic,
            primary_query=arguments.primary_query,
            article_platform=arguments.article_platform,
            account_id=arguments.account_id,
            provider=arguments.provider,
            simulation=arguments.simulation,
        )
        print_json(run_editorial_mvp(database_path, request))
        return 0
    if arguments.command == "operator-panel":
        run_operator_panel(database_path, port=arguments.port)
        return 0
    if arguments.command == "project-migration-plan":
        plan = build_migration_plan(database_path)
        print_json(migration_plan_summary(plan) if arguments.summary_only else plan)
        return 0
    if arguments.command == "project-ownership-apply":
        print_json(apply_approved_ownership_batch(
            database_path,
            expected_source_sha256=arguments.expected_source_sha256,
            expected_manifest_sha256=arguments.expected_manifest_sha256,
            rollback_manifest_path=Path(arguments.rollback_manifest),
            verified_backup_set=Path(arguments.verified_backup_set),
        ))
        return 0
    if arguments.command == "project-decision-ownership-apply":
        print_json(apply_approved_decision_ownership_batch(
            database_path,
            expected_source_sha256=arguments.expected_source_sha256,
            expected_manifest_sha256=arguments.expected_manifest_sha256,
            rollback_manifest_path=Path(arguments.rollback_manifest),
            verified_backup_set=Path(arguments.verified_backup_set),
        ))
        return 0
    if arguments.command == "project-final-ownership-apply":
        print_json(apply_approved_final_ownership_batch(
            database_path,
            expected_source_sha256=arguments.expected_source_sha256,
            expected_manifest_sha256=arguments.expected_manifest_sha256,
            rollback_manifest_path=Path(arguments.rollback_manifest),
            verified_backup_set=Path(arguments.verified_backup_set),
        ))
        return 0
    if arguments.command == "metrichit-project-migration-apply":
        print_json(materialize_metrichit_project(
            database_path,
            expected_source_sha256=arguments.expected_source_sha256,
            expected_manifest_sha256=arguments.expected_manifest_sha256,
            verified_backup_set=Path(arguments.verified_backup_set),
            migration_manifest_path=Path(arguments.migration_manifest),
            rollback_manifest_path=Path(arguments.rollback_manifest),
            replace_existing=arguments.replace_existing,
            activate_runtime=arguments.activate_runtime,
        ))
        return 0
    if arguments.command == "handoff-create":
        raw = sys.stdin.read() if arguments.stdin else arguments.data
        payload = json.loads(raw)
        print_json(HandoffStore(database_path).create_approved(payload))
        return 0
    if arguments.command == "handoff-next":
        handoff = HandoffStore(database_path).next()
        if arguments.format == "text":
            print(format_handoff(handoff), end="")
        else:
            print_json({"handoff": handoff})
        return 0
    if arguments.command == "handoff-claim":
        print_json(HandoffStore(database_path).claim(arguments.id, arguments.developer))
        return 0
    if arguments.command == "handoff-integrate":
        print_json(HandoffStore(database_path).begin_integration(
            arguments.id, arguments.developer, arguments.expected_base, arguments.current_base, arguments.conflict_free,
        ))
        return 0
    if arguments.command == "handoff-complete":
        print_json(HandoffStore(database_path).complete(arguments.id, arguments.commit, arguments.developer))
        return 0
    if arguments.command == "handoff-coordinator-claim":
        print_json(HandoffStore(database_path).coordinator_claim(arguments.id, arguments.coordinator))
        return 0
    if arguments.command == "handoff-delegate-child":
        print_json(HandoffStore(database_path).delegate_child(
            arguments.id, arguments.coordinator, arguments.worker, json.loads(arguments.data),
        ))
        return 0
    if arguments.command == "handoff-worker-claim":
        print_json(HandoffStore(database_path).claim_worker(arguments.id, arguments.worker))
        return 0
    if arguments.command == "handoff-worker-submit":
        print_json(HandoffStore(database_path).worker_submit(
            arguments.id, arguments.worker, json.loads(arguments.data),
        ))
        return 0
    if arguments.command == "handoff-coordinator-review":
        print_json(HandoffStore(database_path).coordinator_review(
            arguments.id, arguments.coordinator, arguments.decision, json.loads(arguments.evidence),
        ))
        return 0
    if arguments.command == "handoff-integration-result":
        print_json(HandoffStore(database_path).integration_result(
            arguments.id, arguments.developer, arguments.commit, arguments.result,
        ))
        return 0
    if arguments.command == "handoff-strategy-complete":
        print_json(HandoffStore(database_path).strategy_complete(
            arguments.id, arguments.strategy, arguments.parent_pack, arguments.pack_status, arguments.clean_delivery,
        ))
        return 0
    if arguments.command == "dispatcher-next":
        print_json({"handoff": HandoffStore(database_path).dispatcher_next()})
        return 0
    if arguments.command == "dispatcher-claim-next":
        print_json({"handoff": HandoffStore(database_path).dispatcher_claim_next(arguments.dispatcher)})
        return 0
    if arguments.command == "dispatcher-record-thread":
        print_json(HandoffStore(database_path).dispatcher_record_thread(arguments.id, arguments.thread_id, arguments.dispatcher))
        return 0
    if arguments.command == "dispatcher-complete":
        print_json(HandoffStore(database_path).dispatcher_complete(arguments.id, arguments.commit, arguments.result, arguments.dispatcher))
        return 0
    if arguments.command.startswith("knowledge-"):
        databases = RuntimeDatabases.resolve(database_path)
        store = RoutedKnowledgeStore(databases) if databases.projects else KnowledgeStore(databases.central)
        projects = ProjectStore(databases.central, tuple(path for _, path in databases.projects))
        if arguments.command == "knowledge-add":
            projects.validate_assignment(arguments.project_id, arguments.subproject_id, required=True)
            print_json(store.add(
                kind=arguments.kind, text=sys.stdin.read() if arguments.stdin else arguments.text, topic=arguments.topic,
                tags=arguments.tags, author=arguments.author, source=arguments.source,
                status=arguments.status,
                project_id=arguments.project_id, subproject_id=arguments.subproject_id,
            ))
        elif arguments.command == "knowledge-list":
            print_json(store.list(kind=arguments.kind, limit=arguments.limit))
        elif arguments.command == "knowledge-to-task":
            projects.validate_assignment(arguments.project_id, arguments.subproject_id, required=True)
            print_json(store.to_task(entry_id=arguments.id, title=arguments.title, project_id=arguments.project_id, subproject_id=arguments.subproject_id))
        else:
            print_json(store.search(kind=arguments.kind, query=arguments.query, limit=arguments.limit))
        return 0
    service = EditorialWorkflowService(database_path)
    if arguments.command in WRITE_COMMANDS:
        model_class, method_name = WRITE_COMMANDS[arguments.command]
        payload = json.loads(arguments.data)
        if not isinstance(payload, dict):
            raise ValueError("--data must contain a JSON object")
        request = model_class.model_validate(payload)
        print_json(getattr(service, method_name)(request))
        return 0
    method_name = {"show-run": "show_run", "next-actions": "next_actions", "audit-trail": "audit_trail"}[
        arguments.command
    ]
    print_json(getattr(service, method_name)(arguments.run_id))
    return 0


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in {*COMMANDS, "context"}:
        parser = argparse.ArgumentParser(prog="metrichit-os")
        parser.add_argument("command", choices=[*COMMANDS, "context"])
        arguments = parser.parse_args()
        if arguments.command == "context":
            result = current_context()
            if not result["exists"]:
                parser.error("Current context does not exist")
            print(result["content"], end="")
        else:
            print_json(COMMANDS[arguments.command]())
        return 0
    try:
        return run_workflow_command(sys.argv[1:])
    except (EditorialDomainError, HandoffError, KnowledgeError, WorkflowError, ProviderError, ValidationError, ValueError, sqlite3.Error) as error:
        print_json({"error": type(error).__name__, "message": str(error)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
