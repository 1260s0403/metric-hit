from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def repository_path(*parts: str) -> Path:
    candidate = REPOSITORY_ROOT.joinpath(*parts).resolve()
    if not candidate.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("Path escapes the repository")
    return candidate


MEMORY_DATABASE = repository_path("data", "database", "metrichit.db")
MEMORY_MIGRATIONS = repository_path("data", "database", "migrations")
EDITORIAL_DATABASE = repository_path("data", "editorial", "editorial.sqlite")
EDITORIAL_MIGRATIONS = repository_path("data", "editorial", "migrations")
CURRENT_CONTEXT = repository_path("knowledge", "approved", "current-context.md")
