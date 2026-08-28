"""behave environment hooks: mock the bridge over HTTP, pin the server's clock.

Every scenario gets its own respx router (never hits the real enphase-bridge)
and its own frozen `datetime.now()` inside `enphase_bridge_mcp.server`, so
Given steps that build "today"/"yesterday" fixture windows and When steps
that call the tool coroutines agree on what "today" means.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import respx

import enphase_bridge_mcp.server as server_module

BRIDGE_URL = "http://localhost:8080"


def _windows_handler(context: Any) -> Any:
    """Route `/api/energy/windows` to whichever fixture list matches the request's `start`."""

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params.get("start")
        windows = context.day_windows_by_start.get(start, [])
        return httpx.Response(
            200, json={"windows": windows, "total": len(windows), "limit": 2880, "offset": 0}
        )

    return handler


class _FixedDateTime(datetime):
    """Stand-in for `server.py`'s `datetime` with `now()` frozen to `context.fixed_now`.

    Reads `context.fixed_now` at call time (not at patch time), since the
    Background step that sets it runs after this class is installed.
    """

    _context: Any = None

    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # noqa: ANN401
        fixed_now: datetime = cls._context.fixed_now
        return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)


def before_scenario(context: Any, scenario: Any) -> None:
    context.day_windows_by_start = {}
    context.fixed_now = None  # set by the "today is ... (Pacific)" step
    context.result = None

    context.respx_mock = respx.mock(assert_all_called=False)
    context.respx_mock.start()
    context.respx_mock.get(f"{BRIDGE_URL}/api/energy/windows").mock(
        side_effect=_windows_handler(context)
    )

    fixed_datetime = type("_ScenarioFixedDateTime", (_FixedDateTime,), {"_context": context})
    context._original_server_datetime = server_module.datetime
    server_module.datetime = fixed_datetime  # type: ignore[misc]


def after_scenario(context: Any, scenario: Any) -> None:
    server_module.datetime = context._original_server_datetime
    context.respx_mock.stop()
