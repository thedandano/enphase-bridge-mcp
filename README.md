# enphase-bridge-mcp

## What this does

Ask your AI assistant about your home solar system in plain English, and get real answers from
your own data:

> **You:** how's my solar today?
> **Assistant:** ☀️ Right now: 2,850 W producing · 1,900 W using · sending 950 W to the grid
> 📊 Today so far: 15.7 kWh produced · 21.3 kWh used

This is an MCP (Model Context Protocol) server: it exposes your home solar data as **8 tools** any
MCP client (Claude Code, Codex, etc.) can call — live status, daily summaries, day and period
comparisons, inverter health, and true-up cost estimates:

`get_current_status` · `get_daily_summary` · `compare_days` · `get_period_summary` ·
`compare_periods` · `get_inverter_health` · `get_trueup_estimate` · `refresh_tou_schedule`

It also bundles four skills that route casual questions ("how's my solar?", "is something
wrong?", "what's my true-up?") to the right tools — see [Bundled skills](#bundled-skills).

## Install — Claude Code

Via the plugin marketplace (this repo is its own marketplace):

```
/plugin marketplace add thedandano/enphase-bridge-mcp
/plugin install enphase-bridge@enphase-plugins
```

CLI equivalents: `claude plugin marketplace add thedandano/enphase-bridge-mcp` and
`claude plugin install enphase-bridge@enphase-plugins`.

Then tell it where your MCP server is, by adding an `env` block to
`~/.claude/settings.json` (merge into the existing top-level object):

```json
{
  "env": { "ENPHASE_MCP_URL": "http://127.0.0.1:8000/mcp" }
}
```

Use `http://<your-mcp-host>/mcp` instead if you run the server on a homelab.
Restart Claude Code afterwards. The plugin's bundled server reads this variable,
so **there is nothing else to register** — see [Pointing the plugin at your
server](#pointing-the-plugin-at-your-server).

Manual alternative — **instead of** the plugin, not in addition to it (running
both registers the same tools twice):

```sh
claude mcp add --transport http enphase http://127.0.0.1:8000/mcp
```

## Install — Codex

**Codex does not expand `${VAR}` in MCP configs**, so it cannot use the
plugin's bundled server entry. Register the server directly in
`~/.codex/config.toml`:

```toml
[mcp_servers.enphase]
url = "http://127.0.0.1:8000/mcp"
```

Swap in `http://<your-mcp-host>/mcp` if the server runs on a homelab.

Codex does consume the same marketplace format, so you *can* install the
plugin there for its skills:

```sh
codex plugin marketplace add thedandano/enphase-bridge-mcp
codex plugin add enphase-bridge@enphase-plugins
```

But be aware of the trade-off: Codex has no way to disable an individual
plugin-provided server, so the plugin's bundled entry will sit there
permanently failed alongside your working `config.toml` one. If a clean
single-server list matters more to you than the bundled skills, register the
server in `config.toml` and skip the plugin in Codex.

## Dependencies & running the server

1. **[enphase-bridge](https://github.com/thedandano/enphase-bridge)** — the local Rust service
   that collects data from your Enphase system. This server is a thin wrapper around it and
   cannot answer anything without it (default `http://localhost:8080`).
2. **[uv](https://docs.astral.sh/uv/)** — the Python package/run tool used to start the server.

Start the server:

```sh
uv run enphase-bridge-mcp                                  # bridge on this machine (localhost:8080)
uv run enphase-bridge-mcp --ip 192.168.1.146 --port 8080   # bridge on another machine
```

Both flags are optional and point at the **bridge**; they override `ENPHASE_MCP_BRIDGE_URL`
from the environment or `.env`. Serves streamable-HTTP MCP at `http://127.0.0.1:8000/mcp` by
default. The server must be running for tool calls to succeed — the installs above work either
way; calls fail with a clear error until it's up.

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

Design note: the transport is fully **stateless** streamable-HTTP (MCP spec 2026-07-28) — no
sessions, no server-side state, every tool call self-contained.

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

## Deploy in your homelab (Docker)

The server is stateless — run it as a container near your enphase-bridge and
point every MCP client at one URL. Nothing runs on your laptop.

Append this service to your existing `docker-compose.yml`:

```yaml
  enphase-mcp:
    image: ghcr.io/thedandano/enphase-bridge-mcp:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      # Where the enphase-bridge REST API lives (via the reverse proxy).
      ENPHASE_MCP_BRIDGE_URL: http://<bridge-host>
      # Host headers the MCP transport accepts (DNS-rebinding protection).
      # Must list every name clients use to reach this container.
      ENPHASE_MCP_ALLOWED_HOSTS: <mcp-host>,<mcp-host>:80
    # If your reverse proxy runs in Docker, delete `ports`, join the proxy's
    # network, and point the proxy at enphase-mcp:8000 instead.
```

```bash
docker compose up -d enphase-mcp
curl -fs http://localhost:8000/healthz   # {"status":"ok"}
```

Then add a reverse-proxy entry (e.g. `<mcp-host>` → `<host>:8000`) and
keep `ENPHASE_MCP_ALLOWED_HOSTS` in the compose file in sync with the
hostname the proxy serves.

| Env var | Default | Meaning |
| --- | --- | --- |
| `ENPHASE_MCP_BRIDGE_URL` | `http://localhost:8080` | Where the enphase-bridge REST API lives |
| `ENPHASE_MCP_BRIDGE_API_KEY` | unset | Bearer token, if your bridge requires one |
| `ENPHASE_MCP_HOST` | `0.0.0.0` (in the image) | Interface the MCP server binds |
| `ENPHASE_MCP_PORT` | `8000` | Port the MCP server binds |
| `ENPHASE_MCP_ALLOWED_HOSTS` | empty | Comma-separated Host headers to accept (required when clients aren't loopback) |

### Pointing the plugin at your server

The plugin's server URL is **not hardcoded** — it reads `ENPHASE_MCP_URL`, so
the same plugin works whether your server runs on your laptop or a homelab.

**Claude Code** — set it once in `~/.claude/settings.json` and restart:

```json
{
  "env": { "ENPHASE_MCP_URL": "http://<mcp-host>/mcp" }
}
```

Use `http://127.0.0.1:8000/mcp` if the server runs on the same machine. Do
**not** also run `claude mcp add` — the plugin already provides the server, and
a second registration shows the same tools twice, one of them usually broken.

There is deliberately no default. An unset variable makes Claude Code report a
`Missing environment variables` error against the server, which is visible and
actionable; a silent fallback to `127.0.0.1` would instead look connected while
talking to the wrong machine, or fail with no explanation of why.

**Codex** cannot expand `${VAR}` in MCP configs at all, so the plugin's bundled
entry is unusable there — set the URL literally in `~/.codex/config.toml`
instead, and see [Install — Codex](#install--codex) for the trade-off if you
also want the plugin's skills.

```toml
[mcp_servers.enphase]
url = "http://<mcp-host>/mcp"
```

## Warning

This project pins `mcp==2.0.0b1`, a **pre-release** of the MCP Python SDK. Its API may change in
breaking ways on any bump — do not upgrade it without re-verifying import paths and behavior against
the installed source under `.venv/lib/python*/site-packages/mcp/`.
