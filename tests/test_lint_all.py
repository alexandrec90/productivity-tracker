"""The lint runner's mypy scoping. It runs as a file, not an import, so it is loaded the same way."""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lint-all.py"


@pytest.fixture
def lint_all() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lint_all", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_this_repo_has_the_two_conftest_roots_the_split_is_for():
    root = SCRIPT.parents[1]
    assert (root / "tests" / "conftest.py").is_file()
    assert (root / "scripts" / "hooks" / "tests" / "conftest.py").is_file()


def test_a_changed_run_never_hands_mypy_the_vendored_hook_tests(lint_all):
    # cbb1017b: `tests/` and `scripts/hooks/tests/` in one mypy run resolved the hook
    # tests' `from conftest import load_module` to `tests/conftest.py`.
    targets = ["tests/test_db.py", "scripts/hooks/tests/test_ship.py", "scripts/launch_gui.py"]
    assert lint_all.mypy_batches(targets) == [["tests/test_db.py", "scripts/launch_gui.py"]]
    assert lint_all.mypy_batches(["scripts/hooks/stop.py", "scripts/sync-devkit.py"]) == []
    assert lint_all.mypy_batches([]) == []


def test_vendored_matches_whole_path_segments_only(lint_all):
    assert lint_all.vendored("scripts/hooks/tests/test_ship.py")
    assert lint_all.vendored("scripts/task_branch.py")
    assert not lint_all.vendored("scripts/hooksmith.py")
    assert not lint_all.vendored("tests/test_db.py")


def test_each_conftest_root_gets_its_own_mypy_run(lint_all, tmp_path, monkeypatch):
    for name in ("tests/conftest.py", "tools/tests/conftest.py", "tests/unit/conftest.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(lint_all, "REPO_ROOT", tmp_path)

    assert lint_all.conftest_root("tests/test_a.py") == "tests"
    assert lint_all.conftest_root("tests/conftest.py") == "tests"
    assert lint_all.conftest_root("tests/unit/test_b.py") == "tests/unit"
    assert lint_all.conftest_root("tools/tests/deep/test_c.py") == "tools/tests"
    assert lint_all.conftest_root("scripts/loose.py") == ""

    targets = ["scripts/loose.py", "tests/test_a.py", "tools/tests/test_c.py", "tests/unit/t.py"]
    assert lint_all.mypy_batches(targets) == [
        ["tests/test_a.py", "scripts/loose.py"],
        ["tools/tests/test_c.py"],
        ["tests/unit/t.py"],
    ]
    assert lint_all.mypy_batches(["scripts/loose.py"]) == [["scripts/loose.py"]]


def test_python_passes_runs_mypy_once_per_batch(lint_all, monkeypatch):
    ran: list[list[str]] = []

    def tool(_name: str, cmd: list[str], _hint: str) -> str:
        ran.append(cmd)
        return ""

    passed = subprocess.CompletedProcess([], 0)
    monkeypatch.setattr(lint_all, "run_tool", tool)
    monkeypatch.setattr(lint_all.subprocess, "run", lambda *a, **k: passed)

    lint_all._python_passes(["tests/test_db.py", "scripts/hooks/tests/test_ship.py"], scoped=True)
    mypy = [cmd[3:] for cmd in ran if cmd[2] == "mypy"]
    assert mypy == [["tests/test_db.py", "--show-error-codes"]]

    ran.clear()
    lint_all._python_passes(["scripts/hooks/stop.py"], scoped=True)
    assert [cmd[2] for cmd in ran] == ["ruff"], "a vendored-only diff runs no mypy at all"
