"""Guard the plugin's bundled MCP server declaration.

`.mcp.json` ships inside the plugin, so whatever it contains is what every
installed copy connects to — and a plugin update overwrites the user's cached
copy from this repo. That makes this one file unusually easy to break for
everybody at once.

It has already been broken once. The URL started as a `${ENPHASE_MCP_URL}`
placeholder, was flattened to a literal `http://127.0.0.1:8000/mcp` in PR #8
(commit 34c8496), and shipped that way through 0.1.0, 1.0.0 and 1.1.2. The
justification was that Codex does not expand `${VAR}` — true of Codex, but it
made the plugin unusable for anyone whose MCP server is not on their own
laptop. Those users had to register a second server by hand, so every session
showed a permanently-failing duplicate that came back on each update.

These tests fail loudly if the placeholder is ever flattened again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MCP_CONFIG_PATH = Path(__file__).resolve().parents[2] / ".mcp.json"

# Deliberately no `:-default` fallback. An unset variable makes Claude Code
# report a `env_missing` configError against the server, which is a visible
# failure the user can act on. A localhost default would instead connect
# silently to a machine that may not be theirs.
EXPECTED_URL = "${ENPHASE_MCP_URL}"


def _load_config() -> dict[str, Any]:
    return json.loads(MCP_CONFIG_PATH.read_text())


def test_mcp_config_declares_exactly_one_server_named_enphase() -> None:
    """A second server name would show up as a duplicate in every client."""
    servers = _load_config()["mcpServers"]

    assert list(servers) == ["enphase"], (
        f"expected exactly one server named 'enphase', got {list(servers)}"
    )


def test_mcp_url_is_the_env_placeholder_not_a_literal() -> None:
    """The regression that shipped in PR #8 — a hardcoded URL here is wrong for
    every user who does not run the server on the same machine as their client.
    """
    url = _load_config()["mcpServers"]["enphase"]["url"]

    assert url == EXPECTED_URL, (
        f"expected {EXPECTED_URL!r}, got {url!r}. Do not flatten this to a "
        "literal URL: it ships to every installed copy and breaks anyone whose "
        "server is not on localhost. Users set ENPHASE_MCP_URL instead."
    )


def test_mcp_url_hardcodes_no_host() -> None:
    """Catches a literal even if someone changes the expected placeholder."""
    url = _load_config()["mcpServers"]["enphase"]["url"]

    assert "://" not in url, f"URL must be a bare env placeholder, got {url!r}"


def test_mcp_transport_is_http() -> None:
    servers = _load_config()["mcpServers"]

    assert servers["enphase"]["type"] == "http"
