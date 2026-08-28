"""Unit tests for `server._transport_security` and its wiring into `main()`.

`_transport_security` is the pure function that turns `Settings.allowed_hosts`
into an SDK `TransportSecuritySettings` object (or `None`, to fall through to
the SDK's own defaults) — see `server.py` for the full rationale. These tests
exercise that function directly, plus a cheap assertion that `main()` actually
passes its result to `MCPServer.run(transport_security=...)`.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.transport_security import TransportSecuritySettings

from enphase_bridge_mcp import server as server_module
from enphase_bridge_mcp.config import Settings
from enphase_bridge_mcp.server import _transport_security, main


class TestTransportSecurity:
    def test_no_allowed_hosts_returns_none(self) -> None:
        """Empty `allowed_hosts` (the default) must return `None`, not a settings
        object with an empty allowlist — `None` lets the SDK apply its own
        defaults (loopback-only, or unrestricted for a non-loopback host);
        an empty-but-non-None `TransportSecuritySettings` would instead lock
        every Host header out."""
        settings = Settings(_env_file=None, allowed_hosts=[])
        assert _transport_security(settings) is None

    def test_allowed_hosts_builds_matching_hosts_and_origins(self) -> None:
        settings = Settings(
            _env_file=None, allowed_hosts=["192.168.1.50:8000", "mydomain.local:8000"]
        )
        result = _transport_security(settings)

        assert isinstance(result, TransportSecuritySettings)
        assert result.enable_dns_rebinding_protection is True
        assert result.allowed_hosts == ["192.168.1.50:8000", "mydomain.local:8000"]
        assert result.allowed_origins == [
            "http://192.168.1.50:8000",
            "http://mydomain.local:8000",
        ]

    def test_no_wildcard_fallback(self) -> None:
        """Configuring specific hosts must never grant a wildcard: only the
        exact hosts listed appear in the allowlist."""
        settings = Settings(_env_file=None, allowed_hosts=["192.168.1.50:8000"])
        result = _transport_security(settings)

        assert result is not None
        assert "*" not in result.allowed_hosts
        assert all(not host.endswith(":*") for host in result.allowed_hosts)


class TestMainPassesTransportSecurity:
    def test_main_passes_transport_security_to_server_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`main()` must forward the constructed transport security settings into
        `MCPServer.run(...)`, not just build them and drop them."""
        monkeypatch.setenv("ENPHASE_MCP_ALLOWED_HOSTS", "192.168.1.50:8000")
        monkeypatch.setenv("ENPHASE_MCP_HOST", "0.0.0.0")

        captured: dict[str, Any] = {}

        def fake_run(self: Any, transport: str, **kwargs: Any) -> None:
            captured["transport"] = transport
            captured.update(kwargs)

        monkeypatch.setattr(server_module.MCPServer, "run", fake_run)

        main([])

        assert captured["transport"] == "streamable-http"
        assert captured["host"] == "0.0.0.0"
        transport_security = captured["transport_security"]
        assert isinstance(transport_security, TransportSecuritySettings)
        assert transport_security.allowed_hosts == ["192.168.1.50:8000"]

    def test_main_passes_none_when_allowed_hosts_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENPHASE_MCP_ALLOWED_HOSTS", raising=False)

        captured: dict[str, Any] = {}

        def fake_run(self: Any, transport: str, **kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(server_module.MCPServer, "run", fake_run)

        main([])

        assert captured["transport_security"] is None
