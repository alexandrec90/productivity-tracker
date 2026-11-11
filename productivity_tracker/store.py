"""Reads and writes behind the API: ingest a host's snapshot, build the overlay's state."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, Text, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from productivity_tracker.db import AgentSession, DailyActivity, Host, Prompt, Task
from productivity_tracker.records import records, streaks
from productivity_tracker.schemas import (
    DayStats,
    SessionOut,
    SnapshotIn,
    StateOut,
    StatsOut,
    TaskOut,
)
from productivity_tracker.status import BUSY, WAITING, task_color

DEFAULT_STALE = timedelta(seconds=30)


def local_date(moment: Any, timezone: str) -> ColumnElement[date]:
    """The calendar day `moment` (a timestamptz column or a datetime) falls on in `timezone`,
    worked out by Postgres, which carries the time-zone database."""
    return func.date(func.timezone(cast(timezone, Text), moment), type_=Date)


async def check_timezone(db: AsyncSession, timezone: str) -> None:
    """Fail at start-up, not on every request, when Postgres does not know `timezone`."""
    try:
        await db.execute(select(local_date(func.now(), timezone)))
    except DBAPIError as exc:
        raise ValueError(
            f"TRACKER_TIMEZONE={timezone!r} is not a time zone Postgres knows"
            " (use an IANA name such as America/New_York)"
        ) from exc


async def ingest_snapshot(
    db: AsyncSession,
    snapshot: SnapshotIn,
    now: datetime,
    *,
    timezone: str = "UTC",
    stale_after: timedelta = DEFAULT_STALE,
) -> None:
    """Replace everything known about the snapshot's host with it; keep its new prompts; and
    add the time since the host's last snapshot to today's agent activity. A session of a
    project with no row is kept, on no task: the list is yours, so a project does not put
    itself on it, and adding the row later picks its sessions up."""
    host = snapshot.host
    busy, waiting = await _time_since_last_report(db, host, now, stale_after)
    # One row per session id: the last one in the snapshot wins.
    unique = list({s.session_id: s for s in snapshot.sessions}.values())
    # Likewise per prompt: an upsert may not touch one row twice in a statement.
    prompts = list({(p.session_id, p.at): p for p in snapshot.prompts}.values())
    await db.execute(
        insert(Host)
        .values(name=host, last_seen_at=now)
        .on_conflict_do_update(index_elements=[Host.name], set_={"last_seen_at": now})
    )
    names = {s.project for s in unique}
    rows = await db.execute(select(Task.name, Task.id).where(Task.name.in_(names)))
    task_ids: dict[str, int] = {name: task_id for name, task_id in rows}
    await db.execute(delete(AgentSession).where(AgentSession.host == host))
    db.add_all(
        AgentSession(
            host=host,
            task_id=task_ids.get(s.project),
            **s.model_dump(exclude={"project"}),
        )
        for s in unique
    )
    if prompts:
        # A collector sends its whole history once, and again after a restart: a prompt the
        # server already has is not counted twice, but takes on what the collector now knows
        # about it, which is how prompts from before `dispatched` got sorted out.
        added_prompts = insert(Prompt).values([{"host": host, **p.model_dump()} for p in prompts])
        await db.execute(
            added_prompts.on_conflict_do_update(
                index_elements=[Prompt.host, Prompt.session_id, Prompt.at],
                set_={"dispatched": added_prompts.excluded.dispatched},
            )
        )
    peak = await db.scalar(
        select(func.count())
        .select_from(AgentSession)
        .join(Host, Host.name == AgentSession.host)
        .where(Host.last_seen_at >= now - stale_after, AgentSession.status == BUSY)
    )
    added = insert(DailyActivity).values(
        day=local_date(now, timezone),
        busy_seconds=busy,
        waiting_seconds=waiting,
        peak_busy=peak or 0,
    )
    await db.execute(
        added.on_conflict_do_update(
            index_elements=[DailyActivity.day],
            set_={
                "busy_seconds": DailyActivity.busy_seconds + added.excluded.busy_seconds,
                "waiting_seconds": DailyActivity.waiting_seconds + added.excluded.waiting_seconds,
                "peak_busy": func.greatest(DailyActivity.peak_busy, added.excluded.peak_busy),
            },
        )
    )
    await db.commit()


async def _time_since_last_report(
    db: AsyncSession, host: str, now: datetime, stale_after: timedelta
) -> tuple[float, float]:
    """Agent-seconds busy and waiting on `host` since its last snapshot, taking the sessions
    it reported then as unchanged until now. A gap longer than `stale_after` counts nothing:
    the PC was asleep or off, and its agents with it."""
    previous = await db.scalar(select(Host.last_seen_at).where(Host.name == host))
    if previous is None:
        return 0.0, 0.0
    elapsed = (now - previous).total_seconds()
    if not 0 < elapsed <= stale_after.total_seconds():
        return 0.0, 0.0
    statuses = (
        await db.scalars(select(AgentSession.status).where(AgentSession.host == host))
    ).all()
    return elapsed * statuses.count(BUSY), elapsed * statuses.count(WAITING)


async def load_state(
    db: AsyncSession, now: datetime, stale_after: timedelta, timezone: str = "UTC"
) -> StateOut:
    """Every task with its live sessions, active tasks first, and the scoreboard. Sessions of
    a host that has not reported since `now - stale_after` are left out: that PC is asleep or
    off."""
    tasks = (await db.scalars(select(Task))).all()
    sessions = (
        await db.scalars(
            select(AgentSession)
            .join(Host, Host.name == AgentSession.host)
            .where(Host.last_seen_at >= now - stale_after)
        )
    ).all()
    by_task: dict[int, list[AgentSession]] = defaultdict(list)
    for session in sessions:
        if session.task_id is not None:
            by_task[session.task_id].append(session)
    today = (await db.execute(select(local_date(now, timezone)))).scalar_one()
    prompted = await db.execute(
        select(Prompt.project, func.count())
        # The range keeps the index in play; the day test is the exact one.
        .where(
            Prompt.at >= now - timedelta(days=2),
            local_date(Prompt.at, timezone) == today,
            Prompt.dispatched.is_(False),
        )
        .group_by(Prompt.project)
    )
    prompts_today: dict[str, int] = {project: count for project, count in prompted}
    out = [
        TaskOut(
            id=task.id,
            name=task.name,
            active=task.active,
            color=task_color(task.active, (s.status for s in by_task[task.id])),
            sessions=[
                SessionOut.model_validate(s, from_attributes=True)
                for s in sorted(by_task[task.id], key=lambda s: (s.host, s.session_id))
            ],
            prompts_today=prompts_today.get(task.name, 0),
        )
        for task in tasks
    ]
    out.sort(key=lambda t: (not t.active, t.name.lower()))
    return StateOut(generated_at=now, tasks=out, stats=await load_stats(db, today, timezone))


async def load_stats(db: AsyncSession, today: date, timezone: str) -> StatsOut:
    """Today's figures against the records of every day before it, and the prompt streak."""
    day = local_date(Prompt.at, timezone)
    typed = select(day, func.count()).where(Prompt.dispatched.is_(False)).group_by(day)
    prompt_days = {d: n for d, n in await db.execute(typed)}
    days = {d: DayStats(prompts=n) for d, n in prompt_days.items()}
    for activity in (await db.scalars(select(DailyActivity))).all():
        days[activity.day] = DayStats(
            prompts=prompt_days.get(activity.day, 0),
            busy_seconds=activity.busy_seconds,
            waiting_seconds=activity.waiting_seconds,
            peak_busy=activity.peak_busy,
        )
    current, longest = streaks(prompt_days, today)
    return StatsOut(
        today=days.get(today, DayStats()),
        best=records(days, today),
        streak=current,
        best_streak=longest,
    )


async def add_task(db: AsyncSession, name: str) -> Task:
    """Put `name` on the list; adding a name already there changes nothing. Its sessions join
    it on their PC's next report."""
    await db.execute(
        insert(Task).values(name=name).on_conflict_do_nothing(index_elements=[Task.name])
    )
    await db.commit()
    return (await db.scalars(select(Task).where(Task.name == name))).one()


async def remove_task(db: AsyncSession, task_id: int) -> bool:
    """Take a row off the list. Its sessions and prompts stay: they count toward the
    scoreboard, and adding the row back finds them."""
    task = await db.get(Task, task_id)
    if task is None:
        return False
    await db.delete(task)
    await db.commit()
    return True


async def set_active(db: AsyncSession, task_id: int, active: bool) -> Task | None:
    task = await db.get(Task, task_id)
    if task is None:
        return None
    task.active = active
    await db.commit()
    return task
