"""Clicks on their way to the PC whose session was clicked.

The overlay cannot reach into a remote desktop, so it leaves the click here and that PC's
collector, already waiting on `take`, carries it out. Kept in memory: a click is worth
seconds, so it has no business surviving a restart. The server runs one process, so this one
object is every collector's and overlay's.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable

# Long enough for a Remote Desktop window that was closed to connect and sign in, no longer:
# a click from a minute ago must not steal the screen when the PC comes back.
FOCUS_TTL_SECONDS = 30.0


class FocusBroker:
    """One waiting click per host: a newer click replaces what you asked for before."""

    def __init__(
        self,
        ttl: float = FOCUS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.clock = clock
        self._pending: dict[str, tuple[int, float]] = {}
        self._posted: defaultdict[str, asyncio.Event] = defaultdict(asyncio.Event)

    def put(self, host: str, pid: int) -> None:
        key = host.lower()
        self._pending[key] = (pid, self.clock())
        self._posted[key].set()

    def _pop_fresh(self, key: str) -> int | None:
        pid, at = self._pending.pop(key, (None, 0.0))
        return pid if pid is not None and self.clock() - at <= self.ttl else None

    async def take(self, host: str, wait: float) -> int | None:
        """The pid waiting for `host`, or None once `wait` seconds pass without one."""
        key = host.lower()
        posted = self._posted[key]
        try:
            async with asyncio.timeout(wait):
                while True:
                    pid = self._pop_fresh(key)
                    if pid is not None:
                        return pid
                    posted.clear()
                    await posted.wait()
        except TimeoutError:
            return None
