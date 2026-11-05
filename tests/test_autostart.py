"""The login entries, through a stand-in for `winreg`, which does not exist on CI."""

from pathlib import PureWindowsPath
from typing import Any

import pytest

from productivity_tracker import autostart
from productivity_tracker.autostart import (
    MAX_COMMAND,
    RUN_KEY,
    VALUES,
    disable,
    enable,
    is_enabled,
    launch_command,
    main,
    start,
)


class Key:
    def __enter__(self) -> "Key":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, key_exists: bool = True) -> None:
        self.key_exists = key_exists
        self.values: dict[str, str] = {}

    def OpenKey(self, hive: str, path: str, *args: Any) -> Key:
        assert (hive, path) == ("HKCU", RUN_KEY)
        if not self.key_exists:
            raise FileNotFoundError(path)
        return Key()

    def CreateKey(self, hive: str, path: str) -> Key:
        assert (hive, path) == ("HKCU", RUN_KEY)
        self.key_exists = True
        return Key()

    def QueryValueEx(self, _key: Key, name: str) -> tuple[str, int]:
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, _key: Key, name: str, _zero: int, kind: int, value: str) -> None:
        assert kind == self.REG_SZ
        self.values[name] = value

    def DeleteValue(self, _key: Key, name: str) -> None:
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture
def registry(monkeypatch) -> FakeWinreg:
    fake = FakeWinreg()
    monkeypatch.setattr(autostart, "_winreg", lambda: fake)
    # These tests may themselves run from a worktree, which `enable` refuses.
    monkeypatch.setattr(autostart, "is_disposable", lambda root: False)
    return fake


def test_a_linked_worktree_is_disposable_and_a_clone_is_not(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    assert autostart.is_disposable(tmp_path)

    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    assert not autostart.is_disposable(clone)


def test_enable_refuses_a_worktree_and_writes_nothing(registry, monkeypatch):
    monkeypatch.setattr(autostart, "is_disposable", lambda root: True)
    with pytest.raises(ValueError, match="worktree"):
        enable("overlay")
    assert registry.values == {}


# Windows paths on purpose: these are what the command must come out as, even on Linux CI.
BASE = PureWindowsPath(
    r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none"
)
ROOT = PureWindowsPath(r"C:\Users\Administrator\vs-code\productivity-tracker")


def test_the_command_uses_the_base_pythonw_never_the_venvs():
    command = launch_command("overlay", ROOT, BASE)

    assert command == f'"{BASE}\\pythonw.exe" "{ROOT}\\scripts\\launch_gui.py" overlay'
    assert ".venv" not in command  # uv 0.11.29's venv pythonw is a console program.


def test_the_command_fits_a_run_value_on_a_real_path():
    assert len(launch_command("collector", ROOT, BASE)) <= MAX_COMMAND


def test_a_command_over_the_limit_is_refused():
    with pytest.raises(ValueError, match="over 260"):
        launch_command("overlay", ROOT / ("x" * 300), BASE)


def test_enable_then_disable(registry):
    assert not is_enabled("overlay")

    enable("overlay")
    assert is_enabled("overlay")
    assert registry.values[VALUES["overlay"]].endswith('launch_gui.py" overlay')
    assert not is_enabled("collector")

    disable("overlay")
    assert not is_enabled("overlay")


def test_disabling_what_is_off_is_fine(registry):
    disable("overlay")
    registry.key_exists = False
    disable("overlay")
    assert not is_enabled("overlay")


def test_enable_creates_a_missing_key(registry):
    registry.key_exists = False
    enable("collector")
    assert is_enabled("collector")


def test_start_launches_the_same_command(monkeypatch):
    launched: list[str] = []
    monkeypatch.setattr(autostart.subprocess, "Popen", lambda cmd, **_: launched.append(cmd))
    start("overlay")
    assert launched == [launch_command("overlay")]


def test_the_command_line_enables_what_it_names(registry, capsys):
    assert main(["enable", "overlay"]) == 0
    assert capsys.readouterr().out == "overlay: on at login\n"
    assert not is_enabled("collector")


def test_status_reports_everything_and_is_the_default(registry, capsys):
    enable("collector")
    assert main([]) == 0
    assert capsys.readouterr().out == "overlay: off at login\ncollector: on at login\n"


@pytest.mark.parametrize("argv", [["enable", "nonsense"], ["explode"]])
def test_bad_arguments_change_nothing(registry, capsys, argv):
    assert main(argv) == 2
    assert "usage" in capsys.readouterr().out
    assert registry.values == {}
