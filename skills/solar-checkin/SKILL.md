---
name: solar-checkin
description: Answer quick questions about the user's home solar system right now, today, or a single specific day. Use this skill whenever the user asks anything like "how's my solar", "how much am I producing right now", "solar today", "how'd we do today vs yesterday", "how'd solar do yesterday", "is my system exporting", "why am I buying power", "am I importing from the grid", "why am I exporting so much", or any casual check-in about current solar production, consumption, or grid flow — even if they don't name a tool.
---

# Solar Check-in

Answer with real numbers from the enphase MCP tools — never estimate or invent values.

## Recipe

1. Call `get_current_status` — always, when the question involves "now" or today.
2. Also call `compare_days` (defaults: today vs yesterday) when the user implies a comparison ("how am I doing", "vs yesterday", "better than").
   **Partial-day rule**: while today is still in progress, today-vs-yesterday is an unfair comparison (a partial day against a full one). Never conclude production is "down X%" mid-day. Present yesterday's final total as a reference ("15.7 kWh so far · yesterday finished at 22.3 kWh") and, if a verdict is wanted, frame it as pace ("on pace to match yesterday"), noting the day isn't over. The raw percent delta from the tool may only be stated once today is complete.
3. For a specific past day ("yesterday", "last Tuesday"), call `get_daily_summary(date)` instead of `get_current_status` and use the **historical template** below (it replaces the live template entirely — there is no "right now" for a finished day). Resolve day names in Pacific time and label the date as Pacific.

## Reading the data correctly

- `grid_w` negative means **exporting** — phrase as "sending X W to the grid"; positive means drawing from the grid. Say which, never a raw signed number.
- `is_online` false means the data is stale — say so, cite `last_data_at`, and do NOT present the wattage numbers as live.
- `is_power_data_consistent` false means the live wattage channels contradict each other (a known upstream sensor issue) — present today's kWh totals normally, but replace the template's "☀️ Right now" line with `☀️ Right now: live reading unavailable (sensor data inconsistent)` instead of reporting the raw watts as fact. This overrides the template.
- `today_data_completeness_pct` below 100 means today's totals are built from partial data (collector gap) — caveat the totals in one line.
- These caveats exist because presenting stale or partial data as live is worse than no answer.

## When the tools error

If a tool errors (bridge unreachable, no data, no recent power samples), do NOT render the numeric template and do NOT surface the raw error. Say: "I can't read your home's solar data right now, so I can't tell whether the system is producing normally. This is a data-connection issue, not proof that anything is wrong with the panels. Try again once the bridge is back online." A data outage must never read as a solar-system failure.

## Output format

ALWAYS use this exact template (drop the bracketed parts when not applicable):

```
☀️ Right now: <X> W producing · <Y> W using · <sending Z W to grid | drawing Z W from grid | no net grid flow (0 W)>
📊 Today so far: <A> kWh produced · <B> kWh used [ · yesterday finished at <Y> kWh ]
⚠️ <only if applicable: stale-data or partial-data caveat, one line>
```

Historical template (for a finished day — replaces the live one):

```
📊 <Weekday>, <date> (Pacific): <A> kWh produced · <B> kWh used [ · vs <other day>: <±C> kWh ]
⚠️ <only if data_completeness_pct < 100: "Only N% of expected readings were available; totals may be understated.">
```

Comparison fine print: if the comparison day's value is 0 kWh, the tool reports a 0% delta as a division-by-zero guard — show the kWh difference and say "percentage change: not available (comparison day was 0 kWh)", never "0% change".

Keep any extra commentary to one sentence after the template unless the user asks for more.
