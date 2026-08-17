import json
import subprocess
import sys


def run_cli(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "metrichit_os", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_check_commands_are_deterministic_json():
    for command in ("check-memory", "check-editorial", "memory-summary", "editorial-status"):
        first = run_cli(command).stdout
        second = run_cli(command).stdout
        assert first == second
        result = json.loads(first)
        if command in {"check-editorial", "editorial-status"}:
            assert result["state"] == "paused"
            assert result["integrity"] == "not_applicable"
        else:
            assert result["integrity"] == "ok"
        assert "C:\\" not in first


def test_cli_reads_the_approved_context():
    output = run_cli("context").stdout
    assert output.startswith("# MetricHit — текущий рабочий контекст")
    assert "C:\\" not in output
