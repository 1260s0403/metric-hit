import tomllib

from metrichit_os.config import REPOSITORY_ROOT


def test_dependency_groups_are_exact_and_separated():
    configuration = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert configuration["build-system"]["requires"] == ["setuptools==82.0.1"]
    assert configuration["project"]["requires-python"] == ">=3.13,<3.14"
    assert configuration["project"]["dependencies"] == [
        "fastapi==0.141.1",
        "pydantic==2.13.4",
        "uvicorn==0.52.3",
    ]
    assert configuration["project"]["optional-dependencies"]["test"] == [
        "httpx==0.28.1",
        "pytest==9.1.1",
    ]


def test_lock_contains_unique_exact_versions():
    requirements = [
        line.strip()
        for line in (REPOSITORY_ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(requirements) == len(set(requirements))
    assert all("==" in requirement for requirement in requirements)
    assert "setuptools==82.0.1" in requirements
    for direct in (
        "fastapi==0.141.1", "pydantic==2.13.4", "uvicorn==0.52.3",
        "httpx==0.28.1", "pytest==9.1.1",
    ):
        assert direct in requirements
