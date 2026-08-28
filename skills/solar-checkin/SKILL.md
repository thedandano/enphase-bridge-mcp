---
name: solar-checkin
description: Answer quick questions about the user's home solar system right now and today. Use this skill whenever the user asks anything like "how's my solar", "how much am I producing right now", "solar today", "how'd we do today vs yesterday", "is my system exporting", or any casual check-in about current solar production, consumption, or grid flow — even if they don't name a tool.
---

# Solar Check-in

Answer with real numbers from the enphase MCP tools — never estimate or invent values.

## Recipe

1. Call `get_current_status` — always.
2. Also call `compare_days` (defaults: today vs yesterday) when the user implies a comparison ("how am I doing", "vs yesterday", "better than").

## Reading the data correctly

- `grid_w` negative means **exporting** — phrase as "sending X W to the grid"; positive means drawing from the grid. Say which, never a raw signed number.
- `is_online` false means the data is stale — say so, cite `last_data_at`, and do NOT present the wattage numbers as live.
- `today_data_completeness_pct` below 100 means today's totals are built from partial data (collector gap) — caveat the totals in one line.
- These caveats exist because presenting stale or partial data as live is worse than no answer.

## Output format

ALWAYS use this exact template (drop the bracketed parts when not applicable):

```
☀️ Right now: <X> W producing · <Y> W using · <sending Z W to grid | drawing Z W from grid>
📊 Today: <A> kWh produced · <B> kWh used [ · vs yesterday: <±C> kWh (<±D>%) ]
⚠️ <only if applicable: stale-data or partial-data caveat, one line>
```

Keep any extra commentary to one sentence after the template unless the user asks for more.
