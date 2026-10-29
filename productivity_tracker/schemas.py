"""The API's request and response bodies."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from productivity_tracker.status import Color

Status = Literal["busy", "waiting", "idle"]


class SessionIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    pid: int
    project: str = Field(min_length=1, max_length=200)
    cwd: str
    status: Status
    waiting_for: str | None = None
    name: str | None = None
    kind: str | None = Field(default=None, max_length=40)
    remote_session_id: str | None = Field(default=None, max_length=100)
    status_updated_at: datetime | None = None


class PromptIn(BaseModel):
    # Empty for a prompt from a Claude Code old enough to record no session.
    session_id: str = Field(max_length=100)
    at: datetime
    project: str = Field(min_length=1, max_length=200)


class SnapshotIn(BaseModel):
    host: str = Field(min_length=1, max_length=200)
    sessions: list[SessionIn]
    # Prompts typed since the last report; a collector sends its history in batches this size.
    prompts: list[PromptIn] = Field(default_factory=list, max_length=1000)


class SessionOut(BaseModel):
    host: str
    session_id: str
    pid: int
    cwd: str
    status: Status
    waiting_for: str | None
    name: str | None
    kind: str | None
    remote_session_id: str | None
    status_updated_at: datetime | None


class TaskOut(BaseModel):
    id: int
    name: str
    active: bool
    color: Color
    sessions: list[SessionOut]
    prompts_today: int = 0


class DayStats(BaseModel):
    prompts: int = 0
    # Summed over agents: two agents busy for an hour is two hours.
    busy_seconds: float = 0.0
    # How long agents sat waiting on you, summed the same way.
    waiting_seconds: float = 0.0
    # The most agents busy at once.
    peak_busy: int = 0


class Records(BaseModel):
    """The best of every day before today, each figure on its own: they may be different days.
    Waiting has no record; less of it is better, and none at all is any quiet day."""

    prompts: int = 0
    busy_seconds: float = 0.0
    peak_busy: int = 0


class StatsOut(BaseModel):
    today: DayStats
    best: Records
    # Consecutive days with a prompt, up to today; a today without one yet does not break it.
    streak: int
    best_streak: int


class StateOut(BaseModel):
    generated_at: datetime
    tasks: list[TaskOut]
    stats: StatsOut


class ActiveIn(BaseModel):
    active: bool
