"""Bring a session in front of you, wherever it runs.

A session on this PC: find the terminal hosting it by walking up from the `claude` process to
the first ancestor that owns a visible window (Windows Terminal, a console, VS Code), select
its tab, and raise that window.

A session on another PC: you reach that PC through a Remote Desktop window, and nothing on
this PC can touch what is inside it. So this side raises that window (or opens it), and the
PC's own collector, which runs inside the remote desktop, does the rest on request: see
`request_focus` here and `serve_focus` in the collector.
"""

import logging
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psutil

log = logging.getLogger("productivity_tracker.focus")

# The shell's own windows: climbing to them would raise the desktop, not the session.
_STOP_AT = {"explorer.exe", "services.exe", "wininit.exe", "systemd", "launchd", "init"}
# mstsc.exe's top-level window, connected or not.
_RDP_CLIENT_CLASSES = {"TscShellContainerClass"}
_TAB_TIMEOUT_SECONDS = 10.0
_TITLE_LENGTH = 512


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    class_name: str


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


def windows_of(pids: Iterable[int], windows: Sequence[Window]) -> list[int]:
    """Every window of the first process in `pids` that has any: one terminal process can
    hold several windows, and the session's tab is in just one of them."""
    for pid in pids:
        found = [window.hwnd for window in windows if window.pid == pid]
        if found:
            return found
    return []


def rdp_window(host: str, windows: Sequence[Window], target: str | None = None) -> int | None:
    """The Remote Desktop window connected to `host`. Its title names what was typed into
    the client, `target` when that is not the host's own name. With no `target` and one
    Remote Desktop window open, that is the one."""
    clients = [window for window in windows if window.class_name in _RDP_CLIENT_CLASSES]
    # A whole name: the client calls itself "Remote Desktop", which a plain substring test
    # finds a host called `desk` in. A dot still ends one: `desk.tail1234.ts.net`.
    wanted = re.compile(rf"(?<![\w-]){re.escape(target or host)}(?![\w-])", re.IGNORECASE)
    for window in clients:
        if wanted.search(window.title):
            return window.hwnd
    return clients[0].hwnd if len(clients) == 1 and not target else None


def top_level_windows() -> list[Window]:
    """Visible, titled, unowned top-level windows. Windows only."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gw_owner = 4
    found: list[Window] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd: int, _lparam: int) -> bool:
        if (
            user32.IsWindowVisible(hwnd)
            and user32.GetWindowTextLengthW(hwnd) > 0
            and not user32.GetWindow(hwnd, gw_owner)
        ):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title = ctypes.create_unicode_buffer(_TITLE_LENGTH)
            user32.GetWindowTextW(hwnd, title, _TITLE_LENGTH)
            class_name = ctypes.create_unicode_buffer(_TITLE_LENGTH)
            user32.GetClassNameW(hwnd, class_name, _TITLE_LENGTH)
            found.append(Window(hwnd, pid.value, title.value, class_name.value))
        return True

    user32.EnumWindows(collect, 0)
    return found


def raise_window(hwnd: int) -> bool:
    """Put `hwnd` in front. The collector is a background process, which Windows refuses
    SetForegroundWindow outright, so it borrows the foreground thread's input state, then
    falls back on SwitchToThisWindow, which that lock refuses less often."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    sw_restore = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    foreground = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    this_thread = kernel32.GetCurrentThreadId()
    borrowing = foreground not in (0, this_thread)
    if borrowing:
        user32.AttachThreadInput(this_thread, foreground, True)
    user32.SetForegroundWindow(hwnd)
    if borrowing:
        user32.AttachThreadInput(this_thread, foreground, False)
    if user32.GetForegroundWindow() == hwnd:
        return True
    user32.SwitchToThisWindow(hwnd, True)
    return bool(user32.GetForegroundWindow() == hwnd)


def tab_window(
    pid: int, hwnds: Sequence[int], run: Callable[..., Any] = subprocess.run
) -> int | None:
    """Select `pid`'s terminal tab, in a process of its own (see `terminal_tab`); returns
    the window holding it, or None when there is no such tab: not every host has tabs."""
    command = [sys.executable, "-m", "productivity_tracker.terminal_tab", str(pid)]
    try:
        done = run(
            [*command, *(str(hwnd) for hwnd in hwnds)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=_TAB_TIMEOUT_SECONDS,
            check=False,
            # No console of its own: a console is what it has to give up to read a title.
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("could not select the tab of pid %s: %s", pid, exc)
        return None
    if done.returncode != 0:
        if done.stderr:
            log.warning("could not select the tab of pid %s: %s", pid, done.stderr)
        return None
    return int(done.stdout)


def focus_local(
    pid: int,
    *,
    ancestors: Callable[[int], list[int]] = ancestor_pids,
    windows: Callable[[], list[Window]] = top_level_windows,
    find_tab: Callable[[int, Sequence[int]], int | None] = tab_window,
    bring_forward: Callable[[int], bool] = raise_window,
) -> bool:
    """Raise the terminal of the session `pid` on this PC, on its own tab."""
    hwnds = windows_of(ancestors(pid), windows())
    if not hwnds:
        return False
    return bring_forward(find_tab(pid, hwnds) or hwnds[0])


def open_rdp(target: str) -> None:
    try:
        subprocess.Popen(["mstsc", f"/v:{target}"])  # noqa: S603, S607 - the OS's own client; the target comes from this PC's .env or a host's name
    except OSError as exc:
        log.warning("could not start Remote Desktop to %s: %s", target, exc)


def show_remote_desktop(
    host: str,
    target: str | None = None,
    *,
    windows: Callable[[], list[Window]] = top_level_windows,
    bring_forward: Callable[[int], bool] = raise_window,
    launch: Callable[[str], None] = open_rdp,
) -> None:
    """Raise the Remote Desktop window to `host`, or open one."""
    hwnd = rdp_window(host, windows(), target)
    if hwnd is None:
        launch(target or host)
    else:
        bring_forward(hwnd)


def focus_session(
    session: Mapping[str, Any],
    local_host: str,
    request_focus: Callable[[str, int], None],
    rdp_targets: Mapping[str, str] | None = None,
    *,
    focus_here: Callable[[int], bool] = focus_local,
    show_remote: Callable[[str, str | None], None] = show_remote_desktop,
) -> str:
    """Focus `session`; returns how: "window" here, "remote" on another PC (on its way: the
    click has been handed over), or "none" when no window could be found."""
    host, pid = str(session["host"]), int(session["pid"])
    if host.lower() == local_host.lower():
        return "window" if focus_here(pid) else "none"
    targets = {name.lower(): value for name, value in (rdp_targets or {}).items()}
    show_remote(host, targets.get(host.lower()))
    request_focus(host, pid)
    return "remote"
