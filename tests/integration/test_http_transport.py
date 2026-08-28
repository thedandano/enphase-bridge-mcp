"""Transport-level integration tests for the stateless streamable-HTTP MCP server.

Stands up the real Starlette app the same way `server.py` does
(`server.streamable_http_app(stateless_http=True)`) and drives it over the
actual MCP wire protocol, using the MCP Python SDK's `ClientSession` +
`streamable_http_client` transport over `httpx.ASGITransport` (no sockets, no
real bridge). The upstream enphase-bridge is mocked with respx — never hit
over the network.

`ASGITransport` carries the SDK's streamable-HTTP client fine: httpx streams
the ASGI response body, and `streamable_http_client` accepts a pre-built
`httpx.AsyncClient` via its `http_client=` parameter (see
`mcp/client/streamable_http.py`), so no uvicorn/real-socket fallback is needed.

Each test builds its own app via the `mcp_app()` helper below rather than
importing the module-level `server.app` singleton: `StreamableHTTPSessionManager.run()`
(entered through the Starlette lifespan) is single-use per instance — see
`mcp/server/streamable_http_manager.py` — so sharing one app across tests
would make every test but the first raise `RuntimeError`. `mcp_app()` is a
plain async context manager entered directly inside each test body (not a
pytest fixture): the lifespan's anyio `CancelScope` must exit on the same
asyncio Task that entered it, and a pytest-asyncio fixture's teardown runs as
a separate task from the one that ran its setup, which trips that check.
Nesting the `async with` inside the test body instead keeps entry and exit on
one task throughout.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import respx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from enphase_bridge_mcp.server import server as mcp_server

BRIDGE_URL = "http://localhost:8080"
# The app auto-enables DNS-rebinding protection for its default host
# (127.0.0.1), which only allows Host headers matching 127.0.0.1:*/localhost:*
# (see `mcp/server/lowlevel/server.py`), so the in-process client must dial
# through a matching base URL (with an explicit port, to match the ":*"
# pattern) rather than the usual httpx "testserver" stand-in.
MCP_BASE_URL = "http://127.0.0.1:9999"
MCP_URL = f"{MCP_BASE_URL}/mcp"


def make_window(
    window_start: int,
    wh_produced: float,
    wh_consumed: float,
    wh_grid_import: float = 0.0,
    wh_grid_export: float = 0.0,
    is_complete: bool = True,
) -> dict[str, Any]:
    return {
        "window_start": window_start,
        "wh_produced": wh_produced,
        "wh_consumed": wh_consumed,
        "wh_grid_import": wh_grid_import,
        "wh_grid_export": wh_grid_export,
        "is_complete": is_complete,
    }


def windows_page(payload: list[dict[str, Any]]) -> dict[str, Any]:
    return {"windows": payload, "total": len(payload), "limit": 2880, "offset": 0}


def mock_windows(payload: list[dict[str, Any]]) -> None:
    respx.get(f"{BRIDGE_URL}/api/energy/windows").mock(
        return_value=httpx.Response(200, json=windows_page(payload))
    )


@asynccontextmanager
async def mcp_app() -> AsyncIterator[Starlette]:
    """A freshly built stateless streamable-HTTP app, with its ASGI lifespan entered."""
    app = mcp_server.streamable_http_app(stateless_http=True)
    async with app.router.lifespan_context(app):
        yield app


@asynccontextmanager
async def mcp_client_session(app: Starlette) -> AsyncIterator[ClientSession]:
    """Connect a real MCP `ClientSession` to `app` over an in-process ASGI transport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=MCP_BASE_URL
    ) as http_client:
        async with streamable_http_client(MCP_URL, http_client=http_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


# --- tools/list --------------------------------------------------------


async def test_tools_list_shows_all_three_tools_with_structured_schemas() -> None:
    async with mcp_app() as app, mcp_client_session(app) as session:
        result = await session.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == {"get_current_status", "get_daily_summary", "compare_days"}

    with_schema = {tool.name for tool in result.tools if tool.output_schema is not None}
    assert with_schema == names, "every tool should have a structured output schema"

    daily_summary_tool = next(t for t in result.tools if t.name == "get_daily_summary")
    assert daily_summary_tool.output_schema is not None
    schema_properties = daily_summary_tool.output_schema["properties"]
    assert "produced_kwh" in schema_properties
    assert "self_consumption_pct" in schema_properties


# --- tools/call happy path --------------------------------------------------------


@respx.mock
async def test_tools_call_get_daily_summary_returns_correct_numbers() -> None:
    windows = [
        make_window(1781420400, 500.0, 300.0, 0.0, 200.0, is_complete=True),  # 00:00 Pacific
        make_window(1781421300, 600.0, 300.0, 0.0, 300.0, is_complete=True),  # 00:15 Pacific
        make_window(1781422200, 700.0, 300.0, 0.0, 400.0, is_complete=True),  # 00:30 Pacific
        make_window(1781423100, 800.0, 300.0, 0.0, 500.0, is_complete=False),  # 00:45 Pacific
    ]
    mock_windows(windows)

    async with mcp_app() as app, mcp_client_session(app) as session:
        result = await session.call_tool("get_daily_summary", {"date": "2026-06-14"})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["date"] == "2026-06-14"
    assert result.structured_content["produced_kwh"] == 2.6
    assert result.structured_content["consumed_kwh"] == 1.2
    assert result.structured_content["net_kwh"] == 1.4
    assert result.structured_content["self_consumption_pct"] == 46.15
    # Peak is chosen only among complete windows: the 800 Wh window is
    # incomplete (trailing, in-progress), so the 700 Wh complete window wins.
    assert result.structured_content["peak_production_w"] == 2800.0
    # 3 complete windows out of 96 expected for a full past day, not out of
    # the 4 the bridge happened to return.
    assert result.structured_content["data_completeness_pct"] == 3.12


# --- tools/call error path --------------------------------------------------------


@respx.mock
async def test_tools_call_bridge_down_returns_mcp_tool_error_not_empty_result() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(side_effect=httpx.ConnectError("refused"))

    async with mcp_app() as app, mcp_client_session(app) as session:
        result = await session.call_tool("get_current_status", {})

    assert result.is_error is True
    assert result.structured_content is None
    assert len(result.content) > 0, "error result must carry a human-readable message, not be empty"
    text_block = result.content[0]
    assert text_block.type == "text"
    assert "Cannot reach enphase-bridge" in text_block.text
