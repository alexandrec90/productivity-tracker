"""Select the Windows Terminal tab a session runs in; raising the window alone would show
whichever tab was on top.

    python -m productivity_tracker.terminal_tab <pid> <hwnd> [<hwnd> ...]

selects `pid`'s tab in one of the terminal windows `hwnd` and prints that window's handle.

A session and its tab share a title: reading the console `pid` is attached to gives the very
string Windows Terminal shows on the tab. That read has to attach to the session's console,
which a process can do only by giving up its own, so this is a process of its own: the
collector usually has a console to keep, and the overlay's click must not sit on COM.
"""

import ctypes
import importlib
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any

# Claude Code animates a glyph in front of the title (✳ ◐ ◑ ...), so the same tab reads
# differently from one moment to the next.
_STATUS_GLYPH = re.compile(r"^\W+")
_TITLE_LENGTH = 1024


def tab_key(title: str) -> str:
    return _STATUS_GLYPH.sub("", title).strip().casefold()


def pick_tab[T](title: str, tabs: Iterable[tuple[str, T]]) -> T | None:
    """The tab called `title`. Two tabs of one name are told apart by nothing, so the first
    wins; an empty title matches none."""
    key = tab_key(title)
    if not key:
        return None
    return next((tab for name, tab in tabs if tab_key(name) == key), None)


def console_title(pid: int) -> str:
    """The title of the console `pid` runs in, or "" when it has none. Windows only."""
    if sys.platform != "win32":
        return ""
    kernel32 = ctypes.windll.kernel32
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        return ""
    title = ctypes.create_unicode_buffer(_TITLE_LENGTH)
    kernel32.GetConsoleTitleW(title, _TITLE_LENGTH)
    kernel32.FreeConsole()
    return title.value


def _tabs_of(automation: Any, names: Any, hwnd: int) -> list[tuple[str, Any]]:
    window = automation.ElementFromHandle(hwnd)
    is_tab = automation.CreatePropertyCondition(
        names.UIA_ControlTypePropertyId, names.UIA_TabItemControlTypeId
    )
    found = window.FindAll(names.TreeScope_Descendants, is_tab)
    elements = [found.GetElement(i) for i in range(found.Length)]
    return [(element.CurrentName, element) for element in elements]


def select_tab(hwnds: Sequence[int], title: str) -> int | None:
    """Select the tab called `title` in the first of `hwnds` holding one; returns that
    window. Goes through UI Automation, Windows Terminal's only way in from outside that
    can name a tab. Windows only: comtypes is not installed anywhere else, which is why it
    is imported by name, here."""
    client: Any = importlib.import_module("comtypes.client")
    client.GetModule("UIAutomationCore.dll")
    names: Any = importlib.import_module("comtypes.gen.UIAutomationClient")
    automation = client.CreateObject(names.CUIAutomation._reg_clsid_, interface=names.IUIAutomation)
    for hwnd in hwnds:
        tab = pick_tab(title, _tabs_of(automation, names, hwnd))
        if tab is not None:
            pattern = tab.GetCurrentPattern(names.UIA_SelectionItemPatternId)
            pattern.QueryInterface(names.IUIAutomationSelectionItemPattern).Select()
            return hwnd
    return None


def run(
    argv: Sequence[str],
    *,
    title_of: Callable[[int], str] = console_title,
    select: Callable[[Sequence[int], str], int | None] = select_tab,
) -> str | None:
    """The chosen window, as this process prints it; None when no tab was selected."""
    pid, *hwnds = [int(arg) for arg in argv]
    title = title_of(pid)
    hwnd = select(hwnds, title) if title else None
    return None if hwnd is None else str(hwnd)


def main() -> int:
    chosen = run(sys.argv[1:])
    if chosen is None:
        return 1
    print(chosen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
