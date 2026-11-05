"""The overlay's window, driven through a stand-in for tkinter.

CI has no display for a real Tk, and what is worth testing here is the wiring, not Tk's
drawing: which rows are built in which colours, and what a click or a right-click sets off.
"""

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from productivity_tracker import overlay
from productivity_tracker.overlay import (
    GOLD,
    MUTED,
    PALETTE,
    ROW_BG,
    ROW_HOVER,
    TEXT,
    OverlayModel,
    OverlayWindow,
)
from productivity_tracker.status import Color
from productivity_tracker.tray import Command
from test_overlay import (  # tests/ is on sys.path: pytest's rootdir-less "prepend" import
    STATE,
    stats,
)


class Widget:
    def __init__(self, parent: "Widget | None" = None, **options: Any) -> None:
        self.parent = parent
        self.options = dict(options)
        self.children: list[Widget] = []
        self.bindings: dict[str, Any] = {}
        if parent is not None:
            parent.children.append(self)

    def bind(self, event: str, handler: Any) -> None:
        self.bindings[event] = handler

    def winfo_children(self) -> list["Widget"]:
        return list(self.children)

    def destroy(self) -> None:
        if self.parent is not None:
            self.parent.children.remove(self)

    def configure(self, **options: Any) -> None:
        self.options.update(options)

    def __setitem__(self, key: str, value: Any) -> None:
        self.options[key] = value

    def __getattr__(self, name: str) -> Any:
        # pack, after, geometry, attributes, winfo_*, mainloop...: accepted and ignored.
        return lambda *args, **kwargs: 0


FAKE_TK = SimpleNamespace(Tk=Widget, Frame=Widget, Label=Widget, Event=object, Misc=Widget)


class Threads:
    def __init__(self) -> None:
        self.started: list[tuple[Any, tuple]] = []

    def __call__(self, target: Any, args: tuple = (), daemon: bool = False) -> SimpleNamespace:
        self.started.append((target, args))
        return SimpleNamespace(start=lambda: None)


class Client:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.toggled: list[tuple[int, bool]] = []

    def state(self) -> dict:
        if self.fail:
            raise OSError("unreachable")
        return STATE

    def set_active(self, task_id: int, active: bool) -> dict:
        if self.fail:
            raise OSError("unreachable")
        self.toggled.append((task_id, active))
        return {}


@pytest.fixture
def threads(monkeypatch) -> Threads:
    threads = Threads()
    monkeypatch.setattr(overlay, "tk", FAKE_TK)
    monkeypatch.setattr(overlay, "threading", SimpleNamespace(Thread=threads))
    return threads


# Unannotated, like the tests: the stand-ins are Tk and a TrackerClient only by duck type.
def make(client):
    return OverlayWindow(Widget(), client, OverlayModel(), "desk", 1.0)


def shown(win, state):
    win.states.put(state)
    win._drain()
    return win.rows.winfo_children()


def test_the_window_starts_polling(threads):
    win = make(Client())
    assert threads.started == [(win._poll_forever, ())]


def test_each_task_is_a_row_with_its_colour_bar(threads):
    rows = shown(make(Client()), STATE)

    assert len(rows) == 4
    bars = [row.children[0].options["bg"] for row in rows]
    assert bars == [PALETTE[Color.YELLOW], PALETTE[Color.GREEN], PALETTE[Color.RED], ROW_BG]
    names = [row.children[1].options["text"] for row in rows]
    assert names == ["alpha", "beta", "gamma", "delta"]
    # The inactive row has no indicator, only muted text.
    assert rows[3].children[1].options["fg"] == MUTED
    assert [row.children[2].options["text"] for row in rows] == ["3", "2", "", "1"]


def test_each_row_shows_todays_prompts(threads):
    rows = shown(make(Client()), STATE)
    assert [row.children[3].options["text"] for row in rows] == ["12", "3", "", ""]


def texts(frame):
    return [child.options["text"] for child in frame.winfo_children()]


def test_the_scoreboard_sits_below_the_rows(threads):
    win = make(Client())
    shown(win, STATE)

    labels = texts(win.footer)
    assert labels[:3] == ["", "today", "best"]
    assert labels[3:6] == ["prompts", "42", "97"]
    assert labels[-1] == "agents waited on you 14m today"


def test_a_record_is_gold(threads):
    win = make(Client())
    shown(win, {**STATE, "stats": stats(today={"prompts": 120})})

    today_prompts = win.footer.winfo_children()[4]
    assert today_prompts.options["text"] == "\N{BLACK STAR} 120"
    assert today_prompts.options["fg"] == GOLD
    assert win.footer.winfo_children()[7].options["fg"] == TEXT


def test_an_unchanged_scoreboard_is_not_rebuilt(threads):
    win = make(Client())
    shown(win, STATE)
    before = win.footer.winfo_children()
    shown(win, STATE)
    assert win.footer.winfo_children() == before


def test_a_server_without_a_scoreboard_shows_none(threads):
    win = make(Client())
    shown(win, {"tasks": STATE["tasks"]})
    assert win.footer.winfo_children() == []


