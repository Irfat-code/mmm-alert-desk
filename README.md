# MMM Alert Desk

A working simulation of the marketing mix modelling (MMM) analyst job. I built a Bayesian MMM for a fictional DTC skincare brand, broke its data in realistic ways, and investigated each alert the way I would in production: hypothesis, evidence, classification (data problem or model problem), recommendation.

The data is synthetic on purpose. I set each channel's true ROAS, adstock decay and saturation curve, so every model result and every investigation can be checked against the real answer instead of just argued for.

## Scoreboard (scored against the answer key: not for investigation sessions)

| | |
|---|---|
| Alerts investigated | 7 alerts on 5 runs, plus 1 monthly review with no alert: 6 scenarios ([alerts/queue.csv](alerts/queue.csv)) |
| Correctly classified (data vs model) | 6 of 6 (`data/truth/scores/scenarios.csv`) |
| Caught by monitor v1 | 5 of 6. It missed the missing promo (scenario A) |
| Caught by monitor v2 | 6 of 6 detected, 5 before fitting ([results/monitor_v2_scorecard.csv](results/monitor_v2_scorecard.csv)). Scenario F, the out-of-sample test, was caught after fitting |
| Recovered ROAS vs true ROAS (baseline) | In `data/truth/scored_decisions.md`, kept out of investigation sessions |

## Investigations

| Scenario | What fired | Classification | Note |
|---|---|---|---|
| A | nothing (monthly review: ROAS moved under the 25% threshold) | DATA: spring sale missing from the promo calendar | [A_spring_promo_missing.md](alerts/A_spring_promo_missing.md) |
| B | A001 TikTok ROAS shift, A002 unexpected channel | DATA: relaunched Meta campaign mapped to "social"; the TikTok alert was a model-side effect | [B_meta_campaign_unmapped.md](alerts/B_meta_campaign_unmapped.md) |
| C | A003 incomplete weeks | DATA: Shopify orders stopped 9 days before ad spend | [C_shopify_truncated.md](alerts/C_shopify_truncated.md) |
| D | A004 divergences, A005 zero-spend weeks | DATA: TikTok feed missing 3 weeks; the divergences were sampler noise | [D_tiktok_feed_gap.md](alerts/D_tiktok_feed_gap.md) |
| E | A006 divergences | MODEL: undocumented change to the saturation prior | [E_lam_prior_edit.md](alerts/E_lam_prior_edit.md) |
| F | A007 TikTok ROAS shift | DATA: TikTok Shop sales feed stopped 12 weeks early | [F_tiktok_shop_feed_stopped.md](alerts/F_tiktok_shop_feed_stopped.md) |

Each note leads with what an analyst could see from the faulty run alone, and uses the clean database only as the confirmation step. The investigations never read the answer key.

## Monitor v1 vs v2

| Scenario | Monitor v1 | Monitor v2 | Caught |
|---|---|---|---|
| A | missed | calendar gate | before fit |
| B | ROAS shift, check 01 | reconciliation and new-campaign gates | before fit |
| C | check 02 (but the model was still fitted) | freshness and reconciliation gates | before fit |
| D | convergence, check 03 | rows-absent gate | before fit |
| E | convergence | spec gate (no changelog entry, prior check failed) | before fit |
| F | ROAS shift | ROAS shift alert, param shift watch; no gate | after fit |

v2 has three tiers. **Gates** run before fitting and block the fit. **Alerts** run on the fitted model. **Watch** rules (parameter shift, residual shift) are shown in every report but never block or alert, because their thresholds rest on one refresh sample. Every rule, the scenario that motivated it, its clean-run evidence and the rejected options are in [configs/CHANGELOG.md](configs/CHANGELOG.md).

## Out-of-sample test

Monitor v2 was designed after seeing faults A–E. To test it on a fault it was not built for, an unseen fault (scenario F) was picked at random from a list the investigating session never saw.

- **Detection:** no pre-fit gate blocked it. After fitting, monitor v2 raised a ROAS shift alert (TikTok 1.7096 → 2.4523), and the param shift watch flagged TikTok's beta (1.11 sd).
- **Blind classification:** DATA, from the scenario database, the results and the alert queue only. The TikTok Shop sales feed stopped on 2025-10-05 while the online store feed continued. A fix-and-refit test restored baseline ROAS exactly. The answer key agrees (`data/truth/scores/scenarios.csv`).
- **Impact:** TikTok ROAS overstated by 43.4%. The model read 12 weeks of missing revenue as slower growth and moved credit from the trend to TikTok.
- **Why the gates missed it:** they check each source as a whole, not each sales channel.
- **Documented gap, left unbuilt:** a proposed `sales_channel_gaps` gate requires every week from a sales channel's first sale to have 7 days of rows ([query](sql/investigations/proposed_gate_sales_channel_gaps.sql)). It fires on F and returns 0 rows on the clean database the 3 seed runs share ([results/investigations/scenario_F/proposed_gate_test.csv](results/investigations/scenario_F/proposed_gate_test.csv)). It is not in monitor v2, so v2 still catches this fault only after fitting.

