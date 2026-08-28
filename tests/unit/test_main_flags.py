"""--ip/--port flag overlay onto the configured bridge URL."""

from __future__ import annotations

import os
from typing import Any

import pytest

from enphase_bridge_mcp import server as server_module
from enphase_bridge_mcp.config import Settings
from enphase_bridge_mcp.server import _apply_bridge_flags, main


def test_ip_and_port_build_bridge_url() -> None:
    s = Settings(bridge_url="http://localhost:8080")
    _apply_bridge_flags(s, ip="192.168.1.146", port=9090)
    assert s.bridge_url == "http://192.168.1.146:9090"


def test_ip_alone_keeps_configured_port() -> None:
    s = Settings(bridge_url="http://localhost:9999")
    _apply_bridge_flags(s, ip="192.168.1.146", port=None)
    assert s.bridge_url == "http://192.168.1.146:9999"


def test_port_alone_keeps_configured_host() -> None:
    s = Settings(bridge_url="http://bridgebox:8080")
    _apply_bridge_flags(s, ip=None, port=9090)
    assert s.bridge_url == "http://bridgebox:9090"


def test_no_flags_leaves_url_untouched() -> None:
    s = Settings(bridge_url="http://localhost:8080")
    _apply_bridge_flags(s, ip=None, port=None)
    assert s.bridge_url == "http://localhost:8080"


def test_configured_url_without_explicit_port_defaults_8080() -> None:
    s = Settings(bridge_url="http://bridgebox")
    _apply_bridge_flags(s, ip="192.168.1.146", port=None)
    assert s.bridge_url == "http://192.168.1.146:8080"


def test_main_exports_flag_url_for_per_call_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tools build a fresh Settings() per call (stateless design), so main()
    must export the flag-derived URL as ENPHASE_MCP_BRIDGE_URL — mutating its
    own local Settings would silently do nothing."""
    # setenv-then-delenv: registers teardown even when the var was absent,
    # so the value main() exports can't leak into later tests
    monkeypatch.setenv("ENPHASE_MCP_BRIDGE_URL", "http://sentinel")
    monkeypatch.delenv("ENPHASE_MCP_BRIDGE_URL")
    argv = ["--ip", "192.168.1.146"]
    monkeypatch.setattr(server_module.MCPServer, "run", lambda self, **kwargs: None)

    main(argv)

    assert os.environ["ENPHASE_MCP_BRIDGE_URL"] == "http://192.168.1.146:8080"
    assert Settings().bridge_url == "http://192.168.1.146:8080"


def test_main_without_flags_does_not_touch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # setenv-then-delenv: registers teardown even when the var was absent,
    # so the value main() exports can't leak into later tests
    monkeypatch.setenv("ENPHASE_MCP_BRIDGE_URL", "http://sentinel")
    monkeypatch.delenv("ENPHASE_MCP_BRIDGE_URL")
    argv = []
    monkeypatch.setattr(server_module.MCPServer, "run", lambda self, **kwargs: None)

    main(argv)

    assert "ENPHASE_MCP_BRIDGE_URL" not in os.environ


def test_main_run_still_receives_transport_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    # setenv-then-delenv: registers teardown even when the var was absent,
    # so the value main() exports can't leak into later tests
    monkeypatch.setenv("ENPHASE_MCP_BRIDGE_URL", "http://sentinel")
    monkeypatch.delenv("ENPHASE_MCP_BRIDGE_URL")
    argv = ["--ip", "192.168.1.146", "--port", "9090"]
    monkeypatch.setattr(
        server_module.MCPServer,
        "run",
        lambda self, **kwargs: captured.update(kwargs),
    )

    main(argv)

    assert captured["transport"] == "streamable-http"
    assert captured["stateless_http"] is True
    assert os.environ.get("ENPHASE_MCP_BRIDGE_URL") == "http://192.168.1.146:9090"
