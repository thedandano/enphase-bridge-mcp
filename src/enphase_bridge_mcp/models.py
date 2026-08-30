"""Pydantic response models for every MCP tool, consolidated in one module.

All models share the `ApiModel` base, which turns their attribute docstrings
into JSON-schema `description`s (via `use_attribute_docstrings`) — so every
tool's `outputSchema` carries human-readable field documentation over the
wire, not just bare types. `server.py`/`analysis_tools.py`/`cost_tools.py`
each re-import the models they use from here (for backward-compatible import
paths) rather than defining their own.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for every response model. A docstring placed right below a field
    becomes that field's `description` in the generated JSON schema — see
    `use_attribute_docstrings` — which is what makes them show up in each
    tool's `outputSchema` for the calling LLM to read."""

    model_config = ConfigDict(use_attribute_docstrings=True)


# --- server.py models --------------------------------------------------------


class CurrentStatus(ApiModel):
    """Live snapshot of the solar system plus today's running totals."""

    production_w: float
    """Instantaneous solar production, in watts."""
    consumption_w: float
    """Instantaneous site consumption, in watts."""
    grid_w: float
    """Instantaneous grid flow, in watts. Negative means exporting to the grid."""
    is_online: bool
    """True if the bridge has recorded a completed window within the last ~20 minutes."""
    last_data_at: str
    """Pacific ISO 8601 timestamp of the most recent completed energy window."""
    today_produced_kwh: float
    """Energy produced so far today (since Pacific midnight), in kWh."""
    today_consumed_kwh: float
    """Energy consumed so far today (since Pacific midnight), in kWh."""
    today_exported_kwh: float
    """Energy exported to the grid so far today (since Pacific midnight), in kWh."""
    today_data_completeness_pct: float
    """Share of today's expected 15-minute windows (so far) marked complete by the bridge, 0-100.

    A value below 100 means the running totals above are based on partial or
    missing data (collector gap, restart, etc.) rather than a full record of
    the day so far.
    """
    uptime_seconds: int
    """Seconds since the enphase-bridge process started."""


class DailySummary(ApiModel):
    """Aggregated energy totals for one Pacific civil day."""

    date: str
    """The Pacific civil date this summary covers, as YYYY-MM-DD."""
    produced_kwh: float
    consumed_kwh: float
    imported_kwh: float
    exported_kwh: float
    net_kwh: float
    """produced_kwh - consumed_kwh: positive means the site generated a surplus that day."""
    self_consumption_pct: float
    """Share of produced energy consumed on-site rather than exported, 0-100."""
    peak_production_w: float
    """Highest average production across any 15-minute window that day, in watts."""
    peak_production_at: str
    """Pacific ISO 8601 start time of the peak-production window."""
    data_completeness_pct: float
    """Share of that day's 15-minute windows marked complete by the bridge, 0-100."""


class DayComparison(ApiModel):
    """Two daily summaries plus the deltas between them (day_a minus day_b)."""

    day_a: DailySummary
    day_b: DailySummary
    produced_kwh_diff: float
    produced_pct_diff: float
    """Percent change in produced_kwh, day_a vs day_b. 0.0 if day_b's value is zero."""
    consumed_kwh_diff: float
    consumed_pct_diff: float
    """Percent change in consumed_kwh, day_a vs day_b. 0.0 if day_b's value is zero."""
    net_kwh_diff: float
    net_pct_diff: float
    """Percent change in net_kwh, day_a vs day_b. 0.0 if day_b's value is zero."""


# --- analysis_tools.py models --------------------------------------------------------


class DayProduced(ApiModel):
    """One day's production, used for `PeriodSummary.best_day`/`worst_day`."""

    date: str
    """Pacific civil date, as YYYY-MM-DD."""
    produced_kwh: float


class DailyTotal(ApiModel):
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


