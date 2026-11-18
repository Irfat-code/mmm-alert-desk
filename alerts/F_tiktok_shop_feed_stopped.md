# Alert A007: TikTok ROAS jumped 43% after the TikTok Shop sales feed stopped (scenario_F)
Raised: 2026-11-18  |  Triage done: 2026-11-18  |  Resolved: open, waiting on a feed re-pull and refit

**Bottom line.** The TikTok Shop sales feed stopped on 2025-10-05, but the online store feed kept going, so every pre-fit gate passed. The model read the missing revenue as slower growth and moved credit from the trend to TikTok and Meta. Don't use this run. Re-pull the feed and refit.

## Symptom
A007 `roas_shift`: TikTok 1.7096 → 2.4523, outside baseline's 90% interval (1.1621–2.2990). No gate fired. Watch: `saturation_beta:tiktok` moved 1.11 sd (threshold 0.70). 0 divergences, max R-hat 1.0022, MAPE 0.0259 in both runs (`monitor_v2_scorecard.csv`, `run_metrics.csv`).

## Hypotheses (ranked before any test)
1. **Rejected:** a control input changed in a way the calendar gate can't see. Test: calendars in F, then diff against the snapshot.
2. **Confirmed:** sales changed in some weeks, since total revenue fell. Test: coverage per sales channel, then diff against the snapshot.
3. **Rejected:** TikTok spend moved between weeks with its total unchanged. Test: weekly spend diff.
4. **Rejected:** a logged config change passed the spec gate. Test: saved model spec against baseline's.

## Evidence
Outputs are in [results/investigations/scenario_F/](../results/investigations/scenario_F/). Queries are in [sql/investigations/scenario_F.sql](../sql/investigations/scenario_F.sql).
- **F alone** (`source_coverage`, `tiktok_shop_vs_spend`): every source runs to 2025-12-28 except `tiktok_shop`, which ends on 2025-10-05. That leaves 12 weeks of TikTok spend with 0 TikTok Shop days. The shop sold 11,562 in its last week, so this is a feed stop, not a fade-out.
- **Where the credit went** (`component_credit.csv`): the trend fell from +371,329 to −717,256. TikTok gained +936,807, and +823,871 of that is in the weeks *before* the gap. Meta gained +674,518. Promo and holiday credit each moved by less than 2,500.
- **Snapshot** (`table_diff`, `channel_week_diff`, `model_input_full_diff`): the only difference is 84 TikTok Shop rows from 2025-10-06 to 2025-12-28, worth 128,582.80. The spec differs only in email's beta sigma, which is computed from the target scale (`model_spec_diff`).
- **Fix and refit** ([src/fix_feed_test.py](../src/fix_feed_test.py), `scenario_F_fixfeed/`): restoring only those rows makes the model input match the clean database. The refit gives TikTok 1.7096, Meta 2.3295 and Google 2.1620, the same as baseline.

## Classification
DATA. The model and config are unchanged. One sub-feed is missing 12 weeks, and restoring it alone restores every estimate.

## Root cause
The TikTok Shop export stopped on 2025-10-05 while the online store export continued. The last 12 weeks lost about 3–5% of revenue each. The model fitted a flatter trend and gave the leftover growth to channels whose spend grew over the period, mainly TikTok. The fit stayed good, so the residual checks barely moved.

## Recommendation
- **Today:** data engineering re-pulls TikTok Shop orders from 2025-10-06. The MMM analyst then reruns `check_data.py`, refits and reruns `monitor_v2.py scorecard`, and expects TikTok ROAS 1.7096.
- **Why no gate caught it:** the gates check each source as a whole, never each sales channel. The online store kept the latest date and the day counts complete.
- **Proposed gate `sales_channel_gaps`** (not built): every week from a sales channel's first sale must have 7 days of rows ([query](../sql/investigations/proposed_gate_sales_channel_gaps.sql)). It fires on F and returns 0 rows on the clean database the 3 seeds share (`proposed_gate_test.csv`).

## Impact
- **TikTok ROAS** overstated by 43.4% (1.7096 → 2.4523). **Meta** +7.7% (2.3295 → 2.5088), inside baseline's interval. Google −1.3%. Media share rose from 53.2% to 58.3% (`run_roas.csv`, `run_metrics.csv`).
- **Blended CAC** in the 12 gap weeks overstated by 7.9% (31.18 → 33.64), because 2,040 new customers were missing (`cac_impact_diff.csv`).
