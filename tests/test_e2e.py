"""`scripts/e2e.py`, the local tier's runner: what it runs and how it reads the result.

It runs as a file, not an import, so it is loaded the same way. These tests are not in the
tier themselves: they spawn nothing and need nothing but this interpreter.
"""

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "e2e.py"

PASSED = "tests/test_e2e_stack.py::test_a PASSED                      [ 50%]"
FAILED = "tests/test_e2e_stack.py::test_b FAILED                      [100%]"
SKIPPED = "tests/test_tray.py::test_icon SKIPPED (no pillow here)     [100%]"
SUMMARY = "FAILED tests/test_e2e_stack.py::test_b - AssertionError: red"


@pytest.fixture
def e2e() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e2e", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_default_run_deselects_the_tier_and_the_script_selects_it(e2e):
    options = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = options["tool"]["pytest"]["ini_options"]
    assert '-m "not local"' in pytest_options["addopts"]
    assert any(m.startswith("local:") for m in pytest_options["markers"])

    command = e2e.pytest_command("py")
    assert command[:4] == ["py", "-m", "pytest", "tests"]
    assert command[command.index("-m", 2) + 1] == "local"


def test_named_ids_replace_the_whole_suite(e2e):
    command = e2e.pytest_command("py", ["tests/test_e2e_stack.py::test_a"])
    assert "tests" not in command
    assert "tests/test_e2e_stack.py::test_a" in command


def test_the_tier_holds_the_stack_test_and_nothing_outside_the_suite():
    """The script runs `tests/`: a `local` test anywhere else would run nowhere."""
    assert "pytestmark = pytest.mark.local" in (ROOT / "tests" / "test_e2e_stack.py").read_text(
        "utf-8"
    )
    elsewhere = ROOT / "scripts" / "hooks" / "tests"
    assert not [p for p in elsewhere.glob("test_*.py") if "mark.local" in p.read_text("utf-8")]


def check_yaml_hooks() -> list[dict]:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    return [
        hook for repo in config["repos"] for hook in repo["hooks"] if hook["id"] == "check-yaml"
    ]


def test_the_compose_overlay_passes_every_check_yaml_hook_that_selects_it():
    # Compose's `!reset` is a tag a safe loader has no constructor for, so a plain
    # check-yaml refuses the overlay at commit time; the hook that selects it must read
    # it as check-yaml's `--unsafe` does, for syntax alone.
    overlay = "tests/e2e-compose.yml"
    text = (ROOT / overlay).read_text(encoding="utf-8")
    selecting = [
        hook
        for hook in check_yaml_hooks()
        if re.search(hook.get("files", ""), overlay)
        and not re.search(hook.get("exclude", "^$"), overlay)
    ]
    assert selecting, "no check-yaml hook reads the compose overlay"
    for hook in selecting:
        if "--unsafe" in hook.get("args", []):
            list(yaml.parse(text))
        else:
            list(yaml.safe_load_all(text))


def test_venv_python_prefers_the_checkouts_venv(e2e, tmp_path):
    assert e2e.venv_python(tmp_path, "fallback") == "fallback"
    venv = tmp_path / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv.mkdir(parents=True)
    interpreter = venv / ("python.exe" if sys.platform == "win32" else "python")
    interpreter.write_text("", encoding="utf-8")
    assert e2e.venv_python(tmp_path, "fallback") == str(interpreter)


def test_outcomes_reads_every_verbose_result_line(e2e):
    output = "\n".join(["collected 3 items", PASSED, FAILED, SKIPPED, "", SUMMARY])
    assert e2e.outcomes(output) == [
        ("tests/test_e2e_stack.py::test_a", "PASSED", ""),
        ("tests/test_e2e_stack.py::test_b", "FAILED", ""),
        ("tests/test_tray.py::test_icon", "SKIPPED", "no pillow here"),
    ]


def test_failure_lines_are_pytests_summary_lines_alone(e2e):
    error = "ERROR tests/test_e2e_stack.py::test_a - Failed: the Docker daemon is not running"
    output = "\n".join([PASSED, FAILED, "", SUMMARY, error, "  FAILED indented"])
    assert e2e.failure_lines(output) == [SUMMARY, error]


def test_a_green_run_stays_green(e2e):
    assert e2e.verdict(0, PASSED, strict=True) == (0, [])


def test_a_red_run_keeps_pytests_code(e2e):
    assert e2e.verdict(1, f"{PASSED}\n{FAILED}\n{SUMMARY}", strict=False) == (1, [])


@pytest.mark.parametrize(
    ("pytest_code", "output", "expected"),
    [(5, "", 5), (5, "collected 3 items / 3 deselected", 5), (0, SKIPPED, 1)],
)
def test_a_run_that_executed_nothing_is_red(e2e, pytest_code, output, expected):
    code, lines = e2e.verdict(pytest_code, output, strict=False)
    assert code == expected
    assert lines[-1] == "e2e: no local test executed, which is not a pass"


def test_a_skip_is_listed_by_hand_and_fails_under_the_scheduler(e2e):
    output = f"{PASSED}\n{SKIPPED}"
    assert e2e.verdict(0, output, strict=False) == (
        0,
        ["SKIPPED tests/test_tray.py::test_icon - skipped: no pillow here"],
    )
    code, lines = e2e.verdict(0, output, strict=True)
    assert code == 1
    assert lines[0] == "FAILED tests/test_tray.py::test_icon - skipped: no pillow here"


def test_scheduled_reads_the_schedulers_flag(e2e):
    assert e2e.scheduled({"DEVKIT_E2E": "1"})
    assert not e2e.scheduled({"DEVKIT_E2E": ""})
    assert not e2e.scheduled({})


def test_the_artifact_opens_with_every_failure(e2e):
    output = f"{FAILED}\n{SUMMARY}"
    text = e2e.artifact_text(output, ["FAILED tests/test_tray.py::test_icon - skipped: x"])
    assert text.splitlines()[:2] == [SUMMARY, "FAILED tests/test_tray.py::test_icon - skipped: x"]
    assert text.endswith(output)


def test_main_prints_the_verdict_and_writes_the_artifact(e2e, tmp_path, monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout=f"{FAILED}\n{SUMMARY}\n", stderr="")

    monkeypatch.setattr(e2e.subprocess, "run", run)
    monkeypatch.setattr(e2e, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(e2e, "ARTIFACT", tmp_path / "logs" / "e2e-failures.log")
    monkeypatch.delenv("DEVKIT_E2E", raising=False)

    assert e2e.main(["tests/test_e2e_stack.py::test_b"]) == 1
    assert calls[0][3] == "tests/test_e2e_stack.py::test_b"
    assert SUMMARY in capsys.readouterr().out
    assert (tmp_path / "logs" / "e2e-failures.log").read_text("utf-8").startswith(SUMMARY)


def test_main_is_red_when_pytest_ran_nothing(e2e, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        e2e.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 5, stdout="", stderr=""),
    )
    monkeypatch.setattr(e2e, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(e2e, "ARTIFACT", tmp_path / "logs" / "e2e-failures.log")

    assert e2e.main([]) == 5
    assert "no local test executed" in capsys.readouterr().out
