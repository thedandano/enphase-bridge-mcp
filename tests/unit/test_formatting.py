from datetime import UTC, datetime, timedelta

import pytest

from enphase_bridge_mcp.formatting import (
    epoch_to_pacific_iso,
    pacific_day_bounds,
    wh_to_kwh,
)


class TestWhToKwh:
    def test_rounds_to_two_decimal_places(self) -> None:
        assert wh_to_kwh(1234.567) == 1.23

    def test_zero(self) -> None:
        assert wh_to_kwh(0) == 0.0

    def test_exact_kwh(self) -> None:
        assert wh_to_kwh(5000) == 5.0


class TestEpochToPacificIso:
    def test_summer_offset_is_pdt(self) -> None:
        # 2026-07-01 12:00:00 UTC -> 2026-07-01 05:00:00-07:00 (PDT)
        ts = int(datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC).timestamp())
        assert epoch_to_pacific_iso(ts) == "2026-07-01T05:00:00-07:00"

    def test_winter_offset_is_pst(self) -> None:
        # 2026-01-01 12:00:00 UTC -> 2026-01-01 04:00:00-08:00 (PST)
        ts = int(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp())
        assert epoch_to_pacific_iso(ts) == "2026-01-01T04:00:00-08:00"


class TestPacificDayBounds:
    def test_explicit_date(self) -> None:
        start, end = pacific_day_bounds("2026-06-15")
        assert start == datetime(2026, 6, 15, 7, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 6, 16, 7, 0, 0, tzinfo=UTC)

    def test_today_with_pinned_clock(self) -> None:
        pinned_now = datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)
        start, end = pacific_day_bounds("today", now=pinned_now)
        assert start == datetime(2026, 6, 15, 7, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 6, 16, 7, 0, 0, tzinfo=UTC)

    def test_today_pinned_near_midnight_uses_pacific_civil_day(self) -> None:
        # 2026-06-16 05:00 UTC is still 2026-06-15 22:00 Pacific (PDT, UTC-7)
        pinned_now = datetime(2026, 6, 16, 5, 0, 0, tzinfo=UTC)
        start, end = pacific_day_bounds("today", now=pinned_now)
        assert start == datetime(2026, 6, 15, 7, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 6, 16, 7, 0, 0, tzinfo=UTC)

    def test_yesterday_with_pinned_clock(self) -> None:
        pinned_now = datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)
        start, end = pacific_day_bounds("yesterday", now=pinned_now)
        assert start == datetime(2026, 6, 14, 7, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 6, 15, 7, 0, 0, tzinfo=UTC)

    def test_spring_forward_day_is_23_hours(self) -> None:
        # 2026-03-08: America/Los_Angeles springs forward at 2am -> 3am.
        start, end = pacific_day_bounds("2026-03-08")
        assert end - start == timedelta(hours=23)

    def test_fall_back_day_is_25_hours(self) -> None:
        # 2026-11-01: America/Los_Angeles falls back at 2am -> 1am.
        start, end = pacific_day_bounds("2026-11-01")
        assert end - start == timedelta(hours=25)

    def test_invalid_date_spec_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid date_spec"):
            pacific_day_bounds("not-a-date")

    def test_invalid_format_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid date_spec"):
            pacific_day_bounds("06/15/2026")
