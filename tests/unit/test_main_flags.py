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


def test_https_scheme_is_preserved() -> None:
    s = Settings(bridge_url="https://bridge.example:8443")
    _apply_bridge_flags(s, ip=None, port=9443)
    assert s.bridge_url == "https://bridge.example:9443"


def test_https_without_port_defaults_443() -> None:
    s = Settings(bridge_url="https://bridge.example")
    _apply_bridge_flags(s, ip="bridge2.example", port=None)
    assert s.bridge_url == "https://bridge2.example:443"


def test_ipv6_flag_gets_bracketed() -> None:
    s = Settings(bridge_url="http://localhost:8080")
    _apply_bridge_flags(s, ip="::1", port=None)
    assert s.bridge_url == "http://[::1]:8080"


def test_ipv6_in_existing_url_stays_bracketed() -> None:
    s = Settings(bridge_url="http://[::1]:8080")
    _apply_bridge_flags(s, ip=None, port=9090)
    assert s.bridge_url == "http://[::1]:9090"


def test_path_prefix_is_preserved() -> None:
    s = Settings(bridge_url="https://proxy.example/enphase")
    _apply_bridge_flags(s, ip=None, port=9443)
    assert s.bridge_url == "https://proxy.example:9443/enphase"


def test_no_path_adds_no_trailing_slash() -> None:
    s = Settings(bridge_url="http://localhost:8080/")
    _apply_bridge_flags(s, ip="192.168.1.146", port=None)
    assert s.bridge_url == "http://192.168.1.146:8080"


@pytest.mark.parametrize("bad_port", ["0", "-1", "65536"])
def test_out_of_range_port_is_a_cli_error(bad_port: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module.MCPServer, "run", lambda self, **kwargs: None)
    with pytest.raises(SystemExit) as exc_info:
        main(["--port", bad_port])
    assert exc_info.value.code == 2  # argparse usage error, not a crash later


def test_main_logs_effective_bridge_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Startup must state the effective bridge URL on stderr so an agent (or
    human) reading server output can see the target and prompt the user when
    it's wrong — silent misconfiguration was the original failure mode."""
    monkeypatch.setenv("ENPHASE_MCP_BRIDGE_URL", "http://sentinel")
    monkeypatch.delenv("ENPHASE_MCP_BRIDGE_URL")
    monkeypatch.setattr(server_module.MCPServer, "run", lambda self, **kwargs: None)

    main(["--ip", "192.168.1.146"])

    err = capsys.readouterr().err
    assert "http://192.168.1.146:8080" in err
    assert "/mcp" in err


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