## The brand

**Loma Skin** sells skincare on Shopify and, from March 2024, TikTok Shop. 3 years of weekly data (Jan 2023 to Dec 2025), four paid channels:

| Channel | 3-yr spend | Notes |
|---|---|---|
| Meta | $3.76M | biggest budget |
| Google | $2.41M | search, PMax, some YouTube |
| TikTok | $1.26M | launched mid-2023, ramps up |
| Email/SMS | $0.21M | Klaviyo, small spend |

True ROAS, marginal ROAS, carryover and the revenue split per channel are in `data/truth/scored_decisions.md`, kept out of the README so investigations stay blind.

Revenue also moves with holiday weeks (Black Friday, Cyber Monday, Mother's Day, Valentine's, a Christmas dip) and about 4 sitewide promos a year.

## How it's built

```
data/                      clean database, data/scenarios/ (one faulty copy per scenario),
                           data/truth/ (the answer key and all scores; investigations never read it)
sql/schema.sql             raw source tables: ad spend by campaign, campaign map, Shopify orders, calendars
sql/views/                 weekly_model_input: the one table the model is fitted on
sql/checks/                data quality queries (unmapped spend, incomplete weeks, zero/absent weeks)
sql/investigations/        the queries behind each investigation note
src/                       generator, model, monitors (v1 and v2), investigation and scoring scripts
alerts/                    alert queue and one investigation note per scenario
configs/                   model configurations + CHANGELOG.md
results/                   fitted runs, results/investigations/<scenario>/, monitor v2 outputs
notebooks/                 stakeholder_summary.ipynb, for the marketing team
```

Raw data is daily and at campaign level, the way it lands from Meta, Google Ads, TikTok, Klaviyo and Shopify. SQL rolls it up to weekly channel totals through a hand-maintained campaign map, which is where many real MMM data problems start.

## Run it

```bash
pip install -r requirements.txt
python src/generate_data.py   # builds data/alert_desk.duckdb and data/truth/
python src/check_data.py      # reconciles SQL output against the truth, runs the data checks
python src/fit_model.py configs/baseline.json   # fits the MMM; reads only the model input view
python src/score_against_truth.py baseline      # the only step that opens the answer key; writes data/truth/scores/baseline.csv
```

Each model configuration lives in `configs/` as a JSON file, and its results go to `results/<name>/`: ROAS estimates, weekly fit, and diagnostics (convergence, plausibility, revenue decomposition).

To test a new configuration:

```bash
python src/prior_check.py configs/<name>.json   # what the priors imply before seeing revenue (no MCMC)
python src/fit_model.py configs/<name>.json     # add --seed N to refit with another sampler seed
python src/identification_check.py <name>       # did the data inform the parameters?
python src/compare_configs.py baseline <name>   # side by side, incl. prior vs posterior per channel
```

To check runs and raise alerts:

```bash
python src/monitor.py <run>                    # v1: adds alerts to alerts/queue.csv
python src/monitor_v2.py scorecard             # v2: gates, alerts and watch rules for every run
python src/monitor_v2.py calibrate             # clean-seed values behind the thresholds
python src/monitor_v2.py refresh               # normal-refresh test for the watch rules
```

To investigate a scenario, and to score the investigations afterwards:

```bash
python src/run_investigation.py <scenario> --full   # checks, table diffs, sql/investigations/<scenario>.sql
python src/compare_runs.py <scenario>               # ROAS, parameters, decomposition vs baseline
python src/score_scenarios.py                       # scoring only: compares each note with the answer key
```

To rebuild the stakeholder notebook: `python -m ipykernel install --sys-prefix --name mmm-venv`, then `python src/build_stakeholder_notebook.py`.

Without DuckDB installed it falls back to SQLite, and all the SQL runs on both.

## Baseline model

`configs/baseline.json`: geometric adstock, logistic saturation, a positive intercept, and channel priors scaled to spend share. Email's prior has a floor based on domain knowledge. The first baseline was rejected because it credited media with 157% of revenue. [configs/CHANGELOG.md](configs/CHANGELOG.md) records why each config was rejected or promoted. How the decision scored against the truth afterwards is in `data/truth/scored_decisions.md`.

