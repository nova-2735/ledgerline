"""Single source of "today" and "now", honouring APP_TODAY."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from app.config import get_settings

# India has no daylight saving, so a fixed offset avoids needing a tz database on Windows.
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def today() -> date:
    """Business date in Asia/Kolkata, or APP_TODAY when set."""
    override = get_settings().app_today
    if override is not None:
        return override
    return datetime.now(IST).date()


def now() -> datetime:
    """Current instant in UTC. With APP_TODAY set, the date is pinned and the clock time is real."""
    override = get_settings().app_today
    real = datetime.now(UTC)
    if override is None:
        return real
    local_time = real.astimezone(IST).timetz()
    return datetime.combine(override, local_time).astimezone(UTC)
