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

from .bridge_client import BridgeClient
from .formatting import PACIFIC, epoch_to_pacific_iso, pacific_day_bounds, wh_to_kwh
from .models import (
    DailyTotal,
    DayProduced,
    InverterArraySummary,
    InverterHealth,
    OfflineInverter,
    PeriodComparison,
    PeriodSummary,
)
from .server import _build_client, _now, _pct_diff, server

_INVERTER_STALE_SECONDS = 20 * 60
"""Same collector-health threshold `get_current_status.is_online` uses."""

_MAX_PERIOD_DAYS = 92


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


def _group_windows_by_pacific_day(
    windows: list[dict[str, Any]],
) -> dict[date, list[dict[str, Any]]]:
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for window in windows:
        window_day = datetime.fromtimestamp(int(window["window_start"]), tz=PACIFIC).date()
        by_day[window_day].append(window)
    return by_day


def _day_stats(day: date, day_windows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Raw (unrounded) per-day figures for one calendar day in a period.

    Keeping Wh figures raw here — rather than converting to kWh immediately —
    means every downstream consumer (the average, best/worst-day picks, and
    the `DailyTotal` built for `daily_breakdown`) rounds from the same
    unrounded source exactly once, instead of compounding independent
    per-day roundings into further arithmetic.
    """
    day_start_utc, day_end_utc = pacific_day_bounds(day.isoformat())
    day_elapsed = (min(now, day_end_utc) - day_start_utc).total_seconds()
    return {
        "day": day,
        "produced_wh": sum(w["wh_produced"] for w in day_windows),
        "consumed_wh": sum(w["wh_consumed"] for w in day_windows),
        "has_data": bool(day_windows),
        "is_partial": now < day_end_utc,
        "expected_windows": max(0, int(day_elapsed // 900)),
        "complete_count": sum(1 for w in day_windows if w["is_complete"]),
    }


def _daily_total(stats: dict[str, Any]) -> DailyTotal:
    produced_kwh = wh_to_kwh(stats["produced_wh"])
    consumed_kwh = wh_to_kwh(stats["consumed_wh"])
    day: date = stats["day"]
    return DailyTotal(
        date=day.isoformat(),
        produced_kwh=produced_kwh,
        consumed_kwh=consumed_kwh,
        net_kwh=round(produced_kwh - consumed_kwh, 2),
        has_data=stats["has_data"],
        is_partial=stats["is_partial"],
    )


def _avg_daily_produced_kwh(finished_days: list[dict[str, Any]]) -> float | None:
    """Average produced kWh over finished days with data only (see
    `PeriodSummary.avg_daily_produced_kwh` for why). None when there are no
    finished days — "not available yet" must not read as "0 kWh average"."""
    if not finished_days:
        return None
    total_wh: float = sum(float(s["produced_wh"]) for s in finished_days)
    return round(total_wh / 1000 / len(finished_days), 2)


def _best_worst_days(
    finished_days: list[dict[str, Any]],
) -> tuple[DayProduced | None, DayProduced | None]:
    if not finished_days:
        return (None, None)
    best = max(finished_days, key=lambda s: s["produced_wh"])
    worst = min(finished_days, key=lambda s: s["produced_wh"])
    best_day: date = best["day"]
    worst_day: date = worst["day"]
    return (
        DayProduced(date=best_day.isoformat(), produced_kwh=wh_to_kwh(best["produced_wh"])),
        DayProduced(date=worst_day.isoformat(), produced_kwh=wh_to_kwh(worst["produced_wh"])),
    )


async def _fetch_period_windows(
    client: BridgeClient,
    start_date: str,
    end_date: str,
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> list[dict[str, Any]]:
    windows = await client.list_windows(range_start_utc, range_end_utc)
    if not windows:
        raise ToolError(
            f"enphase-bridge has no energy data between {start_date} and {end_date} (Pacific)"
        )
    return windows


def _period_totals(windows: list[dict[str, Any]]) -> dict[str, float]:
    """Period-wide produced/consumed/imported/exported/net kWh and self-consumption
    percent, rounded once from the raw Wh sums across every window in the range."""
    produced_wh = sum(w["wh_produced"] for w in windows)
    consumed_wh = sum(w["wh_consumed"] for w in windows)
    imported_wh = sum(w["wh_grid_import"] for w in windows)
    exported_wh = sum(w["wh_grid_export"] for w in windows)

    produced_kwh = wh_to_kwh(produced_wh)
    consumed_kwh = wh_to_kwh(consumed_wh)
    self_consumption_pct = (
        round(max(0.0, min(100.0, (produced_wh - exported_wh) / produced_wh * 100)), 2)
        if produced_wh > 0
        else 0.0
    )
    return {
        "produced_kwh": produced_kwh,
        "consumed_kwh": consumed_kwh,
        "imported_kwh": wh_to_kwh(imported_wh),
        "exported_kwh": wh_to_kwh(exported_wh),
        "net_kwh": round(produced_kwh - consumed_kwh, 2),
        "self_consumption_pct": self_consumption_pct,
    }


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
    windows = await _fetch_period_windows(
        client, start_date, end_date, range_start_utc, range_end_utc
    )

    by_day = _group_windows_by_pacific_day(windows)
    day_count = (end - start).days + 1
    all_days = [start + timedelta(days=i) for i in range(day_count)]
    day_stats = [_day_stats(day, by_day.get(day, []), now) for day in all_days]

    daily_breakdown = [_daily_total(stats) for stats in day_stats]
    expected_windows = sum(stats["expected_windows"] for stats in day_stats)
    complete_count = sum(stats["complete_count"] for stats in day_stats)
    data_completeness_pct = (
        round(complete_count / expected_windows * 100, 2) if expected_windows > 0 else 0.0
    )

    # Total only windows that fall on requested days — a misbehaving bridge
    # returning out-of-range windows must not inflate totals while the
    # daily_breakdown (grouped per requested day) shows nothing.
    in_range_windows = [w for day in all_days for w in by_day.get(day, [])]
    totals = _period_totals(in_range_windows)

    finished_days = [s for s in day_stats if s["has_data"] and not s["is_partial"]]
    avg_daily_produced_kwh = _avg_daily_produced_kwh(finished_days)
    best_day, worst_day = _best_worst_days(finished_days)

    return PeriodSummary(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        day_count=day_count,
        produced_kwh=totals["produced_kwh"],
        consumed_kwh=totals["consumed_kwh"],
        imported_kwh=totals["imported_kwh"],
        exported_kwh=totals["exported_kwh"],
        net_kwh=totals["net_kwh"],
        self_consumption_pct=totals["self_consumption_pct"],
        avg_daily_produced_kwh=avg_daily_produced_kwh,
        best_day=best_day,
        worst_day=worst_day,
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
    one. When no day in the range is both finished and has recorded data
    (e.g. the range only covers a still-in-progress "today"), the period
    totals are still returned and `avg_daily_produced_kwh`/`best_day`/
    `worst_day` are null — not available yet, not zero. Raises an error for
    invalid or reversed dates, a range over 92 days, or if the bridge has no
    data anywhere in the range.
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
