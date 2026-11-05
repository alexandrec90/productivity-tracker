"""Start the overlay and the collector at login, with no console (Windows).

    python -m productivity_tracker.autostart enable overlay collector
    python -m productivity_tracker.autostart disable overlay
    python -m productivity_tracker.autostart start overlay      # the same launch, right now
    python -m productivity_tracker.autostart status

Each is a value under the current user's `Run` key, so it needs no admin rights and shows up
in Windows' own Startup apps list. The command is built by whichever interpreter runs this,
so it points at this checkout; `scripts/launch_gui.py` says why it is not the venv's pythonw.
"""

import importlib
import subprocess
import sys
from pathlib import Path, PurePath
from typing import Any

from productivity_tracker.config import REPO_ROOT

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUES = {
    "overlay": "ProductivityTrackerOverlay",
    "collector": "ProductivityTrackerCollector",
}
# Windows documents this limit for a `Run` value and does not enforce it when writing, so
# going over it would only show up as nothing starting at the next login.
MAX_COMMAND = 260


def _winreg() -> Any:
    # Through importlib so the module loads on the Linux server and CI, and so a test can
    # hand it a stand-in.
    return importlib.import_module("winreg")


def launch_command(
    name: str, root: PurePath = REPO_ROOT, base: PurePath = Path(sys.base_prefix)
) -> str:
    command = f'"{base / "pythonw.exe"}" "{root / "scripts" / "launch_gui.py"}" {name}'
    if len(command) > MAX_COMMAND:
        raise ValueError(f"command is {len(command)} characters, over {MAX_COMMAND}: {command}")
    return command


def is_disposable(root: Path) -> bool:
    """A linked git worktree, whose `.git` is a file: it gets cleaned up, and a login entry
    pointing into it would then start nothing and log nothing."""
    return (root / ".git").is_file()


def is_enabled(name: str) -> bool:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUES[name])
    except FileNotFoundError:
        return False
    return True


def enable(name: str) -> None:
    if is_disposable(REPO_ROOT):
        raise ValueError(f"{REPO_ROOT} is a git worktree: enable this from the main clone")
    winreg = _winreg()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUES[name], 0, winreg.REG_SZ, launch_command(name))


def disable(name: str) -> None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUES[name])
    except FileNotFoundError:
        pass  # Already off, which is what was asked for.


def start(name: str) -> None:
    """Launch it now, the way a login would, detached from whatever called this."""
    subprocess.Popen(launch_command(name), close_fds=True)  # noqa: S603 - built here from sys.base_prefix and this checkout


def main(argv: list[str]) -> int:
    action, names = (argv[0], argv[1:]) if argv else ("status", [])
    actions = {"enable": enable, "disable": disable, "start": start}
    unknown = set(names) - VALUES.keys()
    if unknown or (action != "status" and action not in actions):
        print("usage: autostart {enable,disable,start,status} [overlay] [collector]")
        return 2
    for name in names or VALUES:
        if action != "status":
            actions[action](name)
        print(f"{name}: {'on' if is_enabled(name) else 'off'} at login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
