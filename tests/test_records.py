from datetime import date, timedelta

from productivity_tracker.records import records, streaks
from productivity_tracker.schemas import DayStats, Records

TODAY = date(2026, 10, 28)


def ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def test_a_run_reaching_today_is_the_current_streak():
    assert streaks([ago(2), ago(1), TODAY], TODAY) == (3, 3)


def test_today_without_a_prompt_yet_does_not_break_the_streak():
    assert streaks([ago(2), ago(1)], TODAY) == (2, 2)


def test_a_missed_day_ends_the_streak_but_not_the_record():
    days = [ago(10), ago(9), ago(8), ago(7), ago(2), TODAY]
    assert streaks(days, TODAY) == (1, 4)
    assert streaks(days[:-1], TODAY) == (0, 4)


def test_no_days_is_no_streak():
    assert streaks([], TODAY) == (0, 0)


def test_repeated_and_future_days_are_ignored():
    assert streaks([TODAY, TODAY, ago(1), TODAY + timedelta(days=1)], TODAY) == (2, 2)


def test_records_are_the_best_of_each_figure_before_today():
    days = {
        ago(2): DayStats(prompts=40, busy_seconds=100.0, peak_busy=5),
        ago(1): DayStats(prompts=10, busy_seconds=900.0, peak_busy=2),
        # Today never counts against itself, or it could never beat a record.
        TODAY: DayStats(prompts=99, busy_seconds=9999.0, peak_busy=9),
    }
    assert records(days, TODAY) == Records(prompts=40, busy_seconds=900.0, peak_busy=5)


def test_the_first_day_has_no_records_to_beat():
    assert records({TODAY: DayStats(prompts=3)}, TODAY) == Records()
