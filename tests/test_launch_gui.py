"""The no-console launcher. It runs as a file, not an import, so it is loaded the same way."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "launch_gui.py"


@pytest.fixture
def launch() -> ModuleType:
    spec = importlib.util.spec_from_file_location("launch_gui", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def venv_at(root: Path, launch: ModuleType) -> Path:
    packages = launch.site_packages(root)
    packages.mkdir(parents=True)
    return packages


def test_every_module_it_can_start_exists(launch):
    root = SCRIPT.parents[1]
    for module in launch.MODULES.values():
        assert (root / Path(*module.split("."))).with_suffix(".py").is_file()


def test_add_venv_processes_pth_files(launch, tmp_path, monkeypatch):
    # An editable install is a `.pth` file, so plain `sys.path` would miss the project.
    monkeypatch.setattr(sys, "path", list(sys.path))
    packages = venv_at(tmp_path, launch)
    editable = tmp_path / "src"
    editable.mkdir()
    (packages / "project.pth").write_text(str(editable), encoding="utf-8")

    launch.add_venv(tmp_path)

    assert str(packages) in sys.path
    assert str(editable) in sys.path


def test_a_missing_venv_says_what_to_do(launch, tmp_path):
    with pytest.raises(FileNotFoundError, match="uv sync"):
        launch.add_venv(tmp_path)


def test_the_log_is_overwritten_per_run(launch, tmp_path):
    with launch.open_log(tmp_path, "overlay") as log:
        log.write("first run, much longer")
    with launch.open_log(tmp_path, "overlay") as log:
        log.write("second")
    assert (tmp_path / "logs" / "overlay.log").read_text(encoding="utf-8") == "second"


@pytest.mark.parametrize("argv", [["launch"], ["launch", "nonsense"], ["launch", "a", "b"]])
def test_bad_arguments_start_nothing(launch, monkeypatch, argv):
    monkeypatch.setattr(launch.runpy, "run_module", lambda *a, **k: pytest.fail("started"))
    with pytest.raises(SystemExit, match="usage"):
        launch.main(argv)


@pytest.fixture
def mutexes(launch: ModuleType, monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """`CreateMutexW`'s contract, held in a set: a second create of a name still succeeds,
    and only the last error tells it apart. `WinDLL` exists on Windows alone, and CI is not
    Windows, so every platform takes this stand-in and none of them skips."""
    held: set[str] = set()
    last_error = [0]

    def create_mutex(attributes: None, initial_owner: bool, name: str) -> int:
        last_error[0] = launch.ERROR_ALREADY_EXISTS if name in held else 0
        held.add(name)
        return 1

    kernel32 = SimpleNamespace(CreateMutexW=create_mutex)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(launch.ctypes, "WinDLL", lambda *a, **k: kernel32, raising=False)
    monkeypatch.setattr(launch.ctypes, "get_last_error", lambda: last_error[0], raising=False)
    return held


def test_a_second_instance_is_refused(launch, mutexes):
    assert launch.first_instance("overlay")
    assert not launch.first_instance("overlay")


def test_the_overlay_and_the_collector_do_not_refuse_each_other(launch, mutexes):
    assert launch.first_instance("overlay")
    assert launch.first_instance("collector")


def test_the_mutex_is_per_logon_session(launch, mutexes):
    # `Global\` would let one user's overlay stop another's on a shared machine.
    launch.first_instance("overlay")
    assert mutexes == {"Local\\ProductivityTracker-overlay"}


def test_every_instance_is_first_where_there_is_no_mutex(launch, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert launch.first_instance("overlay")
    assert launch.first_instance("overlay")


def test_a_second_instance_starts_nothing_and_keeps_the_first_ones_log(
    launch, tmp_path, monkeypatch
):
    monkeypatch.setattr(launch, "first_instance", lambda name: False)
    monkeypatch.setattr(launch, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(launch.runpy, "run_module", lambda *a, **k: pytest.fail("started"))

    assert launch.main(["launch", "overlay"]) == 0

    assert not (tmp_path / "logs").exists()


def test_main_logs_then_runs_the_module(launch, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", sys.stderr)  # Restored after main replaces it.
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(launch, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(launch, "first_instance", lambda name: True)
    venv_at(tmp_path, launch)
    ran: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(launch.runpy, "run_module", lambda m, **k: ran.append((m, k)))

    assert launch.main(["launch", "collector"]) == 0

    sys.stderr.close()
    assert ran == [("productivity_tracker.collector", {"run_name": "__main__", "alter_sys": True})]
    assert (tmp_path / "logs" / "collector.log").is_file()
