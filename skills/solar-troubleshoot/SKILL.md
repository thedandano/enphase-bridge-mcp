---
name: solar-troubleshoot
description: Diagnose problems with the user's solar system. Use this skill whenever the user asks anything like "is something wrong with my solar", "inverter offline", "production seems low", "panels not working", "system down?", or expresses any worry that their solar setup is broken or underperforming.
---

# Solar Troubleshoot

Diagnose in a fixed order — the order matters because stale data mimics dead hardware.

## Diagnosis recipe (in order)

1. `get_inverter_health` — check `data_as_of` FIRST. If it's old, suspect the collector/bridge pipeline, **not the panels** — but don't classify anything yet; a stale snapshot alone proves nothing until step 3 confirms it.
2. Check `attention_needed` — each entry is a specific offline inverter with its array and last-report time.
3. `get_current_status` — live confirmation (is_online, current watts). Only now do the two freshness signals together support a classification.
4. `compare_days` for today-vs-yesterday, or `get_period_summary` over the last ~7 days — size the actual production impact in one call.

## Daylight rule

Never diagnose "low production" from current watts outside daylight hours — zero watts at night is a healthy system. Near dawn or dusk, low watts are expected too; judge production from full-day totals (step 4), not the live number. This skill has no weather source: clouds/shading may be offered as a *possible* explanation, never a confirmed cause.

## The three failure classes — always name which one applies

- **Data pipeline problem**: BOTH signals agree — `data_as_of` old AND `is_online` false → the enphase-bridge service or collector is down; the panels are probably fine. If tools error with "Cannot reach enphase-bridge", say to check that the bridge service is running. If the two signals disagree (one stale, one fresh), say "data freshness is inconsistent; I can't confirm inverter health yet" — don't pick a failure class.
- **Inverter(s) need attention**: specific serials in `attention_needed` while the rest report fine.
- **Low production**: all inverters online, output just low **during daylight and across recent full days** — offer weather/season as a possible (not confirmed) explanation before suggesting anything is broken.
- **Unable to confirm live output**: `get_current_status` errors with "no power samples" while inverter health looks fine → say the live reading is unavailable right now, and judge from daily totals instead — don't guess at the live state.

## Output format

ALWAYS use this exact template (drop bracketed parts when not applicable):

```
🔍 Diagnosis: <healthy | data pipeline problem | N inverter(s) need attention | low production | data freshness inconsistent — can't confirm yet | unable to confirm live output>
Data freshness: <data_as_of, flagged if stale>
Arrays: <name>: <online>/<total> online (<watts> W)   (one line per array)
[ Attention: <serial> in <array> — last reported <when> ]   (one line per flagged inverter)
➡️ Next step: <single most useful action for the user>
```
