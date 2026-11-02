import pytest

from productivity_tracker.overlay import OverlayModel, Row, Scoreboard, Stat, format_duration
from productivity_tracker.status import Color


def task(task_id, name, color, sessions=(), active=True, prompts_today=0):
    return {
        "id": task_id,
        "name": name,
        "active": active,
        "color": color,
        "sessions": list(sessions),
        "prompts_today": prompts_today,
    }


def s(session_id, status):
    return {"session_id": session_id, "status": status, "host": "desk", "pid": 1}


def stats(today=None, best=None, streak=3, best_streak=7):
    return {
        "today": {
            "prompts": 42,
            "busy_seconds": 3 * 3600 + 12 * 60,
            "waiting_seconds": 14 * 60,
            "peak_busy": 4,
            **(today or {}),
        },
        "best": {"prompts": 97, "busy_seconds": 6 * 3600 + 40 * 60, "peak_busy": 7, **(best or {})},
        "streak": streak,
        "best_streak": best_streak,
    }


STATE = {
    "generated_at": "2026-10-28T12:00:00Z",
    "tasks": [
        task(
            1,
            "alpha",
            "yellow",
            [s("a1", "busy"), s("a2", "waiting"), s("a3", "waiting")],
            prompts_today=12,
        ),
        task(2, "beta", "green", [s("b1", "idle"), s("b2", "busy")], prompts_today=3),
        task(3, "gamma", "red"),
        task(4, "delta", "gray", [s("d1", "busy")], active=False),
    ],
    "stats": stats(),
}


def model():
    m = OverlayModel()
    m.update(STATE)
    return m


def test_rows_mirror_the_state():
    assert model().rows() == [
        Row(1, "alpha", True, Color.YELLOW, 3, 12),
        Row(2, "beta", True, Color.GREEN, 2, 3),
        Row(3, "gamma", True, Color.RED, 0, 0),
        Row(4, "delta", False, Color.GRAY, 1, 0),
    ]


def test_a_server_without_prompt_counts_shows_none():
    m = OverlayModel()
    m.update({"tasks": [{k: v for k, v in task(1, "a", "red").items() if k != "prompts_today"}]})
    assert m.rows()[0].prompts_today == 0
    assert m.scoreboard() is None


def test_the_scoreboard_sets_today_against_the_best_day():
    assert model().scoreboard() == Scoreboard(
        stats=(
            Stat("prompts", "42", "97", False),
            Stat("agent time", "3h12", "6h40", False),
            Stat("parallel", "4", "7", False),
            Stat("streak", "3d", "7d", False),
        ),
        waited="agents waited on you 14m today",
    )


def test_beating_a_record_stars_it():
    m = OverlayModel()
    m.update({**STATE, "stats": stats(today={"prompts": 98, "peak_busy": 8}, streak=7)})
    board = m.scoreboard()
    assert board is not None
    assert [(st.today, st.record) for st in board.stats] == [
        ("\N{BLACK STAR} 98", True),
        ("3h12", False),
        ("\N{BLACK STAR} 8", True),
        # The longest streak includes today's, so equalling it is the record.
        ("\N{BLACK STAR} 7d", True),
    ]


def test_the_first_day_beats_no_record_and_a_one_day_streak_is_none():
    m = OverlayModel()
    zero = {"prompts": 0, "busy_seconds": 0, "peak_busy": 0}
    m.update({**STATE, "stats": stats(best=zero, streak=1, best_streak=1)})
    board = m.scoreboard()
    assert board is not None
    assert not any(st.record for st in board.stats)


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(0, "0m"), (59, "0m"), (60, "1m"), (3599, "59m"), (3600, "1h00"), (3 * 3600 + 725, "3h12")],
)
def test_format_duration(seconds, shown):
    assert format_duration(seconds) == shown


def test_clicking_a_yellow_row_cycles_through_the_sessions_asking():
    m = model()
    picked = [m.target_for_click(1)["session_id"] for _ in range(3)]
    assert picked == ["a2", "a3", "a2"]


def test_clicking_a_green_row_cycles_through_every_session_working_first():
    m = model()
    picked = [m.target_for_click(2)["session_id"] for _ in range(3)]
    assert picked == ["b2", "b1", "b2"]


def test_clicking_a_row_without_sessions_focuses_nothing():
    assert model().target_for_click(3) is None


def test_clicking_an_unknown_row_focuses_nothing():
    assert model().target_for_click(99) is None


def test_each_row_keeps_its_own_place_in_the_cycle():
    m = model()
    m.target_for_click(1)
    assert m.target_for_click(2)["session_id"] == "b2"
    assert m.target_for_click(1)["session_id"] == "a3"


def test_going_offline_keeps_the_last_rows():
    m = model()
    m.update(None)
    assert not m.online
    assert len(m.rows()) == 4
    m.update(STATE)
    assert m.online


def test_toggle_greys_a_row_at_once_and_back():
    m = model()
    assert m.toggle(2) is False
    assert m.rows()[1] == Row(2, "beta", False, Color.GRAY, 2, 3)
    assert m.toggle(2) is True
    assert m.rows()[1].active


def test_toggle_of_an_unknown_task_is_none():
    assert model().toggle(99) is None
