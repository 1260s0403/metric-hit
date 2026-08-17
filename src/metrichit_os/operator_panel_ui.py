"""Package-local presentation resources for the operator panel."""

from __future__ import annotations

import json
from pathlib import Path


OPERATOR_PANEL_ASSETS = Path(__file__).with_name("operator_panel_assets")
_STARTUP_MARKER = "__OPERATOR_PANEL_STARTUP__"
_VALID_VIEWS = {"overview", "search", "activity", "projects", "artem", "idea", "tasks", "memory"}
_TEMPLATE = OPERATOR_PANEL_ASSETS.joinpath("operator-panel.html").read_text(encoding="utf-8")

if _TEMPLATE.count(_STARTUP_MARKER) != 1:
    raise RuntimeError("operator panel template must contain exactly one startup marker")


def _json_for_html_script(payload: dict[str, object]) -> str:
    """Serialize JSON without allowing data to terminate the script element."""
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _page(token: str, focus_task: str | None, view: str) -> str:
    selected = view if view in _VALID_VIEWS else "overview"
    startup = _json_for_html_script({"token": token, "focus_task": focus_task, "view": selected})
    return _TEMPLATE.replace(_STARTUP_MARKER, startup, 1)
