"""The tables: tasks (one per project, across every PC), hosts, the sessions each host last
reported, and the history behind the scoreboard: prompts and daily agent activity."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func, text, true
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Host(Base):
    __tablename__ = "hosts"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    host: Mapped[str] = mapped_column(
        ForeignKey("hosts.name", ondelete="CASCADE"), primary_key=True
    )
    session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    pid: Mapped[int] = mapped_column(Integer)
    cwd: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    waiting_for: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(40))
    remote_session_id: Mapped[str | None] = mapped_column(String(100))
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Prompt(Base):
    """A prompt you typed, by when and where: never what. Kept by project name rather than
    task, so a project prompted before the collector ever saw it run creates no row."""

    __tablename__ = "prompts"

    host: Mapped[str] = mapped_column(String(200), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, index=True)
    project: Mapped[str] = mapped_column(String(200))


class DailyActivity(Base):
    """What the agents did each day, accumulated from the snapshots as they arrive."""

    __tablename__ = "daily_activity"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    busy_seconds: Mapped[float] = mapped_column(Float, server_default=text("0"))
    waiting_seconds: Mapped[float] = mapped_column(Float, server_default=text("0"))
    peak_busy: Mapped[int] = mapped_column(Integer, server_default=text("0"))


def make_engine(database_url: str) -> AsyncEngine:
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set: the server keeps its state in Postgres")
    return create_async_engine(database_url, pool_pre_ping=True)
