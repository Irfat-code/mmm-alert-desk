# Alert A003: Shopify orders stopped loading 9 days early (scenario_C)
Raised: 2026-11-18  |  Triage done: 2026-11-18  |  Resolved: open, waiting on Shopify backfill

**Bottom line.** Shopify sales after December 19 never reached the model, but ad spend did. Channel ROAS for Meta, Google and TikTok barely moved. The latest week's cost per new customer reads 37.6% too high, because it counts a full week of spend against five days of sales. Don't use last week's CAC until the missing days are reloaded and the model is rerun.

## Symptom
Alert ID A003, check `data_check rows:02_incomplete_weeks`. The check returned 2 rows on the scenario_C database, against 0 on baseline. It was the only alert for this run. Fit, ROAS, CAC, convergence and plausibility rules all stayed under their thresholds.

## Hypotheses
1. Late or partial refresh: one source ends before the others. Test: compare MAX(date) per source with baseline.
2. Days missing mid-history. Test: compare rows and distinct dates per source per week with baseline.
3. Dates collided (timezone or parse error). Test: rows vs distinct dates, dates outside `dim_date`.
4. `dim_date` changed. Test: compare its size, range and days per week with baseline.

## Evidence
Queries: [sql/investigations/scenario_C.sql](../sql/investigations/scenario_C.sql), run with `python src/run_investigation.py scenario_C` and `python src/compare_runs.py scenario_C`. Outputs are in [results/investigations/scenario_C/](../results/investigations/scenario_C/).

- `source_totals`: `shopify_orders_daily` ends 2025-12-19, with 1956 rows over 1083 dates. Baseline ends 2025-12-28 with 1974 rows over 1092 dates. `raw_ad_spend` is identical to baseline and ends 2025-12-28. No dates fall outside `dim_date`.
- `week_diff`: only two weeks differ. Week 2025-12-15 has 5 of 7 order days, and its revenue, orders and new customers are each 27.3% below baseline. Week 2025-12-22 has no orders. Spend is unchanged in both weeks. Earlier weeks match. Rows and dates fell together, so dates did not collide.
- `dim_date_profile`: identical, with 1092 days, 156 weeks and every week 7 days.
- `model_input_rows`: 155 weeks against 156. `weekly_model_input` is built from the sales CTE, so week 2025-12-22 drops out entirely and is never shown as zero. Week 2025-12-15 stays in, with 7 days of spend against 5 days of sales.
- `cac_rule_variants`: the current rule compares 2025-12-08 and 2025-12-15 with the 12 weeks before. CAC is 32.51 against 31.70, +2.6%, so it does not fire. On complete weeks only, it is 28.63 against 31.55, −9.3%, and does not fire. On calendar weeks, with missing sales counted as zero, it is 67.40 against 31.32, +115.2%, and fires.
- `run_fit_tail`: the last fitted week (2025-12-15) has actual revenue 186,435 against predicted 243,745, a −23.5% residual. Baseline's last four residuals are within ±3.1%.

## Classification
DATA. The Shopify source table is short by 9 days, and the clean database shows exactly which rows are missing. Spend, the calendar and the SQL views are unchanged. The model converged normally on the input it was given.

## Root cause
The Shopify orders load stopped after 2025-12-19, while ad spend loaded through 2025-12-28. The model input joins sales to spend through the sales CTE. One partial week (5/7 of sales, full spend) entered the fit, and one week silently disappeared. Nothing between check 02 and `fit_model.py` stopped the refresh, so the model was fitted on truncated data.

## Recommendation
- **Today (MMM analyst):** hold the scenario_C refresh and don't publish its ROAS or CAC. Ask the Shopify connector owner to backfill 2025-12-20 to 2025-12-28. Then rerun `check_data.py`, `fit_model.py` and `monitor.py`. Confirm that check 02 returns 0 rows and the model input has 156 weeks.
- **Fix (MMM analyst):** add a freshness gate in `fit_model.py` that refuses to fit when the sources' MAX(date) disagree or check 02 returns rows. This stops a bad fit before any number exists. Changing `weekly_model_input` to exclude incomplete trailing weeks would not do that. The refresh would still run, and the delay would be hidden.
- **Also:** compute `cac_spike` on complete weeks only, so it measures real CAC and doesn't react to partial weeks.

## Impact
From `run_roas.csv` and `run_metrics.csv`, scenario_C against baseline:
- Meta ROAS 2.3295 → 2.3792 (+2.1%). Google 2.1620 → 2.1790 (+0.8%). TikTok 1.7096 → 1.8205 (+6.5%). All three are inside baseline's 90% intervals. With one fit each, these moves can't be separated from sampling noise.
- Email: there is no valid ROAS comparison. Baseline does not measure email: its posterior/prior SD ratio is 0.967, above the 0.9 cutoff, so its ROAS there is mostly the prior. In scenario_C the ratio is 0.881, so email now counts as measured. A 9-day data change flipped the flag, which shows email sits right on the threshold. Under the borderline-band rule (0.85 to 0.90, logged in [configs/CHANGELOG.md](../configs/CHANGELOG.md)), email is not reported in either run.
- R2 0.9624 → 0.9419 (−0.0205). MAPE 0.0259 → 0.0282 (+0.0023). Both are under the alert thresholds of 0.05 and 0.02.
- CAC for week 2025-12-15 is 41.93 against 30.47 (+37.6%). The rule's latest-2-week CAC is 32.51, against 26.89 on baseline, but the two cover different weeks.

## Should the monitor have caught this sooner?
Check 02 did catch it on day one, and named the exact weeks. The gap is that nothing acted on that check before fitting. The model rules were the wrong layer to rely on. The fit drop, the ROAS shifts and the CAC rise were all too small to fire. The CAC rule missed by design, not by threshold. The dropped week moves its window back, and pooling dilutes the one short week. On complete weeks, CAC is flat (−9.3%), which is correct. The rule that would have prevented a bad fit is the freshness gate above.
