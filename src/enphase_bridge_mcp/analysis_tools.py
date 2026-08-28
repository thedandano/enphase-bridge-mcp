"""Milestone-2 analysis tools: period summaries/comparisons and inverter health.

Split out of `server.py` to keep that module from growing past a screenful.
Registers its `@server.tool()`s on the same `MCPServer` instance imported
from `.server`; `server.py` imports this module once (for the import-time
registration side effect) so `main()` still sees every tool.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from .bridge_client import BridgeClient
from .formatting import PACIFIC, epoch_to_pacific_iso, pacific_day_bounds, wh_to_kwh
from .server import _build_client, _now, _pct_diff, server

_INVERTER_STALE_SECONDS = 20 * 60
"""Same collector-health threshold `get_current_status.is_online` uses."""

_MAX_PERIOD_DAYS = 92


class DayProduced(BaseModel):
    """One day's production, used for `PeriodSummary.best_day`/`worst_day`."""

    date: str
    """Pacific civil date, as YYYY-MM-DD."""
    produced_kwh: float


class DailyTotal(BaseModel):
    """One day's energy totals within a `PeriodSummary.daily_breakdown`."""

    date: str
    """Pacific civil date, as YYYY-MM-DD."""
    produced_kwh: float
    consumed_kwh: float
    net_kwh: float
    """produced_kwh - consumed_kwh for that day."""
    has_data: bool
    """False if the bridge recorded no windows for this day — its totals above
    are 0.0 because of that gap (collector outage, day not reached yet), not
    because production/consumption were genuinely zero."""
    is_partial: bool
    """True if this Pacific civil day has not fully elapsed yet as of the
    summary's reference time (it is "today" and still in progress, or it is
    still in the future). A partial day's totals only cover the time elapsed
    so far, so comparing them against a finished day is apples-to-oranges."""


class PeriodSummary(BaseModel):
    """Aggregated energy totals for a range of Pacific civil days, inclusive of both ends."""

    start_date: str
    end_date: str
    day_count: int
    """Number of calendar days in the range, inclusive of both ends."""
    produced_kwh: float
    consumed_kwh: float
    imported_kwh: float
    exported_kwh: float
    net_kwh: float
    """produced_kwh - consumed_kwh across the whole period."""
    self_consumption_pct: float
    """Share of produced energy consumed on-site rather than exported, 0-100."""
    avg_daily_produced_kwh: float
    """produced_kwh / number of days in the range that have at least one
    recorded window (`DailyTotal.has_data`), not the raw calendar `day_count` —
    days the bridge has no data for (collector gap, or a day not reached yet)
    would otherwise silently drag this down. If the range includes a
    still-in-progress "today", its partial-day production is included in both
    the numerator and this denominator as-is (counted like a full day)."""
    best_day: DayProduced
    """The highest-production day in the range, considering only finished days
    that have recorded data (excludes gaps and any still-in-progress "today")."""
    worst_day: DayProduced
    """The lowest-production day in the range, considering only finished days
    that have recorded data (excludes gaps and any still-in-progress "today")."""
    daily_breakdown: list[DailyTotal]
    """One entry per calendar day in the range, oldest first. A day with no
    windows recorded by the bridge appears with all totals at 0.0 and
    `has_data=False` — see `DailyTotal`."""
    data_completeness_pct: float
    """Share of the period's expected 15-minute windows marked complete by the bridge, 0-100."""


class PeriodComparison(BaseModel):
    """Two period summaries plus the deltas between them (period_a minus period_b)."""

    period_a: PeriodSummary
    period_b: PeriodSummary
    produced_kwh_diff: float
    produced_pct_diff: float
    """Percent change in produced_kwh, period_a vs period_b. 0.0 if period_b's value is zero."""
    consumed_kwh_diff: float
    consumed_pct_diff: float
    """Percent change in consumed_kwh, period_a vs period_b. 0.0 if period_b's value is zero."""
    net_kwh_diff: float
    net_pct_diff: float
    """Percent change in net_kwh, period_a vs period_b. 0.0 if period_b's value is zero."""


