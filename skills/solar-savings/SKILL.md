---
name: solar-savings
description: Answer money questions about the user's solar — true-up bill estimates, NEM credits, time-of-use rates, and how to save. Use this skill whenever the user asks anything like "what's my true-up looking like", "solar bill", "am I saving money", "NEM credit", "TOU rates", or asks when to run appliances / charge the EV to save money.
---

# Solar Savings

Money answers come from `get_trueup_estimate` — never invent tariffs, projections, or dollar amounts beyond what the tool returns.

## Recipe

1. Call `get_trueup_estimate(start_date, end_date)`. Default to the NEM year to date; if you don't know the user's true-up anniversary month, ask once and remember it for the session.
2. The `breakdown` gives import/export kWh and dollars for each TOU period (peak / off-peak / super off-peak). That breakdown is the basis for any savings advice.
3. Call `refresh_tou_schedule` only when: (a) the estimate errors with "no TOU schedule" — refresh once and retry the estimate (first-run bootstrap, per the tool contract), or (b) the user says their rates changed or the schedule looks stale — but in case (b), **ask first** ("I can refresh the saved rate schedule from OpenEI — want me to?") and only call it after the user says yes. It mutates upstream state (fetches from OpenEI), so it is never a routine read and never an unprompted one.

## Reading the data correctly

- Negative `net_cost_usd` is a **CREDIT** — say "you're $X ahead", never "-$X bill". This sign convention is the most common misreading; getting it wrong reverses the meaning of the answer.
- Nonzero `excluded_window_count` means some data was left out of the estimate — surface it as a caveat.
- Savings advice: identify the largest **import cost** bucket in the breakdown and suggest shifting that load toward the cheapest period. Advice must be derived from the returned numbers, not general energy folklore.
- **Never invent clock hours.** The breakdown names TOU periods (peak / off-peak / super off-peak) but does NOT include their hours, and no tool provides them. Say "shift flexible use toward <cheapest period name>; check your utility plan for its exact hours" — never a specific time like "after 9 PM".

## Output format

ALWAYS use this exact template (drop bracketed parts when not applicable):

```
💰 True-up estimate (<start> → <end>): <you're $X ahead so far | you owe $X so far>
Peak: imported <kWh> kWh ($<cost>) · exported <kWh> kWh ($<credit> credit)
Off-peak: imported <kWh> kWh ($<cost>) · exported <kWh> kWh ($<credit> credit)
Super off-peak: imported <kWh> kWh ($<cost>) · exported <kWh> kWh ($<credit> credit)
💡 Tip: <one advice line derived from the largest import-cost bucket>
Based on: <tou_schedule.rate_label>, effective <tou_schedule.effective_date | date unknown>
⚠️ <only if applicable: excluded windows / stale schedule caveat>
```

"So far" matters: the estimate covers the requested range only — it is not a year-end projection, and the tool returns none.
