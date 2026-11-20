"""Single source of "today" and "now", honouring APP_TODAY and a backdated clock for seeding."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta, timezone

from app.config import get_settings

# India has no daylight saving, so a fixed offset avoids needing a tz database on Windows.
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

# (instant the clock was set to, perf_counter at that moment); per thread / task.
_backdated: ContextVar[tuple[datetime, float] | None] = ContextVar("backdated", default=None)


@contextmanager
def backdated(at: datetime) -> Iterator[None]:
    """Run code as if it were `at` (time still advances in real time). Used to seed history."""
    if at.tzinfo is None:
        raise ValueError("backdated() needs an aware datetime")
    token = _backdated.set((at.astimezone(UTC), time.perf_counter()))
    try:
        yield
    finally:
        _backdated.reset(token)


def today() -> date:
    """Business date in Asia/Kolkata, or APP_TODAY when set."""
    pinned = _backdated.get()
    if pinned is not None:
        return now().astimezone(IST).date()
    override = get_settings().app_today
    if override is not None:
        return override
    return datetime.now(IST).date()


def now() -> datetime:
    """Current instant in UTC. With APP_TODAY set, the date is pinned and the clock time is real."""
    pinned = _backdated.get()
    if pinned is not None:
        start, mark = pinned
        return start + timedelta(seconds=time.perf_counter() - mark)
    override = get_settings().app_today
    real = datetime.now(UTC)
    if override is None:
        return real
    local_time = real.astimezone(IST).timetz()
    return datetime.combine(override, local_time).astimezone(UTC)
