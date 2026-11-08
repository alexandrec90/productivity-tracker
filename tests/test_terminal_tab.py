"""Which tab is a session's, on real titles, spinner and all. Reading a console title and
selecting a tab need a live terminal, so only the decisions around them are tested here,
with UI Automation stood in for."""

import sys
from types import SimpleNamespace

import pytest

from productivity_tracker import terminal_tab
from productivity_tracker.terminal_tab import (
    console_title,
    main,
    pick_tab,
    run,
    select_tab,
    tab_key,
)


@pytest.mark.parametrize(
    ("title", "key"),
    [
        ("\N{EIGHT SPOKED ASTERISK} Host PC overlay setup", "host pc overlay setup"),
        ("\N{CIRCLE WITH LEFT HALF BLACK} Host PC overlay setup", "host pc overlay setup"),
        ("Plain title", "plain title"),
        ("\N{EIGHT SPOKED ASTERISK} ", ""),
        ("", ""),
    ],
)
def test_tab_key_drops_the_status_glyph(title, key):
    assert tab_key(title) == key


def test_a_tab_is_found_though_its_spinner_moved_on():
    tabs = [
        ("\N{EIGHT SPOKED ASTERISK} Paper trading app startup", "a"),
        ("\N{CIRCLE WITH RIGHT HALF BLACK} Session list focus and counts", "b"),
    ]
    assert pick_tab("\N{CIRCLE WITH LEFT HALF BLACK} Session list focus and counts", tabs) == "b"


def test_no_tab_of_that_name_is_none():
    assert pick_tab("elsewhere", [("here", "a")]) is None


def test_two_tabs_of_one_name_give_the_first():
    assert pick_tab("same", [("same", "a"), ("same", "b")]) == "a"


def test_an_empty_title_matches_no_tab_even_a_blank_one():
    assert pick_tab("", [("", "a")]) is None


def test_run_looks_up_the_sessions_title_in_the_windows_given():
    seen: list = []

    def select(hwnds, title):
        seen.append((hwnds, title))
        return hwnds[1]

    assert run(["42", "5", "6"], title_of=lambda pid: f"t{pid}", select=select) == "6"
    assert seen == [([5, 6], "t42")]


def test_run_with_no_console_title_does_not_look():
    chosen = run(["42", "5"], title_of=lambda pid: "", select=lambda h, t: pytest.fail("looked"))
    assert chosen is None


def test_run_when_no_window_holds_the_tab_is_none():
    assert run(["42", "5"], title_of=lambda pid: "t", select=lambda h, t: None) is None


def test_main_prints_the_window_and_exits_clean(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["terminal_tab", "42", "5"])
    monkeypatch.setattr(terminal_tab, "run", lambda argv: "5")
    assert main() == 0
    assert capsys.readouterr().out == "5\n"


def test_main_exits_nonzero_when_there_is_no_tab(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["terminal_tab", "42", "5"])
    monkeypatch.setattr(terminal_tab, "run", lambda argv: None)
    assert main() == 1
    assert capsys.readouterr().out == ""


def test_console_title_off_windows_is_empty(monkeypatch):
    monkeypatch.setattr(terminal_tab.sys, "platform", "linux")
    assert console_title(1) == ""


class Tab:
    """A UI Automation tab element: a name, and a selection pattern that records `Select`."""

    def __init__(self, name: str, selected: list[str]) -> None:
        self.CurrentName = name
        self._selected = selected

    def GetCurrentPattern(self, pattern_id):
        assert pattern_id == NAMES.UIA_SelectionItemPatternId
        return SimpleNamespace(QueryInterface=lambda iface: self)

    def Select(self) -> None:
        self._selected.append(self.CurrentName)


NAMES = SimpleNamespace(
    CUIAutomation=SimpleNamespace(_reg_clsid_="clsid"),
    IUIAutomation="IUIAutomation",
    IUIAutomationSelectionItemPattern="IUIAutomationSelectionItemPattern",
    UIA_ControlTypePropertyId=1,
    UIA_TabItemControlTypeId=2,
    TreeScope_Descendants=4,
    UIA_SelectionItemPatternId=5,
)


def fake_comtypes(monkeypatch, windows: dict[int, list[str]]) -> list[str]:
    """Stand in for comtypes, whose UI Automation needs a live Windows Terminal; returns
    the names of the tabs `select_tab` selects."""
    selected: list[str] = []

    def found(hwnd: int) -> SimpleNamespace:
        tabs = [Tab(name, selected) for name in windows[hwnd]]
        return SimpleNamespace(Length=len(tabs), GetElement=tabs.__getitem__)

    automation = SimpleNamespace(
        ElementFromHandle=lambda hwnd: SimpleNamespace(FindAll=lambda scope, cond: found(hwnd)),
        CreatePropertyCondition=lambda prop, value: (prop, value),
    )
    client = SimpleNamespace(
        GetModule=lambda dll: None, CreateObject=lambda clsid, interface: automation
    )
    modules = {"comtypes.client": client, "comtypes.gen.UIAutomationClient": NAMES}
    monkeypatch.setattr(terminal_tab.importlib, "import_module", modules.__getitem__)
    return selected


def test_select_tab_selects_it_in_the_window_that_holds_it(monkeypatch):
    selected = fake_comtypes(
        monkeypatch, {5: ["other"], 6: ["pwsh", "\N{EIGHT SPOKED ASTERISK} job"]}
    )
    assert select_tab([5, 6], "\N{CIRCLE WITH LEFT HALF BLACK} job") == 6
    assert selected == ["\N{EIGHT SPOKED ASTERISK} job"]


def test_select_tab_with_no_such_tab_selects_nothing(monkeypatch):
    selected = fake_comtypes(monkeypatch, {5: ["other"]})
    assert select_tab([5], "job") is None
    assert selected == []
