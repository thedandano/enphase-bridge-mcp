# enphase-bridge-mcp

An MCP (Model Context Protocol) server that exposes the local [enphase-bridge](https://github.com/thedandano/enphase-bridge)
Rust service — solar production/consumption energy windows and power samples — as tools an LLM can call.

## Run

```sh
uv run enphase-bridge-mcp
```

Serves streamable-HTTP MCP at `http://127.0.0.1:8000/mcp` by default.

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Description |
| --- | --- |
| `ENPHASE_MCP_BRIDGE_URL` | Base URL of the enphase-bridge service (default `http://localhost:8080`). |
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

## Endpoint

- `http://127.0.0.1:8000/mcp` — streamable-HTTP MCP endpoint.

## Warning

This project pins `mcp==2.0.0b1`, a **pre-release** of the MCP Python SDK. Its API may change in
breaking ways on any bump — do not upgrade it without re-verifying import paths and behavior against
the installed source under `.venv/lib/python*/site-packages/mcp/`.
