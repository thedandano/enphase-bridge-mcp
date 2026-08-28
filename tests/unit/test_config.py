import pytest

from enphase_bridge_mcp.config import Settings


class TestSettingsDefaults:
    def test_defaults(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.bridge_url == "http://localhost:8080"
        assert settings.bridge_api_key is None
        assert settings.host == "127.0.0.1"
        assert settings.port == 8000


class TestSettingsEnvOverride:
    def test_bridge_url_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENPHASE_MCP_BRIDGE_URL", "http://enphase-bridge.local:9090")
        settings = Settings(_env_file=None)
        assert settings.bridge_url == "http://enphase-bridge.local:9090"

    def test_bridge_api_key_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENPHASE_MCP_BRIDGE_API_KEY", "secret-key")
        settings = Settings(_env_file=None)
        assert settings.bridge_api_key == "secret-key"

    def test_host_and_port_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENPHASE_MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("ENPHASE_MCP_PORT", "9000")
        settings = Settings(_env_file=None)
        assert settings.host == "0.0.0.0"
        assert settings.port == 9000

    def test_unprefixed_env_var_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIDGE_URL", "http://should-not-apply:1234")
        settings = Settings(_env_file=None)
        assert settings.bridge_url == "http://localhost:8080"
