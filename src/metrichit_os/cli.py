from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from .checks import check_editorial_database, check_memory_database
from .services import current_context, editorial_status, memory_summary


COMMANDS: dict[str, Callable[[], dict[str, object]]] = {
    "check-memory": check_memory_database,
    "check-editorial": check_editorial_database,
    "memory-summary": memory_summary,
    "editorial-status": editorial_status,
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="metrichit-os")
    parser.add_argument("command", choices=[*COMMANDS, "context"])
    arguments = parser.parse_args()
    if arguments.command == "context":
        result = current_context()
        if not result["exists"]:
            parser.error("Current context does not exist")
        print(result["content"], end="")
    else:
        print(json.dumps(COMMANDS[arguments.command](), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
