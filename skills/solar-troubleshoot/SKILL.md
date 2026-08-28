---
name: solar-troubleshoot
description: Diagnose problems with the user's solar system. Use this skill whenever the user asks anything like "is something wrong with my solar", "inverter offline", "production seems low", "panels not working", "system down?", or expresses any worry that their solar setup is broken or underperforming.
---

# Solar Troubleshoot

Diagnose in a fixed order — the order matters because stale data mimics dead hardware.

## Diagnosis recipe (in order)

1. `get_inverter_health` — check `data_as_of` FIRST. If it's old, the collector/bridge pipeline is the problem, **not the panels**; don't report inverters as broken from stale data.
2. Check `attention_needed` — each entry is a specific offline inverter with its array and last-report time.
3. `get_current_status` — live confirmation (is_online, current watts).
4. `compare_days` or `get_daily_summary` for recent days — size the actual production impact.

## The three failure classes — always name which one applies

- **Data pipeline problem**: everything looks stale (`data_as_of` old, `is_online` false) → the enphase-bridge service or collector is down; the panels are probably fine. If tools error with "Cannot reach enphase-bridge", say to check that the bridge service is running.
- **Inverter(s) need attention**: specific serials in `attention_needed` while the rest report fine.
- **Low production**: all inverters online, output just low — check recent days and note weather/season before suggesting anything is broken.

## Output format

ALWAYS use this exact template (drop bracketed parts when not applicable):

```
🔍 Diagnosis: <healthy | data pipeline problem | N inverter(s) need attention | low production>
Data freshness: <data_as_of, flagged if stale>
Arrays: <name>: <online>/<total> online (<watts> W)   (one line per array)
[ Attention: <serial> in <array> — last reported <when> ]   (one line per flagged inverter)
➡️ Next step: <single most useful action for the user>
```
