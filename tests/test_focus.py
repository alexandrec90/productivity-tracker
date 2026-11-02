import os
import sys

import psutil

from productivity_tracker import focus
from productivity_tracker.focus import (
    ancestor_pids,
    find_local_window,
    first_window,
    focus_session,
    raise_window,
    remote_url,
)


def session(host="laptop", remote="session_abc"):
    return {"host": host, "pid": 42, "remote_session_id": remote}


class Spy:
    def __init__(self, hwnd=None, raised=True):
        self.hwnd, self.raised = hwnd, raised
        self.opened: list[str] = []
        self.looked_up: list[int] = []

    def find(self, pid):
        self.looked_up.append(pid)
        return self.hwnd

    def bring(self, hwnd):
        return self.raised

    def focus(self, s, local="laptop"):
        return focus_session(
            s, local, find_window=self.find, bring_forward=self.bring, open_url=self.opened.append
        )


def test_a_local_session_with_a_window_is_raised():
    spy = Spy(hwnd=99)
    assert spy.focus(session()) == "window"
    assert spy.looked_up == [42]
    assert spy.opened == []


def test_the_host_comparison_ignores_case():
    spy = Spy(hwnd=99)
    assert spy.focus(session(host="LAPTOP")) == "window"


def test_a_local_session_without_a_window_opens_remote_control():
    spy = Spy(hwnd=None)
    assert spy.focus(session()) == "browser"
    assert spy.opened == ["https://claude.ai/code/session_abc"]


def test_a_window_that_refuses_the_foreground_falls_back_to_the_browser():
    spy = Spy(hwnd=99, raised=False)
    assert spy.focus(session()) == "browser"


def test_a_session_on_another_pc_opens_remote_control_without_looking_for_a_window():
    spy = Spy(hwnd=99)
    assert spy.focus(session(host="desk")) == "browser"
    assert spy.looked_up == []


def test_a_remote_session_without_remote_control_cannot_be_focused():
    spy = Spy()
    assert spy.focus(session(host="desk", remote=None)) == "none"
    assert spy.opened == []


def test_remote_url():
    assert remote_url("session_x") == "https://claude.ai/code/session_x"
    assert remote_url(None) is None
    assert remote_url("") is None


def test_first_window_takes_the_nearest_ancestor_with_one():
    windows = {3: [300, 301], 2: [200]}
    assert first_window([1, 2, 3], windows) == 200
    assert first_window([1], windows) is None


def test_ancestor_pids_starts_at_the_process_itself():
    pids = ancestor_pids(os.getpid())
    assert pids[0] == os.getpid()


def test_ancestor_pids_of_a_dead_process_is_empty(monkeypatch):
    def gone(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(focus.psutil, "Process", gone)
    assert ancestor_pids(123) == []


def test_ancestor_pids_stops_below_the_desktop_shell(monkeypatch):
    class Proc:
        def __init__(self, pid, name, parents=()):
            self.pid, self._name, self._parents = pid, name, parents

        def name(self):
            return self._name

        def parents(self):
            return list(self._parents)

    chain = Proc(
        1, "claude.exe", [Proc(2, "pwsh.exe"), Proc(3, "Explorer.EXE"), Proc(4, "wininit.exe")]
    )
    monkeypatch.setattr(focus.psutil, "Process", lambda pid: chain)
    assert ancestor_pids(1) == [1, 2]


def test_find_local_window_against_the_real_process_table():
    hwnd = find_local_window(os.getpid())
    if sys.platform == "win32":
        # Whether pytest sits under a console window depends on how it was started.
        assert hwnd is None or isinstance(hwnd, int)
    else:
        assert hwnd is None


def test_a_window_handle_that_does_not_exist_cannot_be_raised():
    assert raise_window(1) is False
