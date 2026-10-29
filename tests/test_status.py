import pytest

from productivity_tracker.status import (
    Color,
    focus_order,
    next_session,
    normalize_status,
    task_color,
)


@pytest.mark.parametrize(
    ("active", "statuses", "color"),
    [
        (True, [], Color.RED),
        (True, ["idle", "idle"], Color.RED),
        (True, ["idle", "busy"], Color.GREEN),
        (True, ["busy", "busy"], Color.GREEN),
        (True, ["busy", "waiting"], Color.YELLOW),
        (True, ["waiting"], Color.YELLOW),
        (False, ["waiting", "busy"], Color.GRAY),
        (False, [], Color.GRAY),
    ],
)
def test_task_color(active, statuses, color):
    assert task_color(active, statuses) is color


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("busy", "busy"),
        ("waiting", "waiting"),
        ("idle", "idle"),
        ("asleep", "idle"),
        (None, "idle"),
        (3, "idle"),
    ],
)
def test_normalize_status(raw, status):
    assert normalize_status(raw) == status


def s(session_id, status):
    return {"session_id": session_id, "status": status}


def test_focus_order_on_a_yellow_row_is_only_the_waiting_sessions():
    sessions = [s("a", "busy"), s("b", "waiting"), s("c", "idle"), s("d", "waiting")]
    assert [x["session_id"] for x in focus_order(Color.YELLOW, sessions)] == ["b", "d"]


@pytest.mark.parametrize("color", [Color.GREEN, Color.RED, Color.GRAY])
def test_focus_order_elsewhere_is_every_session_working_first(color):
    sessions = [s("c", "idle"), s("b", "busy"), s("a", "idle")]
    assert [x["session_id"] for x in focus_order(color, sessions)] == ["b", "a", "c"]


def test_focus_order_of_no_sessions_is_empty():
    assert focus_order(Color.RED, []) == []


def test_next_session_cycles_and_wraps():
    order = [s("a", "busy"), s("b", "busy"), s("c", "idle")]
    assert next_session(order, None)["session_id"] == "a"
    assert next_session(order, "a")["session_id"] == "b"
    assert next_session(order, "c")["session_id"] == "a"


def test_next_session_restarts_when_the_last_one_ended():
    assert next_session([s("a", "busy")], "gone")["session_id"] == "a"


def test_next_session_of_nothing_is_none():
    assert next_session([], "a") is None
