# Docker Homelab Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship enphase-bridge-mcp as a Docker container that lives in the homelab behind the existing reverse proxy, so MCP clients call a stable URL (`http://enphase-mcp.home/mcp`) instead of a shell on the laptop.

**Architecture:** Multi-stage uv Docker build → GHCR image published by a CI-gated CD workflow (mirrors the enphase-bridge repo's pattern) → a service block appended to Dan's existing homelab compose file (README carries the snippet; no compose file in this repo) → reverse proxy entry `enphase-mcp.home` → the marketplace plugin's `.mcp.json` reads the URL from `ENPHASE_MCP_URL` (neutral localhost default — no private hostname in the public repo). The server code itself barely changes: one `/healthz` route for the Docker healthcheck.

**Tech Stack:** Python 3.14, uv, mcp==2.0.0b1 (stateless streamable HTTP), Docker buildx (amd64+arm64), GitHub Actions → GHCR.

**Spec:** This plan is the spec — requirements came from conversation: "proper stateless MCP … docker container that lives in my homelab … the client calls the waiter in my homelab."

## Global Constraints

- Python `>=3.14`, package manager `uv`; `mcp[cli]==2.0.0b1` (prerelease; already pinned in `uv.lock`, so `uv sync --frozen` needs no `--prerelease` flag).
- All GitHub Actions pinned to full commit SHAs with a `# vN` comment (repo convention — see `.github/workflows/ci.yml`).
- Conventional commits (release-please parses them). Never add `"release-as"` to `release-please-config.json`.
- Feature branch off `dev`, PR into `dev`. No pushes to `main` except via PR.
- CI gates stay intact: ruff, mypy, bandit, pip-audit, pytest ≥80% coverage, behave. No bypassing.
- Do NOT edit `.claude-plugin/plugin.json` / `marketplace.json` versions by hand — release-please owns them.
- Homelab facts: bridge is reachable at `http://enphase-api.home` (proxy, port 80). The proxy admin UI is manual — Dan adds proxy hosts himself.

## Design References — Google's stateless MCP guidance

Source: [Scaling AI agent infrastructure with the MCP stateless updates](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/) (Google Developers Blog). How each plan decision traces back to it:

| Plan decision | Article guidance |
| --- | --- |
| Server runs as a container the client reaches by URL — not a process launched on the client machine (Tasks 3, 6) | The deployment model is server-side infrastructure ("run MCP servers as serverless functions on platforms like Google Cloud Run"); clients connect over HTTP, nothing runs where the client lives. A single homelab container is the one-node version of this. |
| `stateless_http=True`, fresh `Settings`/`BridgeClient` per tool call — no in-memory session (already shipped; unchanged here) | The spec "removes transport-level session management entirely"; production servers (e.g. GitHub MCP Server) "completely removed Redis session storage." |
| Spec / SDK: MCP `2026-07-28` via `mcp==2.0.0b1` (Global Constraints) | Deploy against the "2026-07-28 Model Context Protocol specification release candidate." |
| Any replica can serve any request → `restart: unless-stopped`, no volumes, no sticky anything (Task 5 compose snippet) | "Any container instance can handle any incoming request, you can throw your … MCP servers behind a plain round-robin load balancer" — no session affinity rules. |
| `/healthz` liveness route + Docker `HEALTHCHECK` (Tasks 2–3) | Statelessness makes "pod restarts, rollouts, and autoscaling events … completely invisible to the client" — but only if the platform can detect a dead instance and restart/replace it; a health probe is what makes that automatic. |
| Plain reverse proxy (`enphase-mcp.home`) in front, no MCP-aware gateway needed (Task 6) | Standard `Mcp-*` headers let proxies route "without inspecting the request body" — an ordinary HTTP proxy is enough. |

Deliberately simplified for a homelab: one replica instead of an autoscaled fleet, and no scale-to-zero — the article's economics (idle cost, load-balancing tax) don't bite at N=1. The design still permits both: nothing in the container prevents running two replicas behind the same proxy tomorrow.

## File Structure

- Create: `Dockerfile` — multi-stage uv build, non-root, healthcheck.
- Create: `.dockerignore` — keep image context tiny.
- Create: `.github/workflows/cd.yml` — CI-gated GHCR publish (multi-arch).
- Modify: `.github/workflows/ci.yml` — add `v*` tag trigger so tag pushes run CI (CD is gated on CI success).
- Modify: `src/enphase_bridge_mcp/server.py` — add `/healthz` route.
- Modify: `.mcp.json` — plugin points at the homelab URL (env-overridable).
- Modify: `.gitignore` — fold in the pending `.claude/settings.local.json` line, add `.serena/`.
- Modify: `README.md` — homelab deployment section.
- Test: `tests/unit/test_healthz.py`.

---

### Task 1: Sync branches, cut the feature branch

**Why:** Housekeeping, not architecture — `dev` and `main` diverge on every squash-merge, and building on a stale `dev` reproduces the stacked-PR conflicts from milestones 1–3. No article reference; this is repo hygiene.

**Files:** none created — git only.

**Interfaces:**
- Produces: branch `feat/docker-homelab` based on a `dev` that contains everything on `main` (v1.0.0 release commits).

- [ ] **Step 1: Update local main and merge main into dev (merge, NOT fast-forward — histories diverge on every squash)**

```bash
git stash push -m "pending gitignore lines" -- .gitignore   # carry the uncommitted edit
git checkout main && git pull
git checkout dev && git pull
git merge main -m "chore: sync dev with main (v1.0.0 release)"
```

- [ ] **Step 2: Resolve conflicts, if any, in favor of main's release bumps**

Expected conflict files: `pyproject.toml` (version), `.release-please-manifest.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `uv.lock`, `CHANGELOG.md`. For each: take main's side (`git checkout --theirs <file>` works when merging main INTO dev only if conflicts markers say so — verify by eye; the winning content is version `1.0.0` everywhere). Then:

```bash
uv lock --check || uv lock   # only if uv.lock conflicted
git add -A && git commit --no-edit
git push origin dev
```

- [ ] **Step 3: Cut the feature branch and restore the pending .gitignore edit**

```bash
git checkout -b feat/docker-homelab
git stash pop
```

- [ ] **Step 4: Commit the .gitignore chore**

Ensure `.gitignore` contains these two lines (add `.serena/` if missing):

```
.claude/settings.local.json
.serena/
```

```bash
git add .gitignore
git commit -m "chore: ignore local claude settings and serena cache"
```

---

### Task 2: `/healthz` route (TDD)

**Why:** The article promises restarts and autoscaling "completely invisible to the client" — but that only works if the platform can *detect* a dead instance and replace it. A health probe is the detection half; Docker's `HEALTHCHECK` (Task 3) and any future load balancer both need a cheap endpoint that answers without calling the bridge. ([Google stateless MCP article](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/) — "Horizontal Scaling & Failover".)

**Files:**
- Modify: `src/enphase_bridge_mcp/server.py` (after the `app: Starlette = ...` line, ~line 258)
- Test: `tests/unit/test_healthz.py`

**Interfaces:**
- Produces: `GET /healthz` → `200 {"status": "ok"}` on the same Starlette app that serves `/mcp`. Task 3's Docker HEALTHCHECK depends on this exact path and JSON body.

- [ ] **Step 1: Write the failing test**

```python
"""GET /healthz answers 200 without touching the bridge — Docker healthcheck target."""

from starlette.testclient import TestClient

from enphase_bridge_mcp.server import app


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_healthz.py -v`
Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Implement the route**

In `server.py`, extend the starlette imports and add the route right after `app: Starlette = server.streamable_http_app(stateless_http=True)`:

```python
from starlette.requests import Request
from starlette.responses import JSONResponse


async def _healthz(_request: Request) -> JSONResponse:
    """Liveness probe for Docker/proxy healthchecks; never calls the bridge."""
    return JSONResponse({"status": "ok"})


app.add_route("/healthz", _healthz, methods=["GET"])
```

(Keep the imports at the top of the file with the existing `from starlette.applications import Starlette` import; only the function and `add_route` call go after the `app` assignment.)

- [ ] **Step 4: Run the full unit suite + lint**

Run: `uv run pytest tests/unit --cov=src/enphase_bridge_mcp --cov-fail-under=80 && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/enphase_bridge_mcp/server.py tests/unit/test_healthz.py
git commit -m "feat: add /healthz liveness route for container healthchecks"
```

---

### Task 3: Dockerfile + .dockerignore

**Why:** This is the core of the rearchitecture. The article's deployment model is server-side compute the client reaches by URL — "run MCP servers as serverless functions on platforms like Google Cloud Run" — never a process the client launches on its own machine. A container is the unit that model runs on: immutable, restartable, holding zero session state, so "any container instance can handle any incoming request." The homelab container is the one-node version of Cloud Run. ([Google stateless MCP article](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/) — "Containers & Serverless", "Load Balancing".)

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `/healthz` from Task 2; `enphase-bridge-mcp` console script from `pyproject.toml`.
- Produces: image listening on `0.0.0.0:8000`, configured entirely via `ENPHASE_MCP_*` env vars. Task 4 (CD) publishes this exact file; Task 5's README compose snippet runs it.

- [ ] **Step 1: Write `.dockerignore`**

```
.git
.github
.venv
.claude
.claude-plugin
.serena
.remember
docs
skills
tests
features
htmlcov
.pytest_cache
.mypy_cache
.ruff_cache
*.md
!README.md
```

(`README.md` stays — `pyproject.toml` declares it, so installing the project needs it.)

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer, cached independently of source changes
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.14-slim
RUN useradd --create-home appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    ENPHASE_MCP_HOST=0.0.0.0
USER appuser
# Documents the default only — the real binding comes from ENPHASE_MCP_PORT.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; port=os.environ.get('ENPHASE_MCP_PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).status==200 else 1)"]
CMD ["enphase-bridge-mcp"]
```

Notes for the implementer:
- `ENPHASE_MCP_HOST=0.0.0.0` is the image default because a container serving only loopback is unreachable; the SDK then requires `ENPHASE_MCP_ALLOWED_HOSTS` to accept non-local Host headers (compose sets it).
- No `curl` install — the healthcheck uses the Python already in the image.
- If the base tag `ghcr.io/astral-sh/uv:python3.14-bookworm-slim` does not exist yet, fall back to `ghcr.io/astral-sh/uv:latest` COPY pattern: `FROM python:3.14-slim` + `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/`. Verify with `docker pull` before deciding.

- [ ] **Step 3: Build and smoke-test locally**

```bash
docker build -t enphase-bridge-mcp:local .
docker run -d --rm --name mcp-smoke -p 18000:8000 \
  -e ENPHASE_MCP_BRIDGE_URL=http://enphase-api.home \
  -e ENPHASE_MCP_ALLOWED_HOSTS=localhost:18000,127.0.0.1:18000 \
  enphase-bridge-mcp:local
sleep 3
curl -fs http://127.0.0.1:18000/healthz          # expect {"status":"ok"}
curl -fs -X POST http://127.0.0.1:18000/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -c 400
docker stop mcp-smoke
```

Expected: healthz JSON, then a tools/list response naming the 8 tools (proves stateless mode: no initialize handshake needed).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: containerize the MCP server (multi-stage uv build, non-root, healthcheck)"
```

---

### Task 4: CD workflow — publish to GHCR, gated on CI

**Why:** Server-side deployment (the article's model) means the homelab host must be able to *pull* a ready-built image — deploys become `docker compose pull && up`, no laptop builds, no source checkout on the server. Publishing only after green CI keeps the "no bypassing CI" rule; mirroring the enphase-bridge repo's CD pattern keeps both homelab services deployed the same way. (Article's serverless/registry model + house convention from `enphase-bridge/.github/workflows/cd.yml`.)

**Files:**
- Create: `.github/workflows/cd.yml`
- Modify: `.github/workflows/ci.yml` (trigger block only)

**Interfaces:**
- Consumes: CI workflow named exactly `CI` (see `ci.yml` line 1).
- Produces: `ghcr.io/thedandano/enphase-bridge-mcp` with tags `latest`, `<short-sha>`, and `vX.Y.Z` on release tags. The README compose snippet (Task 5) pulls `:latest`.

- [ ] **Step 1: Add tag trigger to CI**

In `.github/workflows/ci.yml`, change the `on:` block to:

```yaml
on:
  pull_request:
  push:
    branches: [dev, main]
    tags: ["v*"]
```

(Release-please pushes `vX.Y.Z` tags; without this, tag pushes never run CI, and CD — gated on CI — would never publish a version-tagged image.)

- [ ] **Step 2: Resolve action SHAs to pin**

```bash
for repo in docker/setup-qemu-action docker/setup-buildx-action docker/login-action docker/build-push-action; do
  echo "$repo $(gh api repos/$repo/git/ref/tags/v3 --jq .object.sha 2>/dev/null || gh api repos/$repo/git/ref/tags/v6 --jq .object.sha)"
done
```

(`build-push-action` is at v6; the others at v3. If a ref is an annotated tag — `object.type == "tag"` — dereference once more with `gh api repos/$repo/git/tags/<sha> --jq .object.sha`.) Use these SHAs in Step 3; reuse the checkout/setup-uv SHAs already in `ci.yml`.

- [ ] **Step 3: Write `.github/workflows/cd.yml`**

Single job, QEMU multi-arch (simpler than enphase-bridge's two-runner digest merge; a pure-Python image cross-builds in minutes). Replace each `<SHA-...>` with the value from Step 2:

```yaml
name: CD

on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    # No branch filter — tag-triggered CI runs have head_branch == the tag
    # name (e.g. v1.1.0), which a branches filter would reject.

env:
  IMAGE: ghcr.io/${{ github.repository }}

jobs:
  publish:
    name: Publish image
    if: |
      github.event.workflow_run.conclusion == 'success' &&
      (github.event.workflow_run.head_branch == 'main' ||
       startsWith(github.event.workflow_run.head_branch, 'v'))
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          ref: ${{ github.event.workflow_run.head_sha }}

      - uses: docker/setup-qemu-action@<SHA-qemu> # v3

      - uses: docker/setup-buildx-action@<SHA-buildx> # v3

      - uses: docker/login-action@<SHA-login> # v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Compute tags
        id: tags
        env:
          HEAD_BRANCH: ${{ github.event.workflow_run.head_branch }}
          HEAD_SHA: ${{ github.event.workflow_run.head_sha }}
        run: |
          set -euo pipefail
          tags="${IMAGE}:${HEAD_SHA:0:7},${IMAGE}:latest"
          if [[ "${HEAD_BRANCH}" == v* ]]; then
            tags="${tags},${IMAGE}:${HEAD_BRANCH}"
          fi
          echo "tags=${tags}" >> "$GITHUB_OUTPUT"

      - uses: docker/build-push-action@<SHA-build-push> # v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.tags.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 4: Lint the workflows**

Run: `uvx --from actionlint-py actionlint .github/workflows/cd.yml .github/workflows/ci.yml` (or `brew install actionlint && actionlint`).
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/cd.yml .github/workflows/ci.yml
git commit -m "feat: publish multi-arch image to GHCR after green CI"
```

---

### Task 5: Point the plugin at the homelab + README (with compose snippet)

**Why:** In the article's architecture the client holds only a URL — all server lifecycle lives behind it, so "pod restarts, rollouts, and autoscaling events are completely invisible to the client." This task gives the plugin that URL (env-configurable because the repo is public — each installer's hostname is their own) and gives humans the two server-side artifacts they need: the compose block to append and the proxy note. An ordinary reverse proxy suffices because the spec's standard `Mcp-*` headers let proxies route "without inspecting the request body." ([Google stateless MCP article](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/) — "HTTP Transport Standardization", "Horizontal Scaling & Failover".)

**Files:**
- Modify: `.mcp.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: the proxy hostname `enphase-mcp.home` (Task 6 creates the proxy entry).
- Produces: each installer points the plugin at their own server via `ENPHASE_MCP_URL`; the shipped default is neutral `localhost` — this is a public repo, no private homelab hostname gets baked in.

- [ ] **Step 1: Update `.mcp.json`**

```json
{
  "mcpServers": {
    "enphase": {
      "type": "http",
      "url": "${ENPHASE_MCP_URL:-http://localhost:8000/mcp}"
    }
  }
}
```

(Claude Code expands `${VAR:-default}` in `.mcp.json`. Verify Codex tolerates it: `codex plugin marketplace add` this repo locally and list tools; if Codex chokes on the syntax, hardcode `http://localhost:8000/mcp` and document the override in README instead. Dan then sets `ENPHASE_MCP_URL=http://enphase-mcp.home/mcp` in his shell profile — his homelab hostname never enters the repo.)

- [ ] **Step 2: README — add a "Deploy in your homelab" section**

Content to add (adapt heading levels to the existing README):

````markdown
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
      ENPHASE_MCP_BRIDGE_URL: http://enphase-api.home
      # Host headers the MCP transport accepts (DNS-rebinding protection).
      # Must list every name clients use to reach this container.
      ENPHASE_MCP_ALLOWED_HOSTS: enphase-mcp.home,enphase-mcp.home:80
    # If your reverse proxy runs in Docker, delete `ports`, join the proxy's
    # network, and point the proxy at enphase-mcp:8000 instead.
```

```bash
docker compose up -d enphase-mcp
curl -fs http://localhost:8000/healthz   # {"status":"ok"}
```

Then add a reverse-proxy entry (e.g. `enphase-mcp.home` → `<host>:8000`) and
keep `ENPHASE_MCP_ALLOWED_HOSTS` in the compose file in sync with the
hostname the proxy serves.

| Env var | Default | Meaning |
| --- | --- | --- |
| `ENPHASE_MCP_BRIDGE_URL` | `http://localhost:8080` | Where the enphase-bridge REST API lives |
| `ENPHASE_MCP_BRIDGE_API_KEY` | unset | Bearer token, if your bridge requires one |
| `ENPHASE_MCP_HOST` | `0.0.0.0` (in the image) | Interface the MCP server binds |
| `ENPHASE_MCP_PORT` | `8000` | Port the MCP server binds |
| `ENPHASE_MCP_ALLOWED_HOSTS` | empty | Comma-separated Host headers to accept (required when clients aren't loopback) |

### Point the plugin at your server

The bundled plugin connects to `http://localhost:8000/mcp` by default. To
point it at your homelab server instead, run this once (swap in your own
URL), then open a new terminal:

```bash
# macOS / zsh (the default shell)
echo 'export ENPHASE_MCP_URL=http://enphase-mcp.home/mcp' >> ~/.zshrc && source ~/.zshrc
```

```bash
# Linux / bash
echo 'export ENPHASE_MCP_URL=http://enphase-mcp.home/mcp' >> ~/.bashrc && source ~/.bashrc
```

That saves the setting permanently — every future Claude Code or Codex
session picks it up automatically.
````

- [ ] **Step 3: Install-regression check — BOTH marketplaces, before the PR**

The only file the install paths depend on that this PR touches is `.mcp.json` (the `${ENPHASE_MCP_URL:-...}` syntax is the risk — Codex may not expand it). `.claude-plugin/plugin.json` and `marketplace.json` are untouched, but verify the whole path anyway; the Codex "0 plugins" failure mode from the marketplace work was silent.

Claude Code (from a directory OUTSIDE this repo, so the project-scope `.mcp.json` doesn't mask the plugin):

```bash
claude plugin marketplace add /Users/dandano/workplace/enphase-bridge-mcp
claude plugin install enphase-bridge@enphase-plugins
# In a claude session: /mcp must list the enphase server, and with no
# ENPHASE_MCP_URL set the URL must resolve to http://localhost:8000/mcp.
# Then: ENPHASE_MCP_URL=http://127.0.0.1:18000/mcp claude  (with the Task 3
# smoke container running) — tools must actually answer.
```

Codex:

```bash
codex plugin marketplace add /Users/dandano/workplace/enphase-bridge-mcp
codex plugin list   # must show enphase-bridge, NOT 0 plugins
# Start codex, confirm the enphase MCP server connects (with ENPHASE_MCP_URL
# exported). If codex leaves ${ENPHASE_MCP_URL:-...} unexpanded / errors,
# fall back to a hardcoded http://localhost:8000/mcp in .mcp.json and
# document the "edit the URL" step in README — do NOT ship broken expansion.
```

Expected: both marketplaces install, both clients list the 8 tools, and the 4 bundled skills still appear in Claude Code (`/solar-checkin` etc. — skills are path-based and untouched, this is the regression tripwire). Clean up test installs afterward (`claude plugin uninstall`, `codex plugin remove`, marketplace removes) so the real GitHub-sourced install stays canonical.

- [ ] **Step 4: Commit, push, open the PR into dev**

```bash
git add .mcp.json README.md
git commit -m "feat: default the plugin to the homelab MCP URL; document Docker deployment"
git push -u origin feat/docker-homelab
gh pr create --base dev --title "Docker homelab deployment: containerize the stateless MCP server" \
  --body "Adds /healthz, Dockerfile (multi-stage uv, non-root), a README compose snippet to append to an existing homelab compose file, CI-gated GHCR publish (amd64+arm64), and makes the plugin URL configurable via ENPHASE_MCP_URL (neutral localhost default — no private hostnames in this public repo).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Then STOP for review — Dan and Codex leave PR comments; respond before implementing fixes (house rule).

---

### Task 6: Release, deploy, live verification

**Why:** The article's end state is a client that knows nothing but a URL. This task proves we reached it: image published through the release pipeline, container running in the homelab, proxy in front, laptop process gone — then a real solar question answered end-to-end with no local server running. (Closes the gap that started this work: the server logic was already stateless per the 2026-07-28 spec, but the *deployment* half of the Google design — server-side compute behind a stable URL — was missing.)

**Files:** none — operations. Runs after the PR is squash-merged into `dev`.

**Interfaces:**
- Consumes: everything above, released through the normal pipeline.

- [ ] **Step 1: Promote dev → main**

```bash
git checkout dev && git pull
gh pr create --base main --head dev --title "Release: Docker homelab deployment" --body "Promotes the Docker deployment work to main for release."
```

Squash-merge (Dan's call). Release-please then opens its release PR (expect a 1.1.0 minor bump from the `feat:` commits); merging it tags `vX.Y.Z` → CI runs on the tag → CD publishes `ghcr.io/thedandano/enphase-bridge-mcp:{latest,vX.Y.Z,<sha>}`.

- [ ] **Step 2: Verify the image exists**

```bash
docker pull ghcr.io/thedandano/enphase-bridge-mcp:latest
```

(If the package is private by default, make it public: repo → Packages → package settings → Change visibility.)

- [ ] **Step 3: Deploy on the homelab host — MANUAL, Dan's machine**

On the homelab box: append the README's service block to the existing all-containers compose file, `docker compose up -d enphase-mcp`, then add the proxy host **enphase-mcp.home → <homelab-host>:8000** in the proxy admin UI (same place `enphase-api.home` lives). This proxy step cannot be automated from here — hand it to Dan explicitly.

- [ ] **Step 4: End-to-end verification**

```bash
curl -fs http://enphase-mcp.home/healthz
curl -fs -X POST http://enphase-mcp.home/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -c 400
```

Expected: `{"status":"ok"}`, then the 8-tool listing. Then confirm the released install paths: Dan's installed plugin auto-updates (or reinstall from `thedandano/enphase-bridge-mcp` in both Claude Code and Codex) and both clients connect through `ENPHASE_MCP_URL` → the homelab. Finally, in a fresh Claude Code session, ask a real solar question ("how much did I produce today?") and confirm the answer comes back — through the homelab, with no local server process running.

- [ ] **Step 5: Decommission the laptop shell**

Kill the local background `uv run enphase-bridge-mcp` task and remove any local `.env`/launchd remnants pointing the plugin at `127.0.0.1:8000`. The homelab URL is now the only path.