def test_no_tasks_shows_a_placeholder(threads):
    [label] = shown(make(Client()), {"tasks": []})
    assert label.options["text"] == "no tasks yet"


def test_offline_is_shown_in_the_header_and_keeps_the_rows(threads):
    win = make(Client())
    shown(win, STATE)
    rows = shown(win, None)
    assert win.title.options["text"] == "Agents (offline)"
    assert len(rows) == 4


def test_clicking_a_row_focuses_its_next_session(threads, monkeypatch):
    focused: list[tuple[str, str]] = []
    monkeypatch.setattr(
        overlay, "focus_session", lambda s, host: focused.append((s["session_id"], host))
    )
    rows = shown(make(Client()), STATE)

    rows[0].bindings["<Button-1>"](None)
    rows[0].children[1].bindings["<Button-1>"](None)

    assert focused == [("a2", "desk"), ("a3", "desk")]


def test_clicking_a_row_without_sessions_does_nothing(threads, monkeypatch):
    monkeypatch.setattr(overlay, "focus_session", lambda s, host: pytest.fail("focused"))
    rows = shown(make(Client()), STATE)
    rows[2].bindings["<Button-1>"](None)


def test_right_click_greys_the_row_and_tells_the_server(threads):
    client = Client()
    win = make(client)
    rows = shown(win, STATE)

    rows[1].bindings["<Button-3>"](None)

    assert win.rows.winfo_children()[1].children[0].options["bg"] == ROW_BG
    target, args = threads.started[-1]
    target(*args)
    assert client.toggled == [(2, False)]


def test_a_failed_toggle_is_logged(threads, caplog):
    win = make(Client(fail=True))
    with caplog.at_level(logging.WARNING):
        win._send_toggle(2, False)
    assert "could not set task 2" in caplog.text


def test_hover_shades_the_whole_row(threads):
    rows = shown(make(Client()), STATE)
    rows[0].children[1].bindings["<Enter>"](None)
    assert rows[0].options["bg"] == ROW_HOVER
    rows[0].bindings["<Leave>"](None)
    assert rows[0].children[2].options["bg"] == ROW_BG


class Stop(Exception):
    pass


def test_polling_an_unreachable_server_queues_offline(threads, monkeypatch):
    win = make(Client(fail=True))

    def sleep(seconds):
        raise Stop

    monkeypatch.setattr(overlay.time, "sleep", sleep)
    with pytest.raises(Stop):
        win._poll_forever()
    assert win.states.get_nowait() is None


def test_main_builds_the_window(threads, monkeypatch):
    built: list[OverlayWindow] = []
    real = overlay.OverlayWindow
    monkeypatch.setattr(overlay, "OverlayWindow", lambda *a: built.append(real(*a)))
    monkeypatch.setattr(overlay, "start_tray", lambda commands, bars: None)
    overlay.main()
    assert len(built) == 1


def test_main_stops_the_tray_when_the_window_closes(threads, monkeypatch):
    stopped: list[bool] = []
    tray = SimpleNamespace(stop=lambda: stopped.append(True))
    monkeypatch.setattr(overlay, "start_tray", lambda commands, bars: tray)
    overlay.main()
    assert stopped == [True]


class Root(Widget):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.scheduled = 0

    def withdraw(self) -> None:
        self.calls.append("withdraw")

    def deiconify(self) -> None:
        self.calls.append("deiconify")

    def destroy(self) -> None:
        self.calls.append("destroy")

    def after(self, *args: Any) -> None:
        self.scheduled += 1


def header_labels(root):
    return root.children[0].children


def test_without_a_tray_nothing_offers_to_hide_the_window(threads):
    root = Root()
    OverlayWindow(root, Client(), OverlayModel(), "desk", 1.0)
    assert "\N{EN DASH}" not in [w.options.get("text") for w in header_labels(root)]


def test_the_dash_hides_the_window_when_there_is_a_tray(threads):
    root = Root()
    win = OverlayWindow(root, Client(), OverlayModel(), "desk", 1.0, can_hide=True)
    [hide] = [w for w in header_labels(root) if w.options.get("text") == "\N{EN DASH}"]

    hide.bindings["<Button-1>"](None)

    assert root.calls == ["withdraw"]
    assert win.hidden


def test_the_tray_toggles_the_window_from_the_tk_thread(threads):
    root = Root()
    win = OverlayWindow(root, Client(), OverlayModel(), "desk", 1.0, can_hide=True)

    win.commands.put(Command.TOGGLE)
    assert root.calls == []  # Queued, not called: the tray's thread may not touch Tk.
    win._drain()
    win.commands.put(Command.TOGGLE)
    win._drain()

    assert root.calls == ["withdraw", "deiconify"]
    assert not win.hidden


def test_quit_destroys_the_root_and_schedules_nothing_on_it(threads):
    root = Root()
    win = OverlayWindow(root, Client(), OverlayModel(), "desk", 1.0)
    before = root.scheduled

    win.commands.put(Command.QUIT)
    win._drain()

    assert root.calls == ["destroy"]
    assert root.scheduled == before
