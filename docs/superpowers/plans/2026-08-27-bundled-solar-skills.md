# Bundled Solar Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bundle 4 natural-language skills with the enphase-bridge plugin so user questions route to the right multi-tool recipes with correct interpretation.

**Architecture:** Markdown-only — `skills/<name>/SKILL.md` × 4 at repo root (auto-discovered by Claude Code and Codex plugin loaders; no manifest changes). Each skill = trigger-rich frontmatter + one-page body: tool recipe (order + params) and judgment rules the tool docstrings can't carry. No code, no new gates.

**Tech Stack:** Claude Code plugin skills format (YAML frontmatter `name`/`description` + markdown). Use `skill-creator:skill-creator` at execution start for structure/description best practices; `plugin-dev:skill-reviewer` agent for review.

**Spec:** Approved in-chat brainstorm (2026-08-27): 4 focused skills — checkin, report, savings, troubleshoot; recipes+judgment per section below. Copy this plan to `docs/superpowers/plans/2026-08-27-bundled-solar-skills.md` in Task 0.

## Global Constraints

- **Sync first, own PR:** `git checkout dev && git fetch && git pull --ff-only` (merge PR #8 state comes along); new branch `feature/bundled-skills` off `dev`; NEW PR into `dev` at the end — do not piggyback on #8.
- **Structured, repeatable output:** every skill body MUST define an explicit output template (fixed section order, fixed labels) that the answer follows every time — users get the same shape for the same kind of question. Templates specified per task below.
- The 8 MCP tools (exact names): get_current_status, get_daily_summary, compare_days, get_period_summary, compare_periods, get_inverter_health, get_trueup_estimate, refresh_tou_schedule. Skills reference tools by these names.
- Verified upstream facts skills must encode: negative grid_w/net_cost_usd = export/credit; data_completeness_pct <100 means partial data; get_period_summary caps at 92 days; get_inverter_health.data_as_of reveals collector staleness; skills must NEVER instruct inventing numbers — only narrate tool output.
- No new dependencies, no pyproject/uv.lock changes, hooks never bypassed.
- Each SKILL.md ≤ ~80 lines. Frontmatter `description` must contain concrete trigger phrasings (that's what routes NL → skill).

---

### Task 0: Sync + branch + plan doc

**Files:** Create: `docs/superpowers/plans/2026-08-27-bundled-solar-skills.md`

- [ ] `git checkout dev && git fetch --prune && git pull --ff-only` (pick up PR #8 if merged; if #8 still open, branch from dev anyway — skills don't depend on the manifests at build time, note it in the PR body).
- [ ] `git checkout -b feature/bundled-skills`; copy this plan file into the repo path above.
- [ ] Invoke `Skill(skill-creator:skill-creator)` and follow its structure guidance for all four skills (progressive disclosure, description-writing rules). Where skill-creator conflicts with the content spec below, the content spec wins.
- [ ] Commit: `docs: add bundled-solar-skills plan` (standard trailers).

### Task 1: skills/solar-checkin/SKILL.md

**Interfaces — Produces:** skill name `solar-checkin`.

- [ ] Write SKILL.md. Frontmatter description triggers: "how's my solar", "how much am I producing right now", "solar today", "today vs yesterday", "is my system exporting". Body content (write as prose/bullets, not placeholders):
  - Recipe: `get_current_status` first; add `compare_days()` (defaults today/yesterday) when the user implies comparison or asks "how am I doing".
  - Judgment: if `is_online` false → say data is stale since `last_data_at`, don't quote current watts as live; if `today_data_completeness_pct` < 100 → caveat totals as partial; `grid_w` negative = exporting (phrase as "sending X W to the grid").
  - Output template (verbatim in skill, answer must follow it):
    ```
    ☀️ Right now: <X> W producing · <Y> W using · <sending Z W to grid | drawing Z W from grid>
    📊 Today: <A> kWh produced · <B> kWh used [ · vs yesterday: <±C> kWh (<±D>%) ]
    ⚠️ <only if applicable: stale-data or partial-data caveat, one line>
    ```
- [ ] Validate frontmatter parses: `python3 -c "import yaml,pathlib; t=pathlib.Path('skills/solar-checkin/SKILL.md').read_text(); yaml.safe_load(t.split('---')[1])"` → prints nothing (or use uv run python if pyyaml present in venv; else visually verify `name:`/`description:` lines).
- [ ] Commit: `feat: solar-checkin skill`.

### Task 2: skills/solar-report/SKILL.md

- [ ] Write SKILL.md. Triggers: "how was my solar last week/month", "solar report", "production trends", "compare this month to last". Body:
  - Recipe: `get_period_summary(start,end)`; for trends `compare_periods` with an equal-length immediately-prior period (compute dates; note tool returns both day counts); mention best_day/worst_day.
  - Judgment: ranges >92 days → split into chunks or ask user to narrow (tool errors by design); caveat `data_completeness_pct` <100 and days with `has_data` false; never average across missing days (tool already excludes — say so if asked).
  - Output template (verbatim in skill):
    ```
    📈 <period label> solar report
    Produced: <A> kWh · Used: <B> kWh · Net: <±C> kWh · Self-consumed: <D>%
    Daily average: <E> kWh · Best: <date> (<F> kWh) · Worst: <date> (<G> kWh)
    [ vs <prior period>: produced <±H> kWh (<±I>%) ]
    ⚠️ <only if applicable: completeness/missing-days caveat, one line>
    ```
- [ ] Frontmatter validation as Task 1.
- [ ] Commit: `feat: solar-report skill`.

### Task 3: skills/solar-savings/SKILL.md

- [ ] Write SKILL.md. Triggers: "true-up", "solar bill", "am I saving money", "NEM credit", "when should I run the dishwasher/EV charger", "TOU rates". Body:
  - Recipe: `get_trueup_estimate(start,end)` — default the NEM year to date if user doesn't give dates (ask which month their true-up anniversary is if unknown); breakdown has peak/off_peak/super_off_peak import/export kWh and $ each. `refresh_tou_schedule` ONLY when user says rates changed or schedule looks stale — it mutates upstream state.
  - Judgment: negative net_cost_usd = CREDIT — say "you're $X ahead", never "-$X bill"; surface excluded_window_count if nonzero; savings advice = narrate from the breakdown (e.g. biggest import cost bucket → suggest shifting that load off-peak); no invented tariffs or projections beyond the returned numbers.
  - Output template (verbatim in skill):
    ```
    💰 True-up estimate (<start> → <end>): <you're $X ahead | on track to owe $X>
    Peak: imported <A> kWh ($<B>) · exported <C> kWh ($<D> credit)
    Off-peak: ... · Super off-peak: ...   (same shape per period)
    💡 Tip: <one advice line derived from the largest import-cost bucket>
    ⚠️ <only if applicable: excluded windows / stale schedule caveat>
    ```
- [ ] Frontmatter validation as Task 1.
- [ ] Commit: `feat: solar-savings skill`.

### Task 4: skills/solar-troubleshoot/SKILL.md

- [ ] Write SKILL.md. Triggers: "is something wrong with my solar", "inverter offline", "production seems low", "panels not working", "system down?". Body:
  - Recipe (diagnosis order): 1) `get_inverter_health` — check `data_as_of` FIRST (stale = collector/bridge problem, not panels); 2) `attention_needed` list = specific offline inverters with last-report times; 3) `get_current_status` for live confirmation; 4) `compare_days` or `get_daily_summary` for recent days to size the production impact.
  - Judgment: distinguish three failure classes explicitly — bridge/collector down (stale data everywhere), individual inverters offline (attention_needed), genuinely low production (all online, low kWh — check weather/season before alarming); recommend checking the enphase-bridge service when tools error with "Cannot reach".
  - Output template (verbatim in skill):
    ```
    🔍 Diagnosis: <healthy | data pipeline problem | N inverter(s) need attention | low production>
    Data freshness: <data_as_of, flagged if stale>
    Arrays: <name>: <online>/<total> online (<watts> W)   (one line per array)
    [ Attention: <serial> in <array> — last reported <when> ]   (one line per flagged inverter)
    ➡️ Next step: <single most useful action for the user>
    ```