| Channel | ROAS (90% interval) |
|---|---|
| Meta | 2.33 (1.83 to 2.87) |
| Google | 2.16 (1.58 to 2.84) |
| TikTok | 1.71 (1.16 to 2.30) |
| Email/SMS | not measured by the MMM (posterior = prior) |

Media is credited with 53.2% of revenue. The data did not move email's estimate away from its prior, so a lift test is the way to measure it. The marketing-facing version, with response curves and next-dollar returns, is [notebooks/stakeholder_summary.ipynb](notebooks/stakeholder_summary.ipynb).

## Limitations

- **One clean database.** The clean-run evidence for monitor v2 is 3 extra sampler seeds on that database plus 1 refresh test. The gates pass the clean runs partly because their data equals the approved snapshot by construction. A production system would recalibrate every threshold on real monthly runs.
- **The watch thresholds are provisional.** They rest on 1 refresh sample. Recalibrate after 3 real monthly runs. Residual shift cannot separate scenario E from a normal month.
- **Monitor v2 was designed after seeing faults A–E**, so its gate coverage of those five is in-sample. One out-of-sample fault (F) is a single test: v2 detected it, but only after fitting.
- **Email is not measured.** Its posterior sd is 0.967 of its prior sd. Its ROAS restates the prior, so it is not reported.
- **Meta vs Google ranking.** The spend-share prior gives the biggest budget the biggest prior effect, and the two channels' intervals overlap heavily. The data does not establish which returns more. How this scored is in `data/truth/scored_decisions.md`.
- **Faults were injected one at a time.** Real months can combine them.

## Validating AI-generated analysis

I used Claude Code for most of the build and investigations, and a separate Claude chat to review its work. I treated both as fallible. 

A few rules guided the process: every number had to come from a saved output, investigations couldn't access the answer key, and I wouldn't accept a proposed cause until a fix-and-refit test showed that it was actually responsible..

Where AI output was wrong or vague, and how it was caught:
- Scenario B: The reviewing AI suggested that the TikTok alert was caused by Meta and TikTok spend moving together. I tested this, and the correlation was weak (0.23 for spend and 0.07 for posterior). The actual issue was that the trend control was absorbing the credit.
- Scenario E: The reviewer expected the bad prior to reduce paid channels' marginal ROAS. The actual values barely moved, by about 1%. The bigger impact was on email.
- Scenario A: The reviewer initially misunderstood how the model handled the missing promo. It had to revisit its explanation after I provided the week-by-week evidence.
- Email prior: Claude Code described email's ROAS cap as being in the single digits. When I checked the saved prior, it was closer to 2.7 at the prior mean. That was a much tighter limit, so I set a floor before fitting the model rather than adjusting it after seeing the results.
- A refit error: Claude Code also caught a mistake in its own work. A chained command had refitted an unfixed copy of the data. I added a check to the script so it would refuse to run unless the input data was correct.
- Scenario F: Claude Code refused to investigate this scenario in the same session that built it because it had already seen the fault list. That would have made the investigation less independent. I moved it to a fresh session instead.

The main lesson for me was that an AI-generated explanation isn't the same as a verified result. I still had to check the numbers, question the explanations, and test whether the proposed fixes actually changed the outcome.

## What the data design expected vs what happened

- Missing promo (A): the data was designed so a deleted promo would make the model over-credit Meta, which was pushed hard in the same weeks. It did, but in the response curve (marginal ROAS +13.9%), while average ROAS fell 11.3%. A report based on average ROAS alone would have pointed the wrong way.
- Bad prior (E): designed as a saturation prior error for all channels. The data overruled it for the paid channels. Only email, which the data can't measure, was badly affected.
- Default model (v0): the library defaults let the model credit media with 157% of revenue despite an excellent fit (R2 0.96). Good fit did not mean correct attribution.

## Status

- [x] Data generator with known ground truth
- [x] Database, model input view, data quality checks
- [x] Baseline Bayesian MMM (PyMC-Marketing) and ROAS recovery check
- [x] Alerts: broken TikTok feed, Meta campaign relabelled to "social", reporting delay, missing promo flag, badly set saturation prior, stopped TikTok Shop sales feed (out-of-sample)
- [x] Configuration comparisons and changelog
- [x] Monitor v2: pre-fit gates, post-fit alerts, watch tier
- [x] Stakeholder notebook
- [x] Checking AI-generated analysis against the data
