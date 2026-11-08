import os
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest

from productivity_tracker import focus
from productivity_tracker.focus import (
    Window,
    ancestor_pids,
    focus_local,
    focus_session,
    open_rdp,
    raise_window,
    rdp_window,
    show_remote_desktop,
    tab_window,
    top_level_windows,
    windows_of,
)

RDP = "TscShellContainerClass"


def window(hwnd=1, pid=10, title="t", class_name="Other"):
    return Window(hwnd, pid, title, class_name)


class Spy:
    """focus_session's two ways out, recorded."""

    def __init__(self, found=True):
        self.found = found
        self.local: list[int] = []
        self.remote: list[tuple[str, str | None]] = []
        self.requested: list[tuple[str, int]] = []

    def here(self, pid):
        self.local.append(pid)
        return self.found

    def show(self, host, target):
        self.remote.append((host, target))

    def request(self, host, pid):
        self.requested.append((host, pid))

    def focus(self, host="laptop", targets=None):
        return focus_session(
            {"host": host, "pid": 42},
            "laptop",
            self.request,
            targets,
            focus_here=self.here,
            show_remote=self.show,
        )


def test_a_local_session_is_focused_here():
    spy = Spy()
    assert spy.focus() == "window"
    assert spy.local == [42]
    assert spy.remote == spy.requested == []


def test_the_host_comparison_ignores_case():
    assert Spy().focus(host="LAPTOP") == "window"


def test_a_local_session_with_no_window_says_so():
    assert Spy(found=False).focus() == "none"


def test_a_session_on_another_pc_raises_its_remote_desktop_and_hands_over_the_click():
    spy = Spy()
    assert spy.focus(host="desk") == "remote"
    assert spy.remote == [("desk", None)]
    assert spy.requested == [("desk", 42)]
    assert spy.local == []


def test_a_configured_rdp_target_is_found_whatever_the_case_of_the_host():
    spy = Spy()
    spy.focus(host="DESK", targets={"desk": "100.1.2.3"})
    assert spy.remote == [("DESK", "100.1.2.3")]


def test_windows_of_takes_every_window_of_the_nearest_process_with_one():
    windows = [window(300, 3), window(301, 3), window(200, 2)]
    assert windows_of([1, 2, 3], windows) == [200]
    assert windows_of([3], windows) == [300, 301]
    assert windows_of([1], windows) == []


def test_rdp_window_matches_the_host_in_the_title_ignoring_case():
    windows = [
        window(1, title="other - Remote Desktop Connection", class_name=RDP),
        window(2, title="desktop-b9fc8vp - Remote Desktop Connection", class_name=RDP),
    ]
    assert rdp_window("DESKTOP-B9FC8VP", windows) == 2


def test_a_tailnet_address_in_the_title_is_the_host():
    windows = [
        window(1, title="other - Remote Desktop Connection", class_name=RDP),
        window(2, title="desk.tail1234.ts.net - Remote Desktop Connection", class_name=RDP),
    ]
    assert rdp_window("desk", windows) == 2


def test_a_host_is_a_whole_name_not_part_of_another():
    windows = [
        window(1, title="desk-2 - Remote Desktop Connection", class_name=RDP),
        window(2, title="other - Remote Desktop Connection", class_name=RDP),
    ]
    assert rdp_window("desk", windows) is None


def test_rdp_window_ignores_anything_but_the_client():
    windows = [window(1, title="DESK notes.txt - Notepad")]
    assert rdp_window("desk", windows) is None


def test_the_only_rdp_window_is_the_one_even_if_it_was_opened_by_address():
    windows = [window(1, title="100.76.121.58 - Remote Desktop Connection", class_name=RDP)]
    assert rdp_window("desk", windows) == 1


def test_two_rdp_windows_and_no_match_is_no_guess():
    windows = [
        window(1, title="10.0.0.1 - Remote Desktop Connection", class_name=RDP),
        window(2, title="10.0.0.2 - Remote Desktop Connection", class_name=RDP),
    ]
    assert rdp_window("desk", windows) is None


