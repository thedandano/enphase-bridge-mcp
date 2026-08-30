"""MCP server exposing enphase-bridge solar data as three LLM tools.

Stateless streamable-HTTP server (mcp==2.0.0b1): every tool call constructs
its own `Settings`/`BridgeClient`, matching `BridgeClient`'s own
per-call-connection design. No shared mutable state between calls.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from .bridge_client import BridgeClient
from .config import Settings
from .formatting import PACIFIC, epoch_to_pacific_iso, pacific_day_bounds, wh_to_kwh
from .models import CurrentStatus, DailySummary, DayComparison

server: MCPServer = MCPServer(
    name="enphase-bridge-mcp",
    instructions=(
        "Tools for querying a home solar installation via the local "
        "enphase-bridge service. All energy figures are kWh, all power "
        "figures are watts, and all timestamps are America/Los_Angeles "
        "(Pacific) ISO 8601 strings."
    ),
)


def _build_client() -> BridgeClient:
    return BridgeClient(Settings())


def _now() -> datetime:
    """Current instant, resolved through this module's `datetime` global.

    Exists so other modules (e.g. `analysis_tools`) can share one clock that
    tests pin the same way `test_tools.py`'s `pinned_now` fixture already
    does: by monkeypatching `enphase_bridge_mcp.server.datetime`.
    """
    return datetime.now(tz=UTC)


async def _build_daily_summary(client: BridgeClient, date_spec: str, now: datetime) -> DailySummary:
    """Fetch and aggregate one Pacific day's windows into a `DailySummary`.

    Raises:
        ValueError: `date_spec` is not "today", "yesterday", or "YYYY-MM-DD".
        ToolError: the bridge has no windows recorded for that day.
    """
    start_utc, end_utc = pacific_day_bounds(date_spec, now=now)
    windows = await client.list_windows(start_utc, end_utc)
    if not windows:
        raise ToolError(f"enphase-bridge has no energy data for {date_spec} (Pacific)")

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

    # A trailing in-progress window's Wh understates a full 15 minutes, so an
    # incomplete window should never be picked as the peak-power window.
    peak_candidates = [w for w in windows if w["is_complete"]] or windows
    peak_window = max(peak_candidates, key=lambda w: w["wh_produced"])
    peak_production_w = round(peak_window["wh_produced"] * 4, 1)
    peak_production_at = epoch_to_pacific_iso(int(peak_window["window_start"]))

    # Denominator is the number of 15-minute windows expected to exist by now
    # (not len(windows)) — otherwise missing rows are invisible: a day with
    # only 4 windows recorded due to a collector outage would report 100%
    # complete just because all 4 happen to be marked complete.
    expected_windows = max(1, int((min(now, end_utc) - start_utc).total_seconds() // 900))
    complete_count = sum(1 for w in windows if w["is_complete"])
    data_completeness_pct = round(complete_count / expected_windows * 100, 2)

    resolved_date = start_utc.astimezone(PACIFIC).date().isoformat()

    return DailySummary(
        date=resolved_date,
        produced_kwh=produced_kwh,
        consumed_kwh=consumed_kwh,
        imported_kwh=imported_kwh,
        exported_kwh=exported_kwh,
        net_kwh=net_kwh,
        self_consumption_pct=self_consumption_pct,
        peak_production_w=peak_production_w,
        peak_production_at=peak_production_at,
        data_completeness_pct=data_completeness_pct,
    )


def _pct_diff(a: float, b: float) -> float:
    """Percent change of `a` relative to `b`. 0.0 when `b` is zero (documented edge case)."""
    if b == 0:
        return 0.0
    return round((a - b) / abs(b) * 100, 2)


# ponytail: fixed thresholds; make configurable if real CT noise ever exceeds them
_POWER_BALANCE_TOLERANCE_W = 500.0
_NEGATIVE_CONSUMPTION_NOISE_FLOOR_W = -25.0
"""A home can't consume negative power, but a CT can read a few watts below
zero at near-idle. Beyond this floor, negative consumption is a sensor fault
even when the three channels happen to balance within tolerance."""


def _is_power_consistent(consumption_w: float, power_balance_w: float) -> bool:
    return (
        abs(power_balance_w) <= _POWER_BALANCE_TOLERANCE_W
        and consumption_w >= _NEGATIVE_CONSUMPTION_NOISE_FLOOR_W
    )


def _power_balance_w(production_w: float, consumption_w: float, grid_w: float) -> float:
    """Residual of the live power balance: consumption - (production + grid).

    Positive grid_w is drawing, negative is exporting, so the three channels
    should account for each other and leave only CT measurement noise here.
    A large residual means an upstream channel is misreporting (observed in
    the wild: negative consumption_w alongside grid_w=0 while producing).
    """
    return round(consumption_w - (production_w + grid_w), 2)


def _is_bridge_online(window_start: int, now: datetime) -> bool:
    """True if the most recently completed window ended within the last ~20 minutes.

    `/api/energy/windows/latest` returns the most recently *completed* window,
    stamped with its start time — so staleness must be measured from the
    window's end (start + 900s), not its start, or a healthy bridge looks
    offline for most of each 15-minute cycle.
    """
    window_end = window_start + 900
    return (now.timestamp() - window_end) <= 20 * 60


async def _fetch_latest_power_sample(client: BridgeClient, now: datetime) -> dict[str, Any]:
    """Fetch the most recent power sample from the last 5 minutes.

    Raises:
        ToolError: no power samples were recorded in that window.
    """
    now_epoch = int(now.timestamp())
    samples = await client.get_power_samples(now_epoch - 300, now_epoch, limit=50)
    if not samples:
        raise ToolError("enphase-bridge returned no power samples in the last 5 minutes")
    return max(samples, key=lambda s: s["sampled_at"])


async def _fetch_today_running_totals(
    client: BridgeClient, now: datetime
) -> tuple[float, float, float, float]:
    """Fetch today's windows so far and aggregate them into running totals.

    Returns (produced_kwh, consumed_kwh, exported_kwh, data_completeness_pct).
    """
    day_start_utc, _day_end_utc = pacific_day_bounds("today", now=now)
    today_windows = await client.list_windows(day_start_utc, now)
    today_produced_kwh = wh_to_kwh(sum(w["wh_produced"] for w in today_windows))
    today_consumed_kwh = wh_to_kwh(sum(w["wh_consumed"] for w in today_windows))
    today_exported_kwh = wh_to_kwh(sum(w["wh_grid_export"] for w in today_windows))
    expected_today_windows = max(1, int((now - day_start_utc).total_seconds() // 900))
    complete_today_count = sum(1 for w in today_windows if w["is_complete"])
    today_data_completeness_pct = round(complete_today_count / expected_today_windows * 100, 2)
    return (
        today_produced_kwh,
        today_consumed_kwh,
        today_exported_kwh,
        today_data_completeness_pct,
    )


@server.tool()
async def get_current_status() -> CurrentStatus:
    """Get the solar system's live status: current power flow and today's running totals.

    Returns instantaneous production/consumption/grid power in watts (grid_w is
    negative while exporting), whether the bridge is currently online, when it
    last recorded data (Pacific ISO 8601), today's produced/consumed/exported
    energy in kWh accumulated since Pacific midnight, and what share of today's
    expected 15-minute windows so far the bridge has marked complete. Also
    returns a live power-balance check: `power_balance_w` (the residual of
    consumption - production - grid) and `is_power_data_consistent` (False
    when the instantaneous channels contradict each other — the live watts
    should then not be trusted, though today's kWh totals are unaffected).
    Raises an error if the bridge is unreachable or has no recent power samples.
    """
    client = _build_client()
    now = _now()

    health = await client.get_health()
    latest_window = await client.get_latest_window()
    window_start = int(latest_window["window_start"])

    latest_sample = await _fetch_latest_power_sample(client, now)
    (
        today_produced_kwh,
        today_consumed_kwh,
        today_exported_kwh,
        today_data_completeness_pct,
    ) = await _fetch_today_running_totals(client, now)

    production_w = float(latest_sample["production_w"])
    consumption_w = float(latest_sample["consumption_w"])
    grid_w = float(latest_sample["grid_w"])
    power_balance_w = _power_balance_w(production_w, consumption_w, grid_w)

    return CurrentStatus(
        production_w=production_w,
        consumption_w=consumption_w,
        grid_w=grid_w,
        power_balance_w=power_balance_w,
        is_power_data_consistent=_is_power_consistent(consumption_w, power_balance_w),
        is_online=_is_bridge_online(window_start, now),
        last_data_at=epoch_to_pacific_iso(window_start),
        today_produced_kwh=today_produced_kwh,
        today_consumed_kwh=today_consumed_kwh,
        today_exported_kwh=today_exported_kwh,
        today_data_completeness_pct=today_data_completeness_pct,
        uptime_seconds=int(health["uptime_seconds"]),
    )


@server.tool()
async def get_daily_summary(date: str = "today") -> DailySummary:
    """Get aggregated energy totals for one Pacific civil day (midnight to midnight Pacific).

    `date` accepts "today", "yesterday", or an explicit "YYYY-MM-DD" (interpreted
    as a Pacific date). Returns produced/consumed/imported/exported/net kWh,
    self-consumption percentage, peak production (watts, with its Pacific time),
    and what share of that day's 15-minute windows the bridge marked complete.
    Raises an error for an invalid date, or if the bridge has no data for that day.
    """
    client = _build_client()
    try:
        return await _build_daily_summary(client, date, _now())
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
async def compare_days(date_a: str = "today", date_b: str = "yesterday") -> DayComparison:
    """Compare energy totals between two Pacific civil days.

    Each of `date_a`/`date_b` accepts "today", "yesterday", or "YYYY-MM-DD"
    (Pacific dates). Returns the full `DailySummary` for both days, plus
    kWh and percent deltas (day_a minus/relative-to day_b) for produced,
    consumed, and net energy. Percent deltas are 0.0 when day_b's value is
    zero. Raises an error for an invalid date, or if either day has no data.
    """
    client = _build_client()
    now = _now()
    try:
        day_a = await _build_daily_summary(client, date_a, now)
        day_b = await _build_daily_summary(client, date_b, now)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    return DayComparison(
        day_a=day_a,
        day_b=day_b,
        produced_kwh_diff=round(day_a.produced_kwh - day_b.produced_kwh, 2),
        produced_pct_diff=_pct_diff(day_a.produced_kwh, day_b.produced_kwh),
        consumed_kwh_diff=round(day_a.consumed_kwh - day_b.consumed_kwh, 2),
        consumed_pct_diff=_pct_diff(day_a.consumed_kwh, day_b.consumed_kwh),
        net_kwh_diff=round(day_a.net_kwh - day_b.net_kwh, 2),
        net_pct_diff=_pct_diff(day_a.net_kwh, day_b.net_kwh),
    )


# Import-time side effect: registers @server.tool()s defined in analysis_tools/cost_tools.
from . import analysis_tools as _analysis_tools  # noqa: E402,F401
from . import cost_tools as _cost_tools  # noqa: E402,F401


@server.custom_route("/healthz", methods=["GET"])
async def _healthz(_request: Request) -> JSONResponse:
    """Liveness probe for Docker/proxy healthchecks; never calls the bridge.

    Registered via `MCPServer.custom_route` rather than `app.add_route` so the
    route survives into the *fresh* Starlette app that `MCPServer.run()`
    builds internally for the real production server (`run_streamable_http_async`
    calls `streamable_http_app()` again at that point) — not just the
    module-level `app` object below, which only backs the test suite.
    """
    return JSONResponse({"status": "ok"})


app: Starlette = server.streamable_http_app(stateless_http=True)


def _transport_security(settings: Settings) -> TransportSecuritySettings | None:
    """Build explicit transport security settings from `settings.allowed_hosts`.

    Returns `None` when `allowed_hosts` is empty (the default), which leaves
    the SDK's own defaults in place: DNS-rebinding protection auto-enabled
    with a loopback-only Host/Origin allowlist when bound to a loopback host
    (127.0.0.1/localhost/::1), and left disabled otherwise — see
    `mcp.server.lowlevel.server.Server.streamable_http_app`. There is
    deliberately no wildcard fallback here: binding to a non-loopback host
    (e.g. `ENPHASE_MCP_HOST=0.0.0.0` to serve LAN clients) only accepts
    connections from the hosts explicitly listed in `allowed_hosts`.
    """
    if not settings.allowed_hosts:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=[f"http://{host}" for host in settings.allowed_hosts],
    )


def _apply_bridge_flags(settings: Settings, ip: str | None, port: int | None) -> None:
    """Overlay --ip/--port onto the configured bridge URL (flags beat env/.env).

    Preserves the configured scheme (an https bridge must not silently downgrade
    to http — the bearer token would travel in plaintext) and brackets IPv6
    hosts, which are invalid in a URL authority without them.
    """
    if ip is None and port is None:
        return
    current = urlparse(settings.bridge_url)
    scheme = current.scheme or "http"
    host = ip or current.hostname or "localhost"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    effective_port = port or current.port or (443 if scheme == "https" else 8080)
    path = current.path.rstrip("/")  # keep a reverse-proxy prefix like /enphase
    settings.bridge_url = f"{scheme}://{host}:{effective_port}{path}"


def _bridge_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be 1-65535, got {port}")
    return port


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="enphase-bridge-mcp")
    parser.add_argument(
        "--ip",
        help="IP/hostname of the enphase-bridge service "
        "(default: ENPHASE_MCP_BRIDGE_URL or localhost)",
    )
    parser.add_argument(
        "--port",
        type=_bridge_port,
        help="port of the enphase-bridge service (default: from ENPHASE_MCP_BRIDGE_URL or 8080)",
    )
    args = parser.parse_args(argv)

    settings = Settings()
    if args.ip is not None or args.port is not None:
        _apply_bridge_flags(settings, args.ip, args.port)
        # Tools construct a fresh Settings() per call (stateless design), so the
        # flag override must travel via the environment to reach them.
        os.environ["ENPHASE_MCP_BRIDGE_URL"] = settings.bridge_url
    # One startup line stating the effective target, so anyone (or any agent)
    # reading server output can spot a wrong bridge URL instead of debugging
    # silent tool failures.
    print(
        f"enphase-bridge-mcp: bridge target {settings.bridge_url} · "
        f"serving MCP at http://{settings.host}:{settings.port}/mcp",
        file=sys.stderr,
    )
    server.run(
        transport="streamable-http",
        stateless_http=True,
        host=settings.host,
        port=settings.port,
        transport_security=_transport_security(settings),
    )


if __name__ == "__main__":
    main()
