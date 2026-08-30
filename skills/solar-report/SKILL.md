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
- `avg_daily_produced_kwh`, `best_day`, and `worst_day` come back **null** when the range has no finished day with data (e.g. "today so far", or a week that just started). Render that line as `Daily average / best / worst: not available until a full day is complete` — never as 0 kWh. This **overrides the template's** daily-average line.
- **Partial current period vs finished prior period**: when the current range is still in progress (it includes today, or `is_partial` days), the template's `vs <prior period>` clause must be phrased as "so far" against the prior period's full total (e.g. "42 kWh so far vs 61 kWh for the full prior week") — never as an unqualified delta or percent. A "down X%" verdict is only allowed when both periods are complete.
- `data_completeness_pct` below 100, days with `has_data` false, **or any day with `is_partial` true** mean gaps: caveat in one line and **name the affected dates** (e.g. "⚠️ Data is missing for Aug 4 and Aug 6"). When gaps exist, don't state a trend conclusion ("production improved") — say the comparison is incomplete instead. Note `data_completeness_pct` can read 100 while today is still in progress (its denominator is windows expected *so far*) — so a range that includes today always gets the caveat, and a comparison against a completed prior period must name the partial day rather than compare as complete. The daily average already excludes unfinished/missing days — say so if the user asks why numbers look different.
- **Unequal periods**: when the two compared ranges have different day counts, compare completed-day averages or say the totals are not directly comparable — never a raw total-vs-total verdict.
- **Zero baseline**: percent deltas come back 0.0 when the comparison period's value is 0 kWh (division-by-zero guard). Show the kWh difference and say "percentage change: not available (comparison period was 0 kWh)", never "0% change".

## Output format

ALWAYS use this exact template (drop bracketed parts when not applicable):

```
📈 <period label (Pacific)> solar report
Produced: <A> kWh · Used: <B> kWh · Energy balance (produced − used): <±C> kWh · Self-consumed: <D>%
Daily average: <E> kWh · Best: <date> (<F> kWh) · Worst: <date> (<G> kWh)
[ vs <prior period>: produced <±H> kWh (<±I>%) ]
⚠️ <only if applicable: completeness/missing-days caveat, one line>
```

One sentence of interpretation after the template is welcome; longer analysis only on request.