class PeriodSummary(ApiModel):
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
    avg_daily_produced_kwh: float | None
    """Sum of produced_kwh over finished days that have data (`DailyTotal.has_data`
    and not `DailyTotal.is_partial`), divided by the count of those same
    days — not the raw calendar `day_count`, and not this period's
    `produced_kwh` total (which DOES include a still-in-progress "today", if
    the range has one). Days the bridge has no data for (collector gap, or a
    day not reached yet) and any still-in-progress "today" are excluded from
    both the numerator and the denominator, so a partial day's so-far
    production never drags this figure up or down. None when the range has
    no finished day with data (e.g. it only covers a still-in-progress
    "today") — not available yet, not zero."""
    best_day: DayProduced | None
    """The highest-production day in the range, considering only finished days
    that have recorded data (excludes gaps and any still-in-progress "today").
    None when the range has no such day."""
    worst_day: DayProduced | None
    """The lowest-production day in the range, considering only finished days
    that have recorded data (excludes gaps and any still-in-progress "today").
    None when the range has no such day."""
    daily_breakdown: list[DailyTotal]
    """One entry per calendar day in the range, oldest first. A day with no
    windows recorded by the bridge appears with all totals at 0.0 and
    `has_data=False` — see `DailyTotal`."""
    data_completeness_pct: float
    """Share of the period's expected 15-minute windows marked complete by the bridge, 0-100."""


class PeriodComparison(ApiModel):
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


class InverterArraySummary(ApiModel):
    """Health of one configured inverter array."""

    name: str
    total_watts: float
    """Sum of this array's inverters' output as of `InverterHealth.data_as_of`, in
    watts. This is a snapshot, not necessarily current output right now — see
    `InverterHealth.is_stale`."""
    online_count: int
    total_count: int


class OfflineInverter(ApiModel):
    """One inverter the bridge currently reports offline."""

    serial: str
    array: str
    watts_output: float
    """Last-known output, in watts. 0.0 if the bridge has never seen this inverter report."""
    last_report_at: str | None
    """Pacific ISO 8601 timestamp this inverter last reported data, or None if
    the bridge has never seen this inverter report at all."""


class InverterHealth(ApiModel):
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


# --- cost_tools.py models --------------------------------------------------------


class TouPeriodBreakdown(ApiModel):
    """Import/export energy and cost/credit for one TOU period within an estimate."""

    import_kwh: float
    export_kwh: float
    import_cost_usd: float
    export_credit_usd: float


class ToUScheduleMeta(ApiModel):
    """Identifies which rate schedule a `TrueUpEstimate` was computed against."""

    id: int
    rate_label: str
    effective_date: str | None
    """The schedule's effective date as reported by OpenEI (YYYY-MM-DD), or None
    if OpenEI didn't report one for this rate."""


class TrueUpEstimate(ApiModel):
    """Estimated true-up cost for a range of Pacific civil days, by TOU period."""

    start_date: str
    end_date: str
    net_cost_usd: float
    """Net true-up cost in USD for the period: total import cost minus total
    export credit, summed across all TOU periods. NEGATIVE means the utility
    owes *you* a credit (export credits exceeded import costs) — a negative
    value is a good outcome, not an error."""
    peak: TouPeriodBreakdown
    off_peak: TouPeriodBreakdown
    super_off_peak: TouPeriodBreakdown
    tou_schedule: ToUScheduleMeta
    """The rate schedule this estimate was computed against. If it looks stale,
    call `refresh_tou_schedule` and re-request the estimate."""
    computed_at: str
    """Pacific ISO 8601 timestamp the bridge computed this estimate at (now, not
    a bound of the period)."""
    excluded_window_count: int
    """Number of energy windows inside the requested period that were excluded
    from this estimate because they are still on an older (or unversioned)
    formula version and have not yet been recomputed onto the one currently
    active. Nonzero means this estimate is based on incomplete/stale data for
    the period even though a result was returned — surfaced here rather than
    hidden."""


class ToUSchedule(ApiModel):
    """A freshly fetched Time-of-Use rate schedule, now the bridge's active one."""

    schedule_id: int
    rate_label: str
    utility_name: str
    effective_date: str | None
    """The schedule's effective date as reported by OpenEI (YYYY-MM-DD), or None
    if OpenEI didn't report one for this rate."""
    fetched_at: str
    """Pacific ISO 8601 timestamp this schedule was fetched from OpenEI."""
