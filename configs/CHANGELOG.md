# Config changelog

One entry per promoted or rejected config. Numbers come from `results/<config>/diagnostics.json` and `results/<config>/estimates.csv`.

## baseline_v0 — REJECTED (2026-11-18)

Config: [baseline_v0.json](baseline_v0.json). Formerly `baseline.json`. Geometric adstock (l_max 8), Hill saturation, PyMC-Marketing default priors, target_accept 0.9.

Results: [results/baseline_v0/](../results/baseline_v0/)

Why rejected:

- **Sampler did not converge cleanly.** 225 divergences. Draws that hit max tree depth per chain: 306, 678, 556, 429. Max R-hat 1.0084 (saturation_beta) is under 1.01, but R-hat can't be trusted when the sampler diverges this often.
- **Implausible media credit.** Media contribution is $49,846,993 against total revenue of $31,780,424, which is a 156.9% media share. Media can't drive more revenue than the brand made. The decomposition shows how the model makes it add up: the intercept is negative, at −$125,348 per week (−$19,554,352 in total), and cancels the excess media credit. Controls add $1,492,694 and seasonality −$5,082. A brand with no marketing would still have positive sales, so the baseline can't be negative.
- **ROAS intervals too wide to use.** google 1.35 to 18.73 (width 12.9x its lower bound) and email 0.74 to 150.28 (202.8x). Both are over the 10x limit.
- Fit is good (R2 0.962, MAPE 2.6%), but a good fit with a bad decomposition is the usual sign that parameters are not identified, not that the model is right.

Next step: test candidate prior and sampler fixes. See the entries below.

## Candidate priors — set before fitting (2026-11-18)

Candidates: [hill_spendshare.json](hill_spendshare.json) (A), [logistic_spendshare.json](logistic_spendshare.json) (B), [v0_accept95.json](v0_accept95.json) (C, control: v0 with target_accept 0.95).

All prior numbers below come from `python src/prior_check.py configs/<name>.json` (2,000 prior draws, no MCMC), saved in `results/<name>/prior_check.json`.

**Why v0 failed at the prior level.** Before seeing revenue, the v0 default priors put the median media share of revenue at 239.2%, with a 94.9% chance of being above 80%. The intercept prior was Normal(0, 2), so a negative baseline was allowed.

**Intercept.** HalfNormal(1) on the scaled target in A and B. A brand with no marketing still has sales, so the baseline can't be negative.

**Channel beta: spend share, with a common scale.** sigma = 4 channels × spend share × `spend_share_scale`. With scale 1.0, the plain rule still gave a median prior media share of 261.2% (A) and 232.5% (B), because it splits the prior between channels but does not set its total. The scale is set so the prior gives about a 5% chance of media share above 80%, which matches the plausibility check: 0.13 for A (Hill) and 0.15 for B (logistic).

**Email floor.** `beta_floor_roas_95: {"email": 15}`. Email is an owned channel sent to existing customers, and CRM channels usually have the highest ROAS in a brand's mix. Without the floor ([hill_spendshare_nofloor.json](hill_spendshare_nofloor.json), prior check only), email's prior mean ceiling was $3,576 a week against $1,321.50 of average weekly spend. That is a maximum ROAS of 2.71 at the prior mean and 6.84 at the 95th percentile, which conflicts with what is known about the channel before seeing data. The floor raises email's sigma so its prior 95th-percentile ROAS at full saturation is about 15. This was set from domain knowledge, before any fit with these priors.

Resulting priors:

| | A hill_spendshare | B logistic_spendshare |
|---|---|---|
| beta sigma (meta, google, tiktok, email) | 0.2559, 0.1642, 0.0858, 0.0303 | 0.2953, 0.1895, 0.0990, 0.0303 |
| Prior ROAS at full saturation, 95th pct (meta, google, tiktok, email) | 6.85, 7.35, 6.75, 14.76 | 8.04, 7.90, 8.15, 14.79 |
| Prior media share, median (90% interval) | 34.9% (12.0% to 78.4%) | 35.9% (12.8% to 81.5%) |
| Prior P(media share > 80%) | 4.8% | 5.9% |
| Other changes | kappa HalfNormal(0.5): in v0, kappa's posterior matched its HalfNormal(1.5) prior (about 50% above the largest scaled spend), so the data could not inform it | Logistic saturation: 2 parameters per channel, default lam Gamma(3, 1) |

**Rule set before fitting: prior too tight.** If a channel's posterior median beta sits above its prior's 90th percentile, that channel's prior is flagged as too tight in the comparison. A flagged prior is not changed until the user has reviewed it.

## Candidate results (2026-11-18)

