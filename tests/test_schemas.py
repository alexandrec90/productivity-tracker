from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from productivity_tracker.schemas import (
    ActiveIn,
    DayStats,
    PromptIn,
    Records,
    SessionIn,
    SessionOut,
    SnapshotIn,
    StateOut,
    StatsOut,
    TaskOut,
)
from productivity_tracker.status import Color

MINIMAL = {"session_id": "s1", "pid": 1, "project": "alpha", "cwd": "/code/alpha", "status": "idle"}


def test_a_minimal_session_parses_with_its_optional_fields_empty():
    session = SessionIn.model_validate(MINIMAL)
    assert session.waiting_for is None
    assert session.status_updated_at is None


def test_a_session_from_an_older_collector_still_parses():
    # Collectors outlive a server upgrade until each PC restarts one.
    session = SessionIn.model_validate({**MINIMAL, "remote_session_id": "session_1"})
    assert session.session_id == "s1"


@pytest.mark.parametrize(
    "bad",
    [{"status": "asleep"}, {"session_id": ""}, {"project": ""}, {"pid": "one"}],
)
def test_a_malformed_session_is_rejected(bad):
    with pytest.raises(ValidationError):
        SessionIn.model_validate({**MINIMAL, **bad})


def test_a_snapshot_needs_a_host():
    with pytest.raises(ValidationError):
        SnapshotIn.model_validate({"host": "", "sessions": []})
    assert SnapshotIn.model_validate({"host": "desk", "sessions": [MINIMAL]}).sessions[0].pid == 1


def test_the_state_serialises_colours_as_their_names():
    out = StateOut(
        generated_at=datetime(2026, 10, 28, tzinfo=UTC),
        tasks=[
            TaskOut(
                id=1,
                name="alpha",
                active=True,
                color=Color.YELLOW,
                sessions=[
                    SessionOut(
                        host="desk",
                        session_id="s1",
                        pid=1,
                        cwd="/code/alpha",
                        status="waiting",
                        waiting_for="input needed",
                        name=None,
                        kind=None,
                        status_updated_at=None,
                    )
                ],
            )
        ],
        stats=StatsOut(today=DayStats(), best=Records(), streak=0, best_streak=0),
    )
    dumped = out.model_dump(mode="json")
    assert dumped["tasks"][0]["color"] == "yellow"
    assert dumped["tasks"][0]["sessions"][0]["waiting_for"] == "input needed"
    assert dumped["tasks"][0]["prompts_today"] == 0
    assert dumped["stats"]["today"] == {
        "prompts": 0,
        "busy_seconds": 0.0,
        "waiting_seconds": 0.0,
        "peak_busy": 0,
    }
    assert dumped["stats"]["best"] == {"prompts": 0, "busy_seconds": 0.0, "peak_busy": 0}


PROMPT = {"session_id": "s1", "at": "2026-10-28T12:00:00+00:00", "project": "alpha"}


def test_a_snapshot_without_prompts_has_none():
    assert SnapshotIn.model_validate({"host": "desk", "sessions": []}).prompts == []


def test_a_prompt_parses_its_time_and_may_lack_a_session():
    prompt = PromptIn.model_validate({**PROMPT, "session_id": ""})
    assert prompt.at == datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.mark.parametrize("bad", [{"project": ""}, {"at": "yesterday"}, {"session_id": "x" * 101}])
def test_a_malformed_prompt_is_rejected(bad):
    with pytest.raises(ValidationError):
        PromptIn.model_validate({**PROMPT, **bad})


def test_a_snapshot_carries_at_most_a_thousand_prompts():
    SnapshotIn.model_validate({"host": "desk", "sessions": [], "prompts": [PROMPT] * 1000})
    with pytest.raises(ValidationError):
        SnapshotIn.model_validate({"host": "desk", "sessions": [], "prompts": [PROMPT] * 1001})


def test_active_in():
    assert ActiveIn.model_validate({"active": False}).active is False
    with pytest.raises(ValidationError):
        ActiveIn.model_validate({})
