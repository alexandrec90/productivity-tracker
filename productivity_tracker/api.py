"""The HTTP API every collector reports to and the overlay reads from."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from productivity_tracker import store
from productivity_tracker.config import Settings
from productivity_tracker.db import make_engine
from productivity_tracker.schemas import ActiveIn, SnapshotIn, StateOut, TaskOut
from productivity_tracker.status import task_color


def token_matches(expected: str, authorization: str | None) -> bool:
    """No token configured on the server means no check; otherwise the bearer must match."""
    if not expected:
        return True
    scheme, _, supplied = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(supplied, expected)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with app.state.sessionmaker() as db:
            await store.check_timezone(db, settings.tracker_timezone)
        yield
        await engine.dispose()

    async def database(request: Request) -> AsyncIterator[AsyncSession]:
        async with request.app.state.sessionmaker() as db:
            yield db

    def authorized(authorization: Annotated[str | None, Header()] = None) -> None:
        if not token_matches(settings.tracker_token, authorization):
            raise HTTPException(status_code=401, detail="missing or wrong bearer token")

    Db = Annotated[AsyncSession, Depends(database)]
    stale_after = timedelta(seconds=settings.stale_after_seconds)
    app = FastAPI(title="Productivity Tracker", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/snapshots", status_code=204, dependencies=[Depends(authorized)])
    async def post_snapshot(snapshot: SnapshotIn, db: Db) -> Response:
        await store.ingest_snapshot(
            db,
            snapshot,
            datetime.now(UTC),
            timezone=settings.tracker_timezone,
            stale_after=stale_after,
        )
        return Response(status_code=204)

    @app.get("/state", dependencies=[Depends(authorized)])
    async def get_state(db: Db) -> StateOut:
        return await store.load_state(db, datetime.now(UTC), stale_after, settings.tracker_timezone)

    @app.put("/tasks/{task_id}/active", dependencies=[Depends(authorized)])
    async def put_active(task_id: int, body: ActiveIn, db: Db) -> TaskOut:
        task = await store.set_active(db, task_id, body.active)
        if task is None:
            raise HTTPException(status_code=404, detail=f"no task {task_id}")
        # The overlay re-reads /state for the sessions; this answer only confirms the flag.
        return TaskOut(
            id=task.id,
            name=task.name,
            active=task.active,
            color=task_color(task.active, []),
            sessions=[],
        )

    return app
