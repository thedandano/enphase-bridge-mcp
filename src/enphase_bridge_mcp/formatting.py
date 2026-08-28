"""Conversions between bridge units/timestamps and what the LLM should see.

The bridge speaks Wh and unix timestamps in UTC. The LLM should see kWh
(rounded to 2 decimal places) and Pacific-time ISO 8601 strings, since the
user is in America/Los_Angeles.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def wh_to_kwh(wh: float) -> float:
    """Convert watt-hours to kilowatt-hours, rounded to 2 decimal places."""
    return round(wh / 1000, 2)


def epoch_to_pacific_iso(ts: int) -> str:
    """Convert a unix epoch timestamp to a Pacific-time ISO 8601 string."""
    return datetime.fromtimestamp(ts, tz=PACIFIC).isoformat()


def pacific_day_bounds(date_spec: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the UTC (start, end) bounds of a Pacific civil day.

    ``date_spec`` is one of "today", "yesterday", or "YYYY-MM-DD".
    "today"/"yesterday" are resolved relative to ``now`` (an aware
    datetime), which defaults to the real current time — pass an explicit
    ``now`` in tests to pin the result. Raises ValueError for any other
    ``date_spec``.
    """
    if date_spec == "today":
        target_date = (now or datetime.now(tz=UTC)).astimezone(PACIFIC).date()
    elif date_spec == "yesterday":
        target_date = (now or datetime.now(tz=UTC)).astimezone(PACIFIC).date() - timedelta(days=1)
    else:
        try:
            target_date = date.fromisoformat(date_spec)
        except ValueError as exc:
            raise ValueError(
                f"Invalid date_spec {date_spec!r}: expected 'today', 'yesterday', or 'YYYY-MM-DD'"
            ) from exc

    start_pacific = datetime(target_date.year, target_date.month, target_date.day, tzinfo=PACIFIC)
    end_pacific = start_pacific + timedelta(days=1)
    return start_pacific.astimezone(UTC), end_pacific.astimezone(UTC)
