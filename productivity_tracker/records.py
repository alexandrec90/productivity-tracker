"""The scoreboard's arithmetic: streaks and the records to beat, from day-by-day figures."""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from productivity_tracker.schemas import DayStats, Records

_ONE_DAY = timedelta(days=1)


def streaks(days: Iterable[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive days among `days`. The current run must reach
    today, or yesterday while today has none yet: the day is not over."""
    longest = run = 0
    previous: date | None = None
    for day in sorted({d for d in days if d <= today}):
        run = run + 1 if previous is not None and day - previous == _ONE_DAY else 1
        longest = max(longest, run)
        previous = day
    current = run if previous is not None and today - previous <= _ONE_DAY else 0
    return current, longest


def records(days: Mapping[date, DayStats], today: date) -> Records:
    """The best figures of the days before `today`, which is the day trying to beat them."""
    earlier = [stats for day, stats in days.items() if day < today]
    return Records(
        prompts=max((s.prompts for s in earlier), default=0),
        busy_seconds=max((s.busy_seconds for s in earlier), default=0.0),
        peak_busy=max((s.peak_busy for s in earlier), default=0),
    )
