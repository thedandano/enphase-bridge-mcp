"""Milestone-3 cost/TOU tools: true-up cost estimates and rate-schedule refresh.

Split out of `server.py` for the same reason `analysis_tools.py` was: keeps
that module from growing past a screenful. Registers its `@server.tool()`s on
the same `MCPServer` instance imported from `.server`; `server.py` imports
this module once (for the import-time registration side effect) so `main()`
still sees every tool.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .analysis_tools import _parse_period_date
from .bridge_client import BridgeClient
from .formatting import epoch_to_pacific_iso, pacific_day_bounds
from .models import TouPeriodBreakdown, ToUSchedule, ToUScheduleMeta, TrueUpEstimate
from .server import _build_client, server

_BRIDGE_TRUEUP_END_QUIRK_SECONDS = 24 * 60 * 60
"""`GET /api/trueup/estimate` adds a fixed 24h to the `end` param server-side to
make a UTC calendar-day boundary inclusive (see `energy.rs`'s DAY_SECS
comment). To land on the exact Pacific-day exclusive boundary
`pacific_day_bounds` already computes, we must pre-subtract that same fixed
24h before sending `end` — not a calendar day, since Pacific days can be
23/25h across a DST transition and the bridge's adjustment is a flat 24h.

That flat 24h pre-subtraction has one blind spot: the bridge validates
`end >= start` on these *pre-compensation* wire values, before it applies its
own +24h. On the annual Pacific spring-forward day (a 23h civil day, e.g.
2026-03-08) a same-day request's compensated `end` lands exactly one hour
*before* `start`, so the bridge would reject a legitimate single-day request
with an opaque "end must be after start" 400. `_build_trueup_estimate`
detects that and raises a clear `ToolError` instead of forwarding the request
— see the `end_param_utc < start_utc` check there."""

_MAX_TRUEUP_DAYS = 500
"""`GET /api/trueup/estimate` queries energy windows with a hard limit of
50,000 rows and no pagination (`trueup.rs::get_estimate`). At 96 windows/day
(15-minute windows) that's ~520 days; a longer range would silently drop the
tail of the period from `net_cost_usd` with no error and no signal (even
`excluded_window_count` stays 0, since both the current-formula and
all-formula queries hit the same cap). Capped here with margin below the
bridge's actual limit."""


def _trueup_end_param(end_date_iso: str) -> datetime:
    """UTC `end` instant to send for a Pacific `end_date`, pre-compensated for
    the bridge's fixed +24h inclusivity adjustment (see
    `_BRIDGE_TRUEUP_END_QUIRK_SECONDS`)."""
    _, end_exclusive_utc = pacific_day_bounds(end_date_iso)
    return end_exclusive_utc - timedelta(seconds=_BRIDGE_TRUEUP_END_QUIRK_SECONDS)


def _period_breakdown(raw: dict[str, Any], key: str) -> TouPeriodBreakdown:
    detail = raw["breakdown"][key]
    return TouPeriodBreakdown(
        import_kwh=float(detail["import_kwh"]),
        export_kwh=float(detail["export_kwh"]),
        import_cost_usd=float(detail["import_cost_usd"]),
        export_credit_usd=float(detail["export_credit_usd"]),
    )