def test_a_target_is_matched_instead_of_the_host():
    windows = [window(1, title="10.0.0.1 - Remote Desktop Connection", class_name=RDP)]
    assert rdp_window("desk", windows, "10.0.0.1") == 1
    # A target that says where to look rules out the lone-window guess.
    assert rdp_window("desk", windows, "10.0.0.2") is None


def test_show_remote_desktop_raises_the_window_it_finds():
    raised: list[int] = []
    show_remote_desktop(
        "desk",
        windows=lambda: [window(7, title="desk - RDP", class_name=RDP)],
        bring_forward=lambda hwnd: raised.append(hwnd) or True,
        launch=lambda target: pytest.fail("launched"),
    )
    assert raised == [7]


@pytest.mark.parametrize(("target", "opened"), [(None, "desk"), ("10.0.0.1", "10.0.0.1")])
def test_show_remote_desktop_opens_one_when_there_is_none(target, opened):
    launched: list[str] = []
    show_remote_desktop(
        "desk",
        target,
        windows=lambda: [],
        bring_forward=lambda hwnd: pytest.fail("raised"),
        launch=launched.append,
    )
    assert launched == [opened]


def test_open_rdp_starts_the_client(monkeypatch):
    started: list[list[str]] = []
    monkeypatch.setattr(focus.subprocess, "Popen", started.append)
    open_rdp("desk")
    assert started == [["mstsc", "/v:desk"]]


def test_no_rdp_client_is_logged_not_raised(monkeypatch, caplog):
    def missing(command):
        raise FileNotFoundError("mstsc")

    monkeypatch.setattr(focus.subprocess, "Popen", missing)
    open_rdp("desk")
    assert "could not start Remote Desktop to desk" in caplog.text


def local(hwnds=(5, 6), tab=None, raised=True):
    calls: list[int] = []

    def bring(hwnd):
        calls.append(hwnd)
        return raised

    outcome = focus_local(
        42,
        ancestors=lambda pid: [pid, 9],
        windows=lambda: [window(h, 9) for h in hwnds],
        find_tab=lambda pid, found: tab,
        bring_forward=bring,
    )
    return outcome, calls


def test_focus_local_raises_the_window_holding_the_sessions_tab():
    assert local(tab=6) == (True, [6])


def test_focus_local_without_a_tab_raises_the_terminal_anyway():
    assert local(tab=None) == (True, [5])


def test_focus_local_reports_a_window_that_stayed_behind():
    assert local(tab=5, raised=False) == (False, [5])


def test_focus_local_with_no_window_raises_nothing():
    assert local(hwnds=()) == (False, [])


def test_tab_window_runs_this_interpreter_on_the_helper_and_reads_its_answer():
    seen: dict = {}

    def run(command, **options):
        seen.update(command=command, **options)
        return SimpleNamespace(returncode=0, stdout="6\n", stderr="")

    assert tab_window(42, [5, 6], run) == 6
    assert seen["command"] == [
        sys.executable,
        "-m",
        "productivity_tracker.terminal_tab",
        "42",
        "5",
        "6",
    ]


def test_tab_window_without_a_tab_is_quiet(caplog):
    run = lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="")
    assert tab_window(42, [5], run) is None
    assert caplog.text == ""


def test_a_helper_that_crashed_is_logged(caplog):
    run = lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="COMError boom")
    assert tab_window(42, [5], run) is None
    assert "COMError boom" in caplog.text


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("python", 10), FileNotFoundError("python")]
)
def test_a_helper_that_never_answered_is_logged(failure, caplog):
    def run(*args, **options):
        raise failure

    assert tab_window(42, [5], run) is None
    assert "could not select the tab of pid 42" in caplog.text


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


def test_top_level_windows_against_the_real_desktop():
    windows = top_level_windows()
    if sys.platform != "win32":
        assert windows == []
    # Whether the run has a desktop at all depends on how it was started.
    assert all(w.hwnd and w.title for w in windows)


def test_a_window_handle_that_does_not_exist_cannot_be_raised():
    assert raise_window(1) is False