class InverterArraySummary(BaseModel):
    """Health of one configured inverter array."""

    name: str
    total_watts: float
    """Sum of this array's inverters' output as of `InverterHealth.data_as_of`, in
    watts. This is a snapshot, not necessarily current output right now — see
    `InverterHealth.is_stale`."""
    online_count: int
    total_count: int


class OfflineInverter(BaseModel):
    """One inverter the bridge currently reports offline."""

    serial: str
    array: str
    watts_output: float
    """Last-known output, in watts. 0.0 if the bridge has never seen this inverter report."""
    last_report_at: str | None
    """Pacific ISO 8601 timestamp this inverter last reported data, or None if
    the bridge has never seen this inverter report at all."""


class InverterHealth(BaseModel):
    """Per-array inverter health, plus any inverters needing attention."""

    arrays: list[InverterArraySummary]
    attention_needed: list[OfflineInverter]
    """Every inverter across the reported arrays currently marked offline by the bridge."""
    data_as_of: str
    """Pacific ISO 8601 timestamp of the inverter snapshot window this whole
    report reflects. The bridge only stores the single most recent snapshot
    per inverter with no recency filter, so this can be stale if the
    collector has stopped — see `is_stale`."""
    is_stale: bool
    """True if `data_as_of` is more than ~20 minutes old (the same
    collector-health threshold `get_current_status.is_online` uses), meaning
    every field above reflects a snapshot the bridge has not refreshed
    recently rather than live inverter state."""


def _parse_period_date(label: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} {value!r}: expected 'YYYY-MM-DD'") from exc


def _validate_period(start_date: str, end_date: str) -> tuple[date, date]:
    """Parse and validate a Pacific civil-day range, inclusive of both ends.

    Raises:
        ValueError: either date is malformed, `end_date` precedes `start_date`,
            or the range exceeds `_MAX_PERIOD_DAYS` days.
    """
    start = _parse_period_date("start_date", start_date)
    end = _parse_period_date("end_date", end_date)
    if end < start:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}")
    day_count = (end - start).days + 1
    if day_count > _MAX_PERIOD_DAYS:
        raise ValueError(
            f"range too large; max {_MAX_PERIOD_DAYS} days per call (requested {day_count} days)"
        )
    return start, end


