---
name: solar-report
description: Produce a structured report on the user's solar production over a period — a week, a month, a season. Use this skill whenever the user asks anything like "how was my solar last week", "solar report for July", "production trends", "compare this month to last month", "what was my best day", or wants any multi-day summary or period-over-period comparison of solar data.
---

# Solar Report

Build reports from the enphase MCP tools — never estimate or fill gaps with invented numbers.

## Recipe

1. Resolve the user's period to Pacific calendar dates (`YYYY-MM-DD`).
2. Call `get_period_summary(start_date, end_date)` for the period.
3. For trends or "vs ..." questions, also call `compare_periods` with the comparison period the user implies (e.g. "July vs last July" = one year back); default to the equal-length, immediately-prior period (last week vs the week before). The tool returns both day counts — mention them if the periods differ.
4. Pull `best_day` / `worst_day` from the summary — they only consider days with real, finished data.

## Limits and caveats

- The tools cap ranges at **92 days** and error beyond it by design. For longer questions, split into chunks (e.g. quarters) or ask the user to narrow — don't retry blindly.
- `data_completeness_pct` below 100 or days with `has_data` false mean gaps: caveat in one line. The daily average already excludes unfinished/missing days — say so if the user asks why numbers look different.

## Output format

ALWAYS use this exact template (drop bracketed parts when not applicable):

```
📈 <period label> solar report
Produced: <A> kWh · Used: <B> kWh · Net: <±C> kWh · Self-consumed: <D>%
Daily average: <E> kWh · Best: <date> (<F> kWh) · Worst: <date> (<G> kWh)
[ vs <prior period>: produced <±H> kWh (<±I>%) ]
⚠️ <only if applicable: completeness/missing-days caveat, one line>
```

One sentence of interpretation after the template is welcome; longer analysis only on request.