From `python src/compare_configs.py baseline_v0 v0_accept95 hill_spendshare logistic_spendshare`, saved in [results/comparison.csv](../results/comparison.csv) and [results/comparison_channels.csv](../results/comparison_channels.csv).

| | v0 | C v0_accept95 | A hill_spendshare | B logistic_spendshare |
|---|---|---|---|---|
| Divergences | 225 | 61 | 0 | 0 |
| Max tree depth hits (all chains) | 1,969 | 3,833 | 0 | 0 |
| Max R-hat | 1.0084 | 1.0206 | 1.0043 | 1.0032 |
| R2 / MAPE | 0.962 / 2.62% | 0.9621 / 2.61% | 0.9625 / 2.58% | 0.9624 / 2.59% |
| Media share of revenue | 156.9% | 166.2% | 56.2% | 53.2% |
| Intercept per week | −$125,348 | −$144,284 | $79,444 | $86,473 |
| Corr(intercept, media) | −0.9997 | −0.9997 | −0.989 | −0.9337 |
| Wide ROAS intervals | google, email | google, email | email | email |
| Trend gamma, mean (90% interval) | 0.0184 (−0.0176 to 0.0531) | 0.0179 (−0.0201 to 0.0541) | 0.0196 (−0.0166 to 0.0537) | 0.0143 (−0.0209 to 0.0475) |
| Sampling minutes | 3.8 | 5.8 | 1.1 | 1.4 |

### v0_accept95 (C) — REJECTED

Raising target_accept to 0.95 cut divergences from 225 to 61. Tree depth hits nearly doubled (1,969 to 3,833), max R-hat got worse (1.0206), and media share stayed implausible (166.2%). Smaller steps make the sampler more careful in a hard posterior but do not change the posterior itself. The problem was the priors, not the sampler.

### hill_spendshare (A) — NOT PROMOTED

Fixed convergence and plausibility. Not promoted because B is better on the same checks. Its ROAS intervals for paid channels are wider (width over lower bound 1.14 to 2.37, B: 0.57 to 0.98), and its paid-channel beta posteriors learned less from the data (posterior sd over prior sd 0.648 to 0.791, B: 0.195 to 0.434). Its intercept and media still trade off almost completely (corr −0.989).

### logistic_spendshare (B) — RECOMMENDED, pending user approval

Not yet promoted to `baseline.json`.

Findings that apply to both A and B:

- **Trend did not absorb the trade-off.** The trend coefficient is about the same in all four configs and its 90% interval includes zero in each. Its correlation with the intercept is small (−0.0512 in B). B has a moderate trend-media correlation (−0.3037), to watch but not a sign of the v0 problem.
- **Intercept and media are still correlated** (−0.9337 in B). The positive intercept and the media-share prior now bound the trade-off, but the data alone still separate baseline from media only partly. The media share is informed by both the data and the prior: the prior median was 35.9% and the posterior is 53.2%.
- **No channel's prior is too tight.** No posterior median beta sits above its prior's 90th percentile.
- **The data did not inform email.** In B, email's posterior sd is 0.968 of its prior sd and its median moved 0.05 prior sds. In A, the values are 1.026 and 0.21. Email's ROAS (B: 3.71, 90% interval 0.24 to 10.00) restates the prior, the 15x floor included. It is not a measurement. Report email as "not measured by the MMM" until a holdout or lift test gives evidence.

## baseline — PROMOTED (2026-11-18)

Config: [baseline.json](baseline.json). Approved by the user. A copy of `logistic_spendshare` (candidate B) with only `name` and `description` changed. Refit with the same seed. The results in [results/baseline/](../results/baseline/) match B exactly: 0 divergences, max R-hat 1.0032, R2 0.9624, MAPE 2.59%, media share 53.2%.

Reporting rule: email is reported as "not measured by the MMM (posterior = prior)", not as a ROAS number.

This entry and everything above it were written before any config was scored against the truth.

## Scored after decision (2026-11-18)

Moved to `data/truth/scored_decisions.md` (answer key: not for investigation sessions).

## Rule: measured channels (2026-11-18)

A channel counts as measured by the MMM only if posterior sd / prior sd of its beta is at or below 0.9. Above that, its posterior is mostly the prior, and its ROAS is reported as "not measured by the MMM (posterior = prior)". The threshold is set once, as `MEASURED_MAX_SD_RATIO` in [src/fit_model.py](../src/fit_model.py). `estimates.csv` has a `measured` column, which `results/comparison_channels.csv` and the truth scores in `data/truth/scores/` carry through.

Set after the baseline decision. It does not change that decision.