async def _build_period_summary(
    client: BridgeClient, start_date: str, end_date: str, now: datetime
) -> PeriodSummary:
    """Fetch and aggregate one Pacific date range's windows into a `PeriodSummary`.

    Pages the bridge's windows endpoint exactly once for the whole range,
    then groups the results in memory per Pacific day.

    Raises:
        ValueError: invalid/reversed dates, or a range over `_MAX_PERIOD_DAYS` days.
        ToolError: the bridge has no windows recorded anywhere in the range.
    """
    start, end = _validate_period(start_date, end_date)
    range_start_utc, _ = pacific_day_bounds(start.isoformat())
    _, range_end_utc = pacific_day_bounds(end.isoformat())

    windows = await client.list_windows(range_start_utc, range_end_utc)
    if not windows:
        raise ToolError(
            f"enphase-bridge has no energy data between {start_date} and {end_date} (Pacific)"
        )

    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        window_day = datetime.fromtimestamp(int(window["window_start"]), tz=PACIFIC).date()
        by_day[window_day].append(window)

    day_count = (end - start).days + 1
    all_days = [start + timedelta(days=i) for i in range(day_count)]

    daily_breakdown: list[DailyTotal] = []
    expected_windows = 0
    complete_count = 0
    for day in all_days:
        day_windows = by_day.get(day, [])
        day_produced_kwh = wh_to_kwh(sum(w["wh_produced"] for w in day_windows))
        day_consumed_kwh = wh_to_kwh(sum(w["wh_consumed"] for w in day_windows))
        day_start_utc, day_end_utc = pacific_day_bounds(day.isoformat())
        is_partial = now < day_end_utc
        daily_breakdown.append(
            DailyTotal(
                date=day.isoformat(),
                produced_kwh=day_produced_kwh,
                consumed_kwh=day_consumed_kwh,
                net_kwh=round(day_produced_kwh - day_consumed_kwh, 2),
                has_data=bool(day_windows),
                is_partial=is_partial,
            )
        )

        day_elapsed = (min(now, day_end_utc) - day_start_utc).total_seconds()
        expected_windows += max(0, int(day_elapsed // 900))
        complete_count += sum(1 for w in day_windows if w["is_complete"])

    produced_wh = sum(w["wh_produced"] for w in windows)
    consumed_wh = sum(w["wh_consumed"] for w in windows)
    imported_wh = sum(w["wh_grid_import"] for w in windows)
    exported_wh = sum(w["wh_grid_export"] for w in windows)

    produced_kwh = wh_to_kwh(produced_wh)
    consumed_kwh = wh_to_kwh(consumed_wh)
    imported_kwh = wh_to_kwh(imported_wh)
    exported_kwh = wh_to_kwh(exported_wh)
    net_kwh = round(produced_kwh - consumed_kwh, 2)

    self_consumption_pct = (
        round(max(0.0, min(100.0, (produced_wh - exported_wh) / produced_wh * 100)), 2)
        if produced_wh > 0
        else 0.0
    )
    contributing_day_count = sum(1 for d in daily_breakdown if d.has_data)
    avg_daily_produced_kwh = (
        round(produced_kwh / contributing_day_count, 2) if contributing_day_count > 0 else 0.0
    )

    finished_days_with_data = [d for d in daily_breakdown if d.has_data and not d.is_partial]
    if not finished_days_with_data:
        raise ToolError(
            f"enphase-bridge has no completed day with data between {start_date} and "
            f"{end_date} (Pacific) to determine the best/worst day"
        )
    best = max(finished_days_with_data, key=lambda d: d.produced_kwh)
    worst = min(finished_days_with_data, key=lambda d: d.produced_kwh)

    data_completeness_pct = (
        round(complete_count / expected_windows * 100, 2) if expected_windows > 0 else 0.0
    )

    return PeriodSummary(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        day_count=day_count,
        produced_kwh=produced_kwh,
        consumed_kwh=consumed_kwh,
        imported_kwh=imported_kwh,
        exported_kwh=exported_kwh,
        net_kwh=net_kwh,
        self_consumption_pct=self_consumption_pct,
        avg_daily_produced_kwh=avg_daily_produced_kwh,
        best_day=DayProduced(date=best.date, produced_kwh=best.produced_kwh),
        worst_day=DayProduced(date=worst.date, produced_kwh=worst.produced_kwh),
        daily_breakdown=daily_breakdown,
        data_completeness_pct=data_completeness_pct,
    )


@server.tool()
async def get_period_summary(start_date: str, end_date: str) -> PeriodSummary:
    """Get aggregated energy totals for a range of Pacific civil days, inclusive of both ends.

    `start_date` and `end_date` are explicit Pacific dates as "YYYY-MM-DD"
    (no "today"/"yesterday" shorthand); the range is capped at 92 days per
    call. Returns period totals (produced/consumed/imported/exported/net
    kWh), self-consumption percentage, average daily production, the single
    best and worst day by production, a full day-by-day breakdown, and what
    share of the period's expected 15-minute windows the bridge marked
    complete. If the range includes today, today appears in the breakdown as
    a partial, still-in-progress day, but is excluded from average/best/worst
    day calculations (see `PeriodSummary.avg_daily_produced_kwh`/`best_day`/
    `worst_day`) so it is never compared against finished days as if it were
    one. Raises an error for invalid or reversed dates, a range over 92 days,
    if the bridge has no data anywhere in the range, or if no day in the
    range is both finished and has recorded data.
    """
    client = _build_client()
    try:
        return await _build_period_summary(client, start_date, end_date, _now())
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
async def compare_periods(start_a: str, end_a: str, start_b: str, end_b: str) -> PeriodComparison:
    """Compare energy totals between two ranges of Pacific civil days.

    Each range is "YYYY-MM-DD" start/end, inclusive of both ends and capped
    at 92 days. Returns the full `PeriodSummary` for both periods (each
    carries its own `day_count`, since the two ranges may differ in length —
    caveat any comparison accordingly) plus kWh and percent deltas (period A
    relative to period B) for produced, consumed, and net energy. Percent
    deltas are 0.0 when period B's value is zero. Each period's average/best/
    worst day figures exclude that period's still-in-progress "today", if
    it includes one — see `get_period_summary`. Raises an error for
    invalid/reversed dates (naming which period, A or B, is at fault), either
    range exceeding 92 days, or if either period has no data.
    """
    try:
        _validate_period(start_a, end_a)
    except ValueError as exc:
        raise ToolError(f"period A: {exc}") from exc
    try:
        _validate_period(start_b, end_b)
    except ValueError as exc:
        raise ToolError(f"period B: {exc}") from exc

    client = _build_client()
    now = _now()
    period_a = await _build_period_summary(client, start_a, end_a, now)
    period_b = await _build_period_summary(client, start_b, end_b, now)

    return PeriodComparison(
        period_a=period_a,
        period_b=period_b,
        produced_kwh_diff=round(period_a.produced_kwh - period_b.produced_kwh, 2),
        produced_pct_diff=_pct_diff(period_a.produced_kwh, period_b.produced_kwh),
        consumed_kwh_diff=round(period_a.consumed_kwh - period_b.consumed_kwh, 2),
        consumed_pct_diff=_pct_diff(period_a.consumed_kwh, period_b.consumed_kwh),
        net_kwh_diff=round(period_a.net_kwh - period_b.net_kwh, 2),
        net_pct_diff=_pct_diff(period_a.net_kwh, period_b.net_kwh),
    )


@server.tool()
async def get_inverter_health(array_name: str | None = None) -> InverterHealth:
    """Get per-array inverter health: online/offline counts and any inverters needing attention.

    With no `array_name`, reports every configured array. Pass `array_name`
    to scope the report to a single array (case-sensitive, must match a name
    in the bridge's config); an unknown name raises an error listing the
    valid array names. `attention_needed` lists every inverter (serial
    number, its array, its last-reported watts, and when it last reported)
    currently reported offline by the bridge, across whichever array(s) are
    in scope. The bridge only keeps the single most recent inverter snapshot
    with no recency filter, so `data_as_of`/`is_stale` say how fresh this
    whole report is — a bridge whose collector died still returns its last
    snapshot rather than an error. Raises an error if the bridge is
    unreachable, or if no inverter data has been recorded yet.
    """
    client = _build_client()
    result = await client.get_inverter_arrays()
    raw_arrays: list[dict[str, Any]] = result["arrays"]
    if not raw_arrays:
        raise ToolError("enphase-bridge has no inverter array data yet")

    window_start = int(result["window_start"])
    data_as_of = epoch_to_pacific_iso(window_start)
    is_stale = (_now().timestamp() - (window_start + 900)) > _INVERTER_STALE_SECONDS

    if array_name is not None:
        raw_arrays = [a for a in raw_arrays if a["name"] == array_name]
        if not raw_arrays:
            valid = ", ".join(sorted(a["name"] for a in result["arrays"]))
            raise ToolError(f"Unknown array_name {array_name!r}; valid arrays: {valid}")

    arrays = [
        InverterArraySummary(
            name=a["name"],
            total_watts=float(a["total_watts"]),
            online_count=int(a["online_count"]),
            total_count=int(a["total_count"]),
        )
        for a in raw_arrays
    ]
    attention_needed = [
        OfflineInverter(
            serial=inverter["serial_number"],
            array=a["name"],
            watts_output=float(inverter["watts_output"]),
            last_report_at=(
                epoch_to_pacific_iso(int(inverter["last_report_date"]))
                if inverter["last_report_date"]
                else None
            ),
        )
        for a in raw_arrays
        for inverter in a["inverters"]
        if not inverter["is_online"]
    ]

    return InverterHealth(
        arrays=arrays,
        attention_needed=attention_needed,
        data_as_of=data_as_of,
        is_stale=is_stale,
    )
