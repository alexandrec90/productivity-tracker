"""Run a tracker process with no console: what Windows starts at login.

    <base python>/pythonw.exe scripts/launch_gui.py overlay

The venv's own `pythonw.exe` cannot be trusted with this. uv 0.11.29 built it as a console
program, a copy of `python.exe`, so anything started through it (`pt-overlay.exe` included)
opens a terminal, and closing that terminal kills the process. The base interpreter's
`pythonw.exe` is a GUI program whichever uv built the venv, so it runs this file, which adds
the venv's packages itself.

This has to be a file: a `Run` registry value is documented as limited to 260 characters,
and the same thing spelled as a `-c` one-liner comes to about 285 on a real path.

Stdlib only, and nothing here may import the application before `add_venv`: until then the
application's dependencies are not importable.
"""

import ctypes
import runpy
import site
import sys
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "overlay": "productivity_tracker.overlay",
    "collector": "productivity_tracker.collector",
}
ERROR_ALREADY_EXISTS = 183


def first_instance(name: str) -> bool:
    """False when this logon session already runs `name`: a login start plus a manual one
    must not mean two tray icons, or a second run truncating the first one's log. The mutex
    needs no cleanup, since Windows drops it when the process exits, however it exits."""
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, f"Local\\ProductivityTracker-{name}")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def site_packages(root: Path) -> Path:
    return root / ".venv" / "Lib" / "site-packages"


def add_venv(root: Path) -> None:
    """Make the checkout's venv importable. `addsitedir`, not `sys.path`: the project itself
    is an editable install, which only a `.pth` file in there puts on the path."""
    packages = site_packages(root)
    if not packages.is_dir():
        raise FileNotFoundError(f"no venv at {packages}: run `uv sync` in {root}")
    site.addsitedir(str(packages))


def open_log(root: Path, name: str) -> TextIO:
    """`logs/<name>.log`, overwritten per run. Under pythonw `sys.stderr` is None, so without
    this a crash at login leaves no trace at all."""
    directory = root / "logs"
    directory.mkdir(exist_ok=True)
    return (directory / f"{name}.log").open("w", encoding="utf-8", buffering=1)


def main(argv: list[str]) -> int:
    name = argv[1] if len(argv) == 2 else ""
    module = MODULES.get(name)
    if module is None:
        raise SystemExit(f"usage: launch_gui.py {{{','.join(MODULES)}}}")
    if not first_instance(name):
        return 0
    sys.stderr = open_log(REPO_ROOT, name)
    add_venv(REPO_ROOT)
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
