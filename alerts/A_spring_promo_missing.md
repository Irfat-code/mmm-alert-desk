# Review A: April 2025 spring sale missing from the promo calendar (scenario_A)
Raised: 2026-11-18 (monthly review, no alert)  |  Triage done: 2026-11-18  |  Resolved: open, waiting on calendar fix and refit

**Bottom line.** A two-week spring sale in April 2025 is missing from the promo calendar. The model saw a sales jump with no sale to explain it and reshaped Meta's curve to cover part of it. The reports now say Meta got worse (ROAS −11%), while the model's curves say Meta can take twice its peak budget. Both readings are wrong. Don't move budget on this run until the sale is back in the calendar and the model is rerun.

## Symptom
No alert. ROAS against baseline: Meta 2.3295 → 2.0660 (−11.3%), Google 2.1620 → 2.4772 (+14.6%), TikTok 1.7096 → 1.9175 (+12.2%). All are under 25% and inside baseline's 90% intervals.

## Hypotheses
1. **Confirmed:** calendar or control data changed.
2. **Rejected:** a campaign remapped between channels, changed spend, changed sales, a prior or spec edit. Raw spend, sales, map and spec all match.
3. **Tested and not supported:** the model decided Meta doesn't explain the lift and pushed it to other channels.

## Evidence
Outputs: [results/investigations/scenario_A/](../results/investigations/scenario_A/), with the fix test in `scenario_A_fixpromo/`.
- **From A alone** (`residual_weeks`, `promo_calendar__scenario_A`): the two largest misses are 2025-04-14 (+12.5%) and 2025-04-07 (+11.1%). Revenue beat the model in back-to-back weeks with Meta at 2.25x and 2.35x its median week, and with no promo or holiday on the calendar. The promo IDs skip from 9 to 11. Each year still shows 4 promos, so counting promos per year would not reveal the gap.
- **Confirmation against last month's snapshot** (`table_rows_diff`, `model_input_full_diff`): one row is missing, promo 10 "SPRING25", 2025-04-07 to 04-20, 25% off. Only `promo_intensity` changed (0.25 → 0, in 2 weeks). Everything else matches.
- **Mechanism** (`week_decomp`, `week_decomp_test`, `run_params`): Meta's credit went **up** in the sale weeks (+6,392 and +8,984) and was flat in the pre-sale spike week 03-31 (−403). It went down in other weeks (average −6,574). Its change tracks its spend (corr 0.89). The model straightened Meta's curve (lam 3.24 → 1.45; beta 0.289 → 0.516, outside baseline's interval) to reach the lift through Meta's peak weeks. The no-lift week 03-31 shows the cost: A overshoots it by more (−10.0% against −6.0%). Google gained a flat amount in every week (+4,870, sd 600), filling the base Meta lost.
- **Causal test:** a copy of A with only SPRING25 restored matches the clean input in every column. Refitting it with A's config reproduced baseline exactly: every ROAS changed by 0.0.

## Classification
DATA. One row is missing from a control table. The model reacted as designed to the input it got.

## Root cause
SPRING25 was an ad-hoc sale, named outside the usual PROMO_YYYY_N pattern, and it never reached `promo_calendar`. Ad-hoc promos are the ones most likely to be missed.

## Recommendation
- **Today (MMM analyst):** re-enter SPRING25 from the marketing team's records, refit, and rerun `monitor.py`. Expect baseline's results, as the fix test showed.
- **Prevention:** the brand's marketing team signs off the promo calendar every month, ad-hoc sales included. Add a calendar snapshot check: past rows in `promo_calendar` and `holiday_calendar` must not change between loads.

## Impact
- **Average ROAS:** Meta −11.3%, Google +14.6%, TikTok +12.2%.
- **Marginal ROAS at average spend** (`marginal_roas_diff`), which is what budget decisions use: Meta 1.71 → 1.95 (+13.9%), TikTok 1.67 → 1.83 (+9.6%), Google 1.70 → 1.72 (+1.0%). Meta's 90% saturation point moved from 91% of peak ($49,451 a week) to 203% ($110,127). A budget tool would push money into Meta on the strength of a lift that was really the sale.
- CAC is unchanged: spend and new customers are identical.

## Why the monitor missed it, and what would catch it
- **Current rules:** checks 01–03 don't read the calendars. R2 fell 0.0148 (threshold 0.05), MAPE rose 0.0022 (threshold 0.02). ROAS shifts were under 25% and inside the intervals. CAC is unchanged. 0 divergences, R-hat 1.0008. Media share 53.1%.
- **v2 candidates that would miss it:** freshness gate, reconciliation gate, two-way CAC, convergence tolerance, check 03 refinement and spec diff. Spend, sales, dates and spec are all unchanged. Control shift also misses: the promo coefficient held at 0.5985 → 0.5996, estimated from the other 12 promos.
- **New candidates that catch it** (`rule_tests.csv`, all 0 on the 3 clean runs):
  - **Calendar diff:** fires on A only.
  - **Parameter shift** (any media parameter's interval stops overlapping baseline's): fires on A (Meta beta) and E.
  - **Residual shift** (a week's residual moves more than 5 points against baseline's in the same week): A 12.65 points, clean 0.28. It also fires on C and D. The threshold rests on a single clean seed, so calibrate it on more seeds before adopting.
