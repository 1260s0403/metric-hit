from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from .checks import check_editorial_database, check_memory_database
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
from .editorial_store import WorkflowError, initialize_workflow_database
from .editorial_mvp import run_editorial_mvp
from .editorial_workflow import EditorialWorkflowService
from .knowledge_store import KnowledgeError, KnowledgeStore
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
    for name in ("knowledge-add", "knowledge-list", "knowledge-search"):
        command = subparsers.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--kind", choices=("artem", "idea"), required=True)
        command.add_argument("--limit", type=int, default=20)
        if name == "knowledge-add":
            command.add_argument("--text", required=True)
            command.add_argument("--topic", required=True)
            command.add_argument("--tags")
            command.add_argument("--author", default="owner")
            command.add_argument("--source", default="manual")
            command.add_argument("--status", choices=("active", "converted_to_task", "archived"), default="active")
        if name == "knowledge-search":
            command.add_argument("--query", required=True)
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
    database_path = Path(arguments.db)
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
    if arguments.command.startswith("knowledge-"):
        store = KnowledgeStore(database_path)
        if arguments.command == "knowledge-add":
            print_json(store.add(
                kind=arguments.kind, text=arguments.text, topic=arguments.topic,
                tags=arguments.tags, author=arguments.author, source=arguments.source,
                status=arguments.status,
            ))
        elif arguments.command == "knowledge-list":
            print_json(store.list(kind=arguments.kind, limit=arguments.limit))
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
    except (KnowledgeError, WorkflowError, ProviderError, ValidationError, ValueError, sqlite3.Error) as error:
        print_json({"error": type(error).__name__, "message": str(error)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