- [ ] Frontmatter validation as Task 1.
- [ ] Commit: `feat: solar-troubleshoot skill`.

### Task 5: README + review + ship

**Files:** Modify: `README.md` (after "Try it" section)

- [ ] Add README section "Bundled skills" — 4 bullets, one line each: skill name + the question it answers.
- [ ] Dispatch `plugin-dev:skill-reviewer` agent over `skills/` (focus: description trigger quality, body clarity); apply real findings, skip false positives with reasons.
- [ ] Run `uv run pre-commit run --all-files` — all green (markdown adds nothing to gates; proves nothing broke).
- [ ] Smoke: `claude --plugin-dir . -p "how's my solar today?" --max-turns 2` (server may be down — success = the skill loads/triggers, tool error is fine and expected offline). If `--plugin-dir` unavailable in this CLI build, note it and rely on skill-reviewer + manual frontmatter checks.
- [ ] Commit: `docs: bundled skills README section`; push `feature/bundled-skills`; `gh pr create --base dev` (new PR, standard body + footer); watch CI green.

## Self-Review (done)

Spec coverage: 4 skills ↔ 4 approved moments ✓; placeholders: none — all trigger phrases and judgment rules stated inline ✓; consistency: tool names match models/server implementations (8 tools, exact snake_case) ✓.

## Verification (end-to-end)

1. All gates green on PR #8; CI pass.
2. `codex plugin marketplace add <local path>` + `codex plugin add enphase-bridge@enphase-plugins` → skills appear in the plugin snapshot (`ls ~/.codex/plugins/cache/enphase-plugins/enphase-bridge/*/skills/`); remove test install after.
3. With bridge + server running: ask "how's my solar today vs yesterday?" in a Claude session with the plugin — confirm the checkin skill loads and the answer includes the completeness/staleness framing.