async def _build_trueup_estimate(
    client: BridgeClient, start_date: str, end_date: str
) -> TrueUpEstimate:
    """Fetch and map one Pacific date range's true-up estimate.

    Raises:
        ValueError: invalid or reversed dates, a range over `_MAX_TRUEUP_DAYS`
            days, or a single-day request on the Pacific spring-forward date.
        ToolError: no TOU schedule configured, no data in the range, or the
            bridge is unreachable.
    """
    start = _parse_period_date("start_date", start_date)
    end = _parse_period_date("end_date", end_date)
    if end < start:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}")
    day_count = (end - start).days + 1
    if day_count > _MAX_TRUEUP_DAYS:
        raise ValueError(
            f"range too large; max {_MAX_TRUEUP_DAYS} days per call "
            f"(requested {day_count} days) — the bridge caps true-up queries "
            "at 50,000 15-minute windows per request"
        )

    start_utc, _ = pacific_day_bounds(start_date)
    end_param_utc = _trueup_end_param(end_date)
    if end_param_utc < start_utc:
        # Only reachable when start_date == end_date and that date is the
        # ~23h Pacific spring-forward day — see _BRIDGE_TRUEUP_END_QUIRK_SECONDS.
        raise ValueError(
            f"{end_date} is the Pacific DST spring-forward date (a 23-hour "
            "civil day), which this endpoint cannot express as a single-day "
            "range — request a multi-day range that includes it instead"
        )

    raw = await client.get_trueup_estimate(start_utc, end_param_utc)
    schedule = raw["tou_schedule"]

    return TrueUpEstimate(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        net_cost_usd=float(raw["net_cost_usd"]),
        peak=_period_breakdown(raw, "peak"),
        off_peak=_period_breakdown(raw, "off_peak"),
        super_off_peak=_period_breakdown(raw, "super_off_peak"),
        tou_schedule=ToUScheduleMeta(
            id=int(schedule["id"]),
            rate_label=str(schedule["rate_label"]),
            effective_date=schedule["effective_date"],
        ),
        computed_at=epoch_to_pacific_iso(int(raw["computed_at"])),
        excluded_window_count=int(raw["excluded_window_count"]),
    )


@server.tool()
async def get_trueup_estimate(start_date: str, end_date: str) -> TrueUpEstimate:
    """Estimate the true-up bill for a range of Pacific civil days, by TOU period.

    `start_date` and `end_date` are explicit Pacific dates as "YYYY-MM-DD",
    inclusive of both ends, capped at 500 days per call (a full NEM true-up
    year — 12 months — is fine in one call; the bridge computes this
    server-side). Returns net cost in USD (NEGATIVE means the utility owes
    you a credit — see `net_cost_usd`), a per-TOU-period breakdown
    (peak/off_peak/super_off_peak: imported/exported kWh and their
    cost/credit in USD), which rate schedule was used, and how many windows
    in the range were excluded from the estimate because they haven't yet
    been recomputed onto the currently active formula version (see
    `excluded_window_count` — a nonzero count means the estimate is based on
    incomplete/stale data even though it succeeded). Raises an error for
    invalid or reversed dates, a range over 500 days, a single-day request on
    the Pacific DST spring-forward date, if no TOU rate schedule has been
    fetched yet (call `refresh_tou_schedule` first), if the bridge has no
    energy data anywhere in the range, or if the bridge is unreachable.
    """
    client = _build_client()
    try:
        return await _build_trueup_estimate(client, start_date, end_date)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=False
    ),
)
async def refresh_tou_schedule() -> ToUSchedule:
    """Fetch the latest Time-of-Use rate schedule from OpenEI and make it the active one.

    This tool MUTATES upstream state: enphase-bridge persists the newly
    fetched schedule as a new row (it does NOT overwrite the previous one —
    each call appends, and `get_trueup_estimate` always uses the most
    recently fetched row), so repeated calls are not idempotent and a timed-
    out call may still have landed upstream. Call it once before the first
    `get_trueup_estimate` (which otherwise errors with no schedule
    configured), and again whenever utility rates change. Raises an error if
    OpenEI is unreachable or returns a non-2xx response, if its response
    can't be parsed, or if the configured rate label isn't present in it.
    """
    client = _build_client()
    raw = await client.refresh_tou_schedule()
    return ToUSchedule(
        schedule_id=int(raw["schedule_id"]),
        rate_label=str(raw["rate_label"]),
        utility_name=str(raw["utility_name"]),
        effective_date=raw["effective_date"],
        fetched_at=epoch_to_pacific_iso(int(raw["fetched_at"])),
    )
