# Alert A005 + A004: TikTok spend missing for 3 weeks in June 2025 (scenario_D)
Raised: 2026-11-18  |  Triage done: 2026-11-18  |  Resolved: A004 closed as sampler noise; A005 open, waiting on re-pull

**Bottom line.** TikTok's ad spend for 16 June to 6 July 2025 never loaded, but the sales it drove did. The model now rates TikTok about 13% lower and much less precisely. Cost per new customer for those weeks reads 31% too low. Hold TikTok budget decisions from this model until the missing weeks are reloaded and the model rerun.

## Symptom
- A005 `data_check rows:03_channel_zero_weeks`: 3 rows, against 0 on baseline. TikTok shows zero spend in weeks 2025-06-16, 06-23 and 06-30.
- A004 `convergence divergences`: 2, against 0 on baseline. The threshold is 0. Max R-hat is 1.0032, the same as baseline.

## Hypotheses
1. **Supported:** a broken TikTok feed (DATA). Tested with check 03 detail, raw rows and sales in those weeks.
2. **Rejected:** a real 3-week pause. Same tests.
3. **Rejected:** the gap distorts TikTok's geometry and causes the divergences. Tested with where the divergent draws sit, and one extra seed per run.

## Evidence
Queries: [sql/investigations/scenario_D.sql](../sql/investigations/scenario_D.sql). Scripts: `run_investigation.py`, `compare_runs.py`, `divergence_check.py`, `seed_check.py`. Outputs: [results/investigations/scenario_D/](../results/investigations/scenario_D/).
- **What an analyst sees without a clean copy** (`gap_vs_neighbours`): TikTok spend went from 24,419 a week to 0 and back to 21,624. TikTok Shop revenue barely moved: 12,386 a week in the gap, against 13,305 before and 12,668 after. All three TikTok campaigns vanish together, on exact week boundaries. A real pause rarely stops every campaign on a Monday and leaves sales intact. A connector outage does exactly that.
- **Confirmation, the equivalent of re-pulling those weeks from TikTok Ads Manager** (`channel_week_diff`): the clean copy has 21 rows a week in those weeks, across 3 campaigns and 7 days, with 1.7M to 2.6M impressions and 13,587 to 19,249 of spend. Scenario_D has no rows at all, absent rather than zeroed. Nothing else in raw spend differs, and sales match in every week (`sales_week_diff`, 0 rows).
- **Divergences** (`divergence_summary`, `seed_check`): both divergent draws are in chain 3, at draws 185 and 857. No parameter has both draws in its outer 10%. TikTok's alpha sits near the 16th percentile in both, not in the high-carryover region. With one extra seed each, D gave 1 divergence and the clean baseline also gave 1.

## Classification
- **A005: DATA.** TikTok spend rows are missing for three full weeks, while the sales they drove are present.
- **A004: not a fault.** It is sampler noise at the 1–2 per 4,000 draws level. The clean data produces it too, and the draws show no shared region. The evidence is one extra seed each, so confidence is moderate, and the priority is low.

## Root cause
The TikTok Ads export returned no rows for 2025-06-16 to 2025-07-06, across all three campaigns. The model saw TikTok at zero while TikTok-driven sales continued, so it loosened TikTok's estimate and lengthened its carryover to explain the sales.

## Recommendation
- **Today (MMM analyst):** re-pull 2025-06-16 to 2025-07-06 from TikTok Ads Manager, and ask the TikTok connector owner to backfill `raw_ad_spend`. Then rerun `check_data.py`, `fit_model.py configs/scenario_D.json` and `monitor.py`. Confirm that check 03 returns 0 rows.
- **A004:** no action beyond the v2 rule review below.

## Impact
- TikTok ROAS 1.7096 → 1.4832 (−13.2%), inside baseline's interval, so no ROAS alert fired. The 90% interval widened from 1.16–2.30 to 0.72–2.41, and the SD ratio went from 0.433 to 0.743. The extra seed gave the same result (1.4798), so this is the data, not sampling.
- Google ROAS 2.1620 → 2.3372 (+8.1%). Email is not measured.
- **Business risk, untested:** TikTok's adstock alpha rose from 0.28 to 0.50 (0.50 under the extra seed too). If that stays, any budget plan built on this model would overvalue TikTok's delayed effect.
- CAC for the 3 gap weeks reads 20.78 instead of 30.11 (−31.0%). The latest weeks are unaffected, so no CAC rule sees it.

## Monitor: candidate rules for v2
Candidates only. All v2 rules will be decided together after scenario A.
- **Convergence tolerance:** the clean baseline gave 1 divergence under a second seed, so "any divergence" fires on noise. Consider firing above a small count, or only when divergences persist across seeds.
- **Check 03 refinement:** report "rows absent" separately from "spend zero". Here that would have pointed to a feed gap straight away.
