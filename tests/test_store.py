"""The store directly, with the clock in the test's hands."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from productivity_tracker.db import make_engine
from productivity_tracker.schemas import DayStats, PromptIn, Records, SessionIn, SnapshotIn
from productivity_tracker.store import (
    add_task,
    check_timezone,
    ingest_snapshot,
    load_state,
    load_stats,
    local_date,
    remove_task,
    set_active,
)

T0 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
STALE = timedelta(seconds=30)


@pytest.fixture
def run(
    sync_db, test_database_url: str
) -> Callable[[Callable[[AsyncSession], Awaitable[Any]]], Any]:
    def go(work: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async def inner() -> Any:
            engine = make_engine(test_database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    return await work(db)
            finally:
                await engine.dispose()

        return asyncio.run(inner())

    return go


def sin(session_id: str, project: str = "alpha") -> SessionIn:
    return SessionIn(
        session_id=session_id, pid=1, project=project, cwd=f"/code/{project}", status="busy"
    )


def snap(host: str, sessions: list[SessionIn], prompts: list[PromptIn] | None = None):
    return SnapshotIn(host=host, sessions=sessions, prompts=prompts or [])


def listed(run, *names: str) -> None:
    for name in names:
        run(lambda db, name=name: add_task(db, name))


def test_sessions_count_until_their_host_goes_stale(run):
    listed(run, "alpha")
    run(lambda db: ingest_snapshot(db, snap("desk", [sin("s1")]), T0))

    fresh = run(lambda db: load_state(db, T0 + timedelta(seconds=29), STALE))
    stale = run(lambda db: load_state(db, T0 + timedelta(seconds=31), STALE))

    assert fresh.tasks[0].color == "green"
    assert len(fresh.tasks[0].sessions) == 1
    assert stale.tasks[0].color == "red"
    assert stale.tasks[0].sessions == []


def test_active_tasks_come_first_then_by_name_ignoring_case(run):
    listed(run, "beta", "Alpha", "zeta")
    state = run(lambda db: load_state(db, T0, STALE))
    zeta = next(t for t in state.tasks if t.name == "zeta")
    run(lambda db: set_active(db, zeta.id, False))

    names = [t.name for t in run(lambda db: load_state(db, T0, STALE)).tasks]
    assert names == ["Alpha", "beta", "zeta"]


def test_sessions_on_two_pcs_share_one_row(run):
    listed(run, "alpha")
    run(lambda db: ingest_snapshot(db, snap("desk", [sin("s1")]), T0))
    run(lambda db: ingest_snapshot(db, snap("laptop", [sin("s2")]), T0))

    state = run(lambda db: load_state(db, T0, STALE))
    assert [t.name for t in state.tasks] == ["alpha"]
    assert len(state.tasks[0].sessions) == 2


def test_a_session_of_an_unlisted_project_makes_no_row_but_still_counts(run):
    ingest(run, "desk", [sin("s1", "vs-code")], at(0))
    ingest(run, "desk", [sin("s1", "vs-code")], at(3))

    state = run(lambda db: load_state(db, at(3), STALE))
    assert state.tasks == []
    assert state.stats.today.busy_seconds == 3.0
    assert state.stats.today.peak_busy == 1


def test_a_removed_row_is_gone_and_a_second_removal_says_so(run):
    listed(run, "alpha")
    run(lambda db: ingest_snapshot(db, snap("desk", [sin("s1")]), T0))
    task_id = run(lambda db: load_state(db, T0, STALE)).tasks[0].id

    assert run(lambda db: remove_task(db, task_id)) is True
    assert run(lambda db: remove_task(db, task_id)) is False
    assert run(lambda db: load_state(db, T0, STALE)).tasks == []


def test_set_active(run):
    listed(run, "alpha")
    task_id = run(lambda db: load_state(db, T0, STALE)).tasks[0].id

    task = run(lambda db: set_active(db, task_id, False))
    assert task is not None
    assert task.active is False
    assert run(lambda db: set_active(db, 9999, True)) is None


def test_an_empty_snapshot_still_marks_the_host_seen(run):
    run(lambda db: ingest_snapshot(db, snap("desk", []), T0))
    assert run(lambda db: load_state(db, T0, STALE)).tasks == []


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def ingest(
    run,
    host: str,
    sessions: list[SessionIn],
    when: datetime,
    prompts: list[PromptIn] | None = None,
) -> None:
    run(lambda db: ingest_snapshot(db, snap(host, sessions, prompts), when, stale_after=STALE))


def stats(run, when: datetime = T0, timezone: str = "UTC"):
    return run(lambda db: load_state(db, when, STALE, timezone)).stats


def test_agent_time_is_the_time_each_session_spent_busy_or_waiting(run):
    asking = sin("s3").model_copy(update={"status": "waiting"})
    ingest(run, "desk", [sin("s1"), sin("s2"), asking], at(0))
    ingest(run, "desk", [sin("s1")], at(3))
    ingest(run, "desk", [sin("s1")], at(6))

    today = stats(run, at(6)).today
    # 0-3 s: two busy, one waiting (what the first snapshot reported); 3-6 s: one busy.
    assert today.busy_seconds == 9.0
    assert today.waiting_seconds == 3.0


def test_a_gap_longer_than_staleness_adds_no_agent_time(run):
    ingest(run, "desk", [sin("s1")], at(0))
    ingest(run, "desk", [sin("s1")], at(31))
    # A clock that went backwards adds nothing either.
    ingest(run, "desk", [sin("s1")], at(20))

    assert stats(run, at(31)).today.busy_seconds == 0.0


def test_the_peak_counts_busy_agents_across_pcs(run):
    ingest(run, "desk", [sin("s1"), sin("s2")], at(0))
    ingest(
        run, "laptop", [sin("s3"), sin("s4", "beta").model_copy(update={"status": "idle"})], at(1)
    )
    ingest(run, "desk", [], at(2))

    assert stats(run, at(2)).today.peak_busy == 3


def test_prompts_count_once_per_task_and_day(run):
    prompts = [
        PromptIn(session_id="s1", at=at(-60), project="alpha"),
        PromptIn(session_id="s1", at=at(-30), project="alpha"),
        PromptIn(session_id="s2", at=at(-10), project="itopia"),
    ]
    listed(run, "alpha")
    ingest(run, "desk", [sin("s1")], T0, prompts=prompts)
    # Sent again after a collector restart: not counted twice.
    ingest(run, "desk", [sin("s1")], at(1), prompts=prompts[:2])

    state = run(lambda db: load_state(db, at(1), STALE))
    assert {t.name: t.prompts_today for t in state.tasks} == {"alpha": 2}
    assert state.stats.today.prompts == 3


def test_dispatched_prompts_touch_no_count_record_or_streak(run):
    def sent(days_ago: int, n: int, dispatched: bool) -> list[PromptIn]:
        moment = T0 - timedelta(days=days_ago)
        return [
            PromptIn(
                session_id="s" + str(dispatched),
                at=moment + timedelta(seconds=i),
                project="alpha",
                dispatched=dispatched,
            )
            for i in range(n)
        ]

    listed(run, "alpha")
    # Yesterday was all fixers, ten of them; today you typed two and a fixer sent ten.
    ingest(run, "desk", [], T0, prompts=sent(1, 10, True) + sent(0, 2, False) + sent(0, 10, True))

    state = run(lambda db: load_state(db, T0, STALE))
    assert state.tasks[0].prompts_today == 2
    assert state.stats.today.prompts == 2
    assert state.stats.best.prompts == 0
    assert (state.stats.streak, state.stats.best_streak) == (1, 1)


def test_the_day_turns_over_at_midnight_in_the_configured_zone(run):
    # 03:00 UTC on the 28th is still the 27th in New York.
    early = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
    ingest(run, "desk", [], early, prompts=[PromptIn(session_id="s", at=early, project="alpha")])

    assert stats(run, early, "America/New_York").today.prompts == 1
    # At noon UTC it is the 28th everywhere: in UTC that prompt was today, in New York not.
    assert stats(run, T0, "UTC").today.prompts == 1
    assert stats(run, T0, "America/New_York").today.prompts == 0
    assert stats(run, T0, "America/New_York").best.prompts == 1


def test_records_and_streaks_come_from_earlier_days(run):
    def typed(days_ago: int, n: int) -> list[PromptIn]:
        moment = T0 - timedelta(days=days_ago)
        return [
            PromptIn(session_id="s", at=moment + timedelta(seconds=i), project="alpha")
            for i in range(n)
        ]

    ingest(run, "desk", [], T0, prompts=typed(5, 9) + typed(2, 4) + typed(1, 1) + typed(0, 2))
    board = stats(run)

    assert board.today.prompts == 2
    assert board.best.prompts == 9
    assert (board.streak, board.best_streak) == (3, 3)


def test_local_date_is_the_day_in_the_zone(run):
    early = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)

    def day(timezone: str):
        async def work(db):
            return (await db.execute(select(local_date(early, timezone)))).scalar_one()

        return run(work)

    assert day("UTC") == date(2026, 10, 28)
    assert day("America/New_York") == date(2026, 10, 27)


def test_load_stats_of_an_empty_history_is_all_zero(run):
    board = run(lambda db: load_stats(db, date(2026, 10, 28), "UTC"))
    assert board.today == DayStats()
    assert board.best == Records()
    assert (board.streak, board.best_streak) == (0, 0)


def test_check_timezone(run):
    run(lambda db: check_timezone(db, "America/New_York"))
    with pytest.raises(ValueError, match="Mars/Olympus"):
        run(lambda db: check_timezone(db, "Mars/Olympus"))