- **Baseline:** meta, google and tiktok are measured (0.195, 0.348, 0.433). Email is not (0.967).
- **The ratio is now computed in `fit_model.py` from the unrounded prior sd.** This changes the third decimal for two baseline channels compared with the candidate results above: email 0.968 to 0.967, tiktok 0.434 to 0.433. No measured verdict changes.
- **Limit: the rule is relative to the prior.** In v0 and v0_accept95, email counts as measured (0.455 and 0.559), because their default prior was so wide that almost any data narrows it. "Measured" means the data moved the estimate, not that the estimate is plausible. Read it together with the plausibility checks.

Existing runs were updated with `python src/fit_model.py configs/<name>.json --estimates-only`, which rebuilds `estimates.csv` from the saved model without resampling. Their ROAS columns are unchanged.

## Rule: borderline band for reported ROAS (2026-11-18)

A channel whose posterior sd / prior sd of beta is above 0.85 and at or below 0.90 still counts as measured, so the monitor's ROAS rule compares it. Its ROAS is not reported. It is shown as "borderline, not reported". The cutoff is `REPORTED_MAX_SD_RATIO` in [src/fit_model.py](../src/fit_model.py), and `estimates.csv` has a new `reported` column.

Why: in alert A003 ([alerts/C_shopify_truncated.md](../alerts/C_shopify_truncated.md)), email's ratio went from 0.967 on baseline to 0.881 on scenario_C. The only data change was 9 missing days of Shopify sales. That flipped email from not measured to measured. A verdict that flips on a change this small is not stable enough to report a ROAS from.

- Existing runs were updated with `--estimates-only`. All existing columns in all 10 runs are unchanged.
- The only channel in the band in any run is email in scenario_C (0.881). Baseline verdicts are unchanged: meta, google and tiktok are reported, and email is not measured.
- The monitor still uses `measured`, not `reported`.

## Monitor v2 (2026-11-18)

Code: [src/monitor_v2.py](../src/monitor_v2.py). Monitor v1 ([src/monitor.py](../src/monitor.py)) is unchanged. v2 has three tiers. Gates run on the database and config before fitting, and any gate blocks the fit. Alerts run on the fitted model. Watch rules are computed and shown in every report but never block or alert.

**Evidence base, and its limits.** The clean-run evidence is 3 extra seeds of the baseline config on one clean database, plus one refresh test (baseline refitted on its history minus the last 4 weeks, compared on the 152 shared weeks). The gates pass the clean runs partly because their data equals the approved snapshot by construction. A production system would recalibrate every threshold on real monthly runs. Saved outputs: `results/monitor_v2_scorecard.csv`, `results/monitor_v2_calibration.csv`, `results/monitor_v2_refresh_test.csv`, `results/monitor_v2_rejected_cac.csv`.

Result: all 3 clean seeds give 0 gates and 0 alerts. All five scenarios are caught before fitting. Monitor v1 raised nothing on scenario A.

### Gates (pre-fit)

| Gate | Rule | Motivated by | Fires on | Clean seeds |
|---|---|---|---|---|
| freshness | sources' MAX(date) agree, and the latest week has 7 days in both | C ([note](../alerts/C_shopify_truncated.md)) | C: ad spend to 2025-12-28, sales to 2025-12-19 | 0 |
| reconciliation | raw spend total = model-input spend total | B ([note](../alerts/B_meta_campaign_unmapped.md)) | B: gap 197,345.86. C: gap 42,774.44 (a week with spend but no sales drops out of the model input) | 0 |
| new_campaigns | every campaign_id was in the last approved snapshot | B | B: 105 META_AdvantagePlus_Shopping → social | 0 |
| calendar | every approved promo or holiday row is unchanged | A ([note](../alerts/A_spring_promo_missing.md)) | A: promo 10 SPRING25 missing | 0 |
| spec | config matches the live config (ignoring name, description and database). Otherwise it needs a changelog heading naming the config AND a prior check with P(prior media share > 80%) ≤ 10% | E ([note](../alerts/E_lam_prior_edit.md)) | E: lam prior changed, no changelog entry, prior P(> 80%) 41.6% | 0 |
| rows_absent | check 03 rows where a launched channel has no raw rows for a week | D ([note](../alerts/D_tiktok_feed_gap.md)) | D: TikTok 2025-06-16, 06-23, 06-30 | 0 |

- **Prior-check limit:** 10%. The live baseline gives 5.85% (`results/baseline/prior_check.json`), and its priors were set to give about 5%. E gives 41.6% (`results/scenario_E/prior_check.json`).
- **Spec compares config files, not the saved model spec.** The beta prior's sigma is computed from each channel's spend share, so it changes with any spend change. A saved-spec diff would fire on every data fault, not only on config edits.
- **Check 03 is now split.** `sql/checks/03_channel_zero_weeks.sql` labels each row 'rows absent' or 'spend zero'. 'Rows absent' is pure data, so it became a gate, which moved D from caught-after-fit to caught-before-fit.

