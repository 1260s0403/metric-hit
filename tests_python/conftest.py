from __future__ import annotations

import os
from pathlib import Path


# pytest's pythonpath setting affects only the current interpreter. Child CLI
# processes must receive the same source root so the suite is reliable before
# or after an editable project install.
SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")
existing = os.environ.get("PYTHONPATH")
os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (SOURCE_ROOT, existing)))


def pytest_configure(config) -> None:
    config.option.basetemp = Path(__file__).resolve().parents[1] / f".pytest-metrichit-{os.getpid()}"
