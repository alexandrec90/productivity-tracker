"""Bring a session in front of you.

A session on this PC: raise the window hosting it, found by walking up from the `claude`
process to the first ancestor that owns a visible window (the console, Windows Terminal,
VS Code). A session on another PC, or one whose window cannot be found: open its Remote
Control page at claude.ai/code, which is how a remote session is reached at all.
"""

import sys
import webbrowser
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import psutil

REMOTE_BASE = "https://claude.ai/code/"
# The shell's own windows: climbing to them would raise the desktop, not the session.
_STOP_AT = {"explorer.exe", "services.exe", "wininit.exe", "systemd", "launchd", "init"}


def remote_url(remote_session_id: str | None) -> str | None:
    return REMOTE_BASE + remote_session_id if remote_session_id else None


def ancestor_pids(pid: int) -> list[int]:
    """`pid` and its parents, nearest first, stopping below the desktop shell."""
    try:
        chain = [psutil.Process(pid), *psutil.Process(pid).parents()]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []
    pids: list[int] = []
    for process in chain:
        try:
            if process.name().lower() in _STOP_AT:
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        pids.append(process.pid)
    return pids


def first_window(pids: Iterable[int], windows: Mapping[int, list[int]]) -> int | None:
    for pid in pids:
        if windows.get(pid):
            return windows[pid][0]
    return None


def _visible_windows() -> dict[int, list[int]]:
    """Visible, titled, unowned top-level windows, by owning pid. Windows only."""
    if sys.platform != "win32":
        return {}
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gw_owner = 4
    found: dict[int, list[int]] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd: int, _lparam: int) -> bool:
        if (
            user32.IsWindowVisible(hwnd)
            and user32.GetWindowTextLengthW(hwnd) > 0
            and not user32.GetWindow(hwnd, gw_owner)
        ):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.setdefault(pid.value, []).append(hwnd)
        return True

    user32.EnumWindows(collect, 0)
    return found


def find_local_window(pid: int) -> int | None:
    return first_window(ancestor_pids(pid), _visible_windows())


def raise_window(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    sw_restore = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    return bool(user32.SetForegroundWindow(hwnd))


def focus_session(
    session: Mapping[str, Any],
    local_host: str,
    *,
    find_window: Callable[[int], int | None] = find_local_window,
    bring_forward: Callable[[int], bool] = raise_window,
    open_url: Callable[[str], object] = webbrowser.open,
) -> str:
    """Focus `session`; returns how: "window", "browser", or "none" when neither works."""
    if str(session["host"]).lower() == local_host.lower():
        hwnd = find_window(int(session["pid"]))
        if hwnd and bring_forward(hwnd):
            return "window"
    url = remote_url(session.get("remote_session_id"))
    if url:
        open_url(url)
        return "browser"
    return "none"
