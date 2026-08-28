# enphase-bridge-mcp

An MCP (Model Context Protocol) server that lets an AI assistant answer questions about your home
solar system — current production, history, comparisons, inverter health, and true-up cost
estimates — by wrapping the local [enphase-bridge](https://github.com/thedandano/enphase-bridge)
Rust service.

Fully **stateless** streamable-HTTP transport (MCP spec 2026-07-28): no sessions, no server-side
state, every tool call self-contained.

**8 tools:** `get_current_status`, `get_daily_summary`, `compare_days`, `get_period_summary`,
`compare_periods`, `get_inverter_health`, `get_trueup_estimate`, `refresh_tou_schedule`.

## Prerequisites

1. [enphase-bridge](https://github.com/thedandano/enphase-bridge) running (default `http://localhost:8080`).
2. [uv](https://docs.astral.sh/uv/) installed.
3. Start this server:

```sh
uv run enphase-bridge-mcp                                  # bridge on this machine (localhost:8080)
uv run enphase-bridge-mcp --ip 192.168.1.146 --port 8080   # bridge on another machine
```

Both flags are optional and point at the **bridge**; they override `ENPHASE_MCP_BRIDGE_URL`
from the environment or `.env`. Serves streamable-HTTP MCP at `http://127.0.0.1:8000/mcp` by
default. The server must be running for tool calls to succeed — installs below work either way;
calls fail with a clear error until it's up.

## Install — Claude Code

Via the plugin marketplace (this repo is its own marketplace):

```
/plugin marketplace add thedandano/enphase-bridge-mcp
/plugin install enphase-bridge@enphase-plugins
```

CLI equivalents: `claude plugin marketplace add thedandano/enphase-bridge-mcp` and
`claude plugin install enphase-bridge@enphase-plugins`.

Manual alternative (no plugin, just the MCP server):

```sh
claude mcp add --transport http enphase http://127.0.0.1:8000/mcp
```

## Install — Codex

Codex consumes the same marketplace format:

```sh
codex plugin marketplace add thedandano/enphase-bridge-mcp
codex plugin add enphase-bridge@enphase-plugins
```

Manual alternative — add to `~/.codex/config.toml`:

```toml
[mcp_servers.enphase]
url = "http://127.0.0.1:8000/mcp"
```

## Try it

- "How's my solar doing today vs yesterday?"
- "What did I produce last week compared to the week before?"
- "Are any of my inverters having problems?"
- "What would my true-up bill look like for the last year?"

## Bundled skills

Installing the plugin also bundles four skills that route natural-language questions to the right
tools and format every answer the same way, every time:

- **solar-checkin** — "How's my solar?" → live status + today vs yesterday, with staleness caveats.
- **solar-report** — "How was last week/month?" → structured period report with best/worst days.
- **solar-savings** — "What's my true-up? How do I save?" → cost/credit breakdown by TOU period + one data-derived tip.
- **solar-troubleshoot** — "Is something wrong?" → ordered diagnosis: data pipeline vs offline inverters vs low production.

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Description |
| --- | --- |
| `ENPHASE_MCP_BRIDGE_URL` | Base URL of the enphase-bridge service (default `http://localhost:8080`). The `--ip`/`--port` flags override this. |
| `ENPHASE_MCP_BRIDGE_API_KEY` | Optional bearer token for the bridge, if it has an API key configured. |
| `ENPHASE_MCP_HOST` | Host this MCP server binds to (default `127.0.0.1`). |
| `ENPHASE_MCP_PORT` | Port this MCP server binds to (default `8000`). |
| `ENPHASE_MCP_ALLOWED_HOSTS` | Comma-separated extra `Host` header values to accept (e.g. `192.168.1.50:8000,mydomain.local:8000`), for when `ENPHASE_MCP_HOST` is bound to a non-loopback address so LAN clients can reach it. Empty by default. |

### Binding beyond loopback

The MCP SDK auto-restricts incoming requests to loopback `Host`/`Origin` headers only when
`ENPHASE_MCP_HOST` is `127.0.0.1`, `localhost`, or `::1`. If you set `ENPHASE_MCP_HOST=0.0.0.0` (or
another non-loopback address) to serve LAN clients, also set `ENPHASE_MCP_ALLOWED_HOSTS` to the exact
`Host` header value(s) those clients will send — there is no wildcard fallback, only the hosts you list
are accepted.

## Warning

This project pins `mcp==2.0.0b1`, a **pre-release** of the MCP Python SDK. Its API may change in
breaking ways on any bump — do not upgrade it without re-verifying import paths and behavior against
the installed source under `.venv/lib/python*/site-packages/mcp/`.
