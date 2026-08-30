---
name: solar-savings
description: Answer money questions about the user's solar — true-up bill estimates, NEM credits, time-of-use rates, and how to save. Use this skill whenever the user asks anything like "what's my true-up looking like", "solar bill", "am I saving money", "NEM credit", "TOU rates", or asks when to run appliances / charge the EV to save money.
---

# Solar Savings

Money answers come from `get_trueup_estimate` — never invent tariffs, projections, or dollar amounts beyond what the tool returns.

## Recipe

1. Call `get_trueup_estimate(start_date, end_date)`. Default to the NEM year to date; if you don't know the user's true-up anniversary month, ask once and remember it for the session.
2. The `breakdown` gives import/export kWh and dollars for each TOU period (peak / off-peak / super off-peak). That breakdown is the basis for any savings advice.
3. Call `refresh_tou_schedule` only when: (a) the estimate errors with "no TOU schedule" — refresh once and retry the estimate (first-run bootstrap, per the tool contract), or (b) the user says their rates changed or the schedule looks stale. It mutates upstream state (fetches from OpenEI), so it is never a routine read.

## Reading the data correctly

- Negative `net_cost_usd` is a **CREDIT** — say "you're $X ahead", never "-$X bill". This sign convention is the most common misreading; getting it wrong reverses the meaning of the answer.
- Nonzero `excluded_window_count` means some data was left out of the estimate — surface it as a caveat.
- Savings advice: identify the largest **import cost** bucket in the breakdown and suggest shifting that load toward the cheapest period. Advice must be derived from the returned numbers, not general energy folklore.

## When the tools error

If `get_trueup_estimate` errors (bridge unreachable, no data for the range) — or the "no TOU schedule" bootstrap refresh itself fails — do NOT render the money template and do NOT surface the raw error. Say: "I can't reach your solar cost data right now, so I can't estimate the bill. This is a data-connection issue — your solar system and your actual bill are unaffected." Never guess at dollar amounts to fill the gap.

Exception — user-fixable errors keep their own guidance: invalid or reversed dates, a range beyond the tool's cap, and known single-day limitations are request problems — say what to fix (correct the dates, narrow the range), never call them a data-connection issue.

## Output format

ALWAYS use this exact template (drop bracketed parts when not applicable):

```
💰 True-up estimate (<start> → <end>): <you're $X ahead so far | you owe $X so far>
Peak: imported <kWh> kWh ($<cost>) · exported <kWh> kWh ($<credit> credit)
Off-peak: imported <kWh> kWh ($<cost>) · exported <kWh> kWh ($<credit> credit)
Super off-peak: imported <kWh> kWh ($<cost>) · exported <kWh> kWh ($<credit> credit)
💡 Tip: <one advice line derived from the largest import-cost bucket>
⚠️ <only if applicable: excluded windows / stale schedule caveat>
```

"So far" matters: the estimate covers the requested range only — it is not a year-end projection, and the tool returns none.