### Alerts (post-fit)

| Alert | Rule | Motivated by | Fires on | Clean seeds |
|---|---|---|---|---|
| roas_shift | as v1: measured channel, > 25% and outside baseline's 90% interval | v1 | B: TikTok 1.7096 → 0.7851 | 0 |
| control_shift | a control coefficient's 90% interval stops overlapping baseline's | B | B: trend 0.0143 → 0.0878 | 0 |
| convergence | divergences > 8, or max R-hat > 1.01 | D, E | E: 14. D's 2 does not fire | 0 (max 4, seed 7) |
| spend_zero | check 03 rows with raw rows present but zero spend | D (split) | none | 0 |

- **Convergence threshold:** v1 fired on any divergence. Clean seeds give 0, 1 and 4 (`monitor_v2_calibration.csv`). The threshold is 2x the clean maximum. D's divergences were shown to be noise, and E's were not.
- **Control shift misses A.** The promo coefficient held (0.5985 → 0.5996, `scenario_A/run_params.csv`) because it is estimated from the other 12 promos. A is caught by the calendar gate.

### Watch (shown, never blocking or alerting)

Provisional, calibrated on 1 refresh sample. Recalibrate after 3 real monthly runs.

| Watch rule | Threshold | Clean seeds max | Normal refresh | A / B / C / D / E |
|---|---|---|---|---|
| param_shift: largest move in a media parameter's mean, in baseline posterior sds | 0.70 | 0.062 | 0.350 | 6.46 / 1.64 / 0.87 / 1.70 / 15.61 |
| residual_shift: largest change in a week's residual against baseline, in points | 3.2 | 0.329 | 1.60 | 12.65 / 4.78 / 26.06 / 7.72 / 0.91 |

- **Seed-based thresholds were rejected.** 2x the clean-seed maximum (0.13 sd, 0.7 pts) would fire on every normal month: a refresh moves parameters 5.7 times and residuals 4.9 times as much as the worst seed. Thresholds are set at 2x the refresh value instead.
- **Residual shift cannot separate E from a normal month** (0.91 against 1.60 pts). E is caught by the spec gate and the convergence alert.
- **Rejected option: compare only weeks older than the latest 4–8.** The refresh's largest residual move is in an old week (2023-12-25), so it stays at 1.60 with any exclusion. Excluding the latest 4 weeks erases C's signal (26.06 → 2.11).
- **Parameter shift separates all five scenarios** from the refresh, but C's margin is thin (0.87 against 0.350).

### Rejected: two-way CAC

Proposed in B, where CAC from 2025-09-01 read 16.8% low against baseline. As a rule it compares the latest 2 complete weeks with the 12 before, within the run. It reads −14.15% on every clean run (December seasonality) and −13.12% on B, so it cannot see B, and it fires on no run (`results/monitor_v2_rejected_cac.csv`). A CAC rule would need to compare against the last approved run for the same weeks. That is close to residual shift, so no separate rule was added.

### PROPOSED, not built: sales_channel_gaps gate (2026-11-18)

**What F revealed.** F was an out-of-sample fault, not seen when v2 was designed ([note](../alerts/F_tiktok_shop_feed_stopped.md)). The TikTok Shop sales feed stopped on 2025-10-05 while the online store feed continued to 2025-12-28. No gate fired: they all check a source as a whole, and the online store kept MAX(date) and the 7-day counts normal. `rows_absent` covers ad channels only. v2 caught F only after fitting: a ROAS shift alert (TikTok 1.7096 → 2.4523) plus the param shift watch (1.11 sd).

**Rule.** From each sales channel's first sale, every week in dim_date must have 7 days of rows. This is the sales-side twin of `rows_absent`. Query: [sql/investigations/proposed_gate_sales_channel_gaps.sql](../sql/investigations/proposed_gate_sales_channel_gaps.sql). It runs on DuckDB and SQLite.

**Evidence** ([src/proposed_gate_test.py](../src/proposed_gate_test.py), `results/investigations/scenario_F/proposed_gate_test.csv`):
- Clean database: 0 rows. The 3 clean seed runs share this database, so this is one data test, not three.
- F: 12 rows (tiktok_shop, every week from 2025-10-06).
- C: 4 rows (online_store and tiktok_shop from 2025-12-15). The freshness gate already blocks C.
- A, B, D, E: 0 rows.

**Status.** Left unbuilt as a documented gap. It is not in `monitor_v2.py`, so v2 still catches a stopped sales sub-feed only after fitting. A real channel closure would also fire it, and that would need a sign-off.
