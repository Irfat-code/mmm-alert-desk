# Alert A001 + A002: Relaunched Meta campaign mislabelled, so TikTok looked half as effective (scenario_B)
Raised: 2026-11-18  |  Triage done: 2026-11-18  |  Resolved: open, fix verified on a copy, waiting on map change

**Bottom line.** A relaunched Meta campaign was given the wrong label, so about $197K of Meta spend never reached the model. As a result, TikTok looked half as effective as it is, and Meta's effect was understated. Cost per new customer since September also reads 17% too low. Neither ROAS reading, and no CAC since September, should drive budget decisions until the label is fixed and the model rerun.

## Symptom
- A001 `roas_shift roas_mean:tiktok`: TikTok mean ROAS fell from 1.7096 to 0.7851. That is −54.1%, outside baseline's 90% interval of 1.1621 to 2.2990.
- A002 `data_check rows:01_unexpected_channels`: 1 row, against 0 on baseline.

The alert fired on the wrong channel. TikTok's spend is identical to baseline in every week.

## Hypotheses
1. **Confirmed:** one mapping fault behind both alerts (check 01 detail, map diff, weekly spend). The spend is Meta's. TikTok's data and mapping are unchanged.
2. **Rejected:** a knock-on through Meta–TikTok collinearity. Spend correlation is 0.23 and posterior beta correlation 0.07 in baseline, both lower in B.

## Evidence
Queries: [sql/investigations/scenario_B.sql](../sql/investigations/scenario_B.sql). Scripts: `run_investigation.py`, `compare_runs.py`, `credit_check.py`, `fix_mapping_test.py`. Outputs: [results/investigations/scenario_B/](../results/investigations/scenario_B/).
- **Check 01:** campaign 105 `META_AdvantagePlus_Shopping`, platform meta, is mapped to `social`. It spent 197,345.86 between 2025-09-01 and 2025-12-28.
- **Campaign map:** campaign 104, same name and mapped to meta, fell by exactly that amount (822,814.77 → 625,468.91). Total raw spend is unchanged at 7,641,355.20. This is a relaunch under a new ID.
- **Model spend:** Meta is −197,345.86 (−5.2%), spread over 17 weeks from 2025-09-01 to 2025-12-22, and −36.5% within those weeks. Google, TikTok and email are unchanged.
- **Where the credit went:** media fell from 16,898,311 to 14,009,738, and its share from 53.2% to 44.1%. Controls rose from 1,397,787 to 3,331,440, and the intercept from 13,489,821 to 14,445,026. Of the controls, only trend moved: 1.11 → 6.81 in scaled units.
- **Causal test:** in a copy of B with only campaign 105 remapped to meta, every model-input column matched baseline in all 156 weeks. Refitting it with the baseline config, and again with the scenario_B config, reproduced baseline exactly. Every ROAS changed by 0.0, and R2, MAPE and the decomposition were identical.
- **Not used:** the truth-scored section of `configs/CHANGELOG.md`. It was seen while checking the changelog format and played no part in this investigation.

## Classification
DATA root cause, with a MODEL-side effect. The fault is one wrong row in `campaign_channel_map`. The model behaved as designed on the input it got, and fixing the input alone removes the alert.

## Root cause
Meta relaunched AdvantagePlus Shopping under campaign ID 105 from 2025-09-01. The new ID was mapped to `social`, a label outside the four model channels, so its spend dropped out of `weekly_model_input`. **Mechanism, well supported but not separately proven:** with that spend gone, Meta's spend no longer rises over time (corr with time 0.21 → −0.02), but revenue still does. The model explains the growth with the trend control instead. The trend coefficient moved from 0.0143 (90%: −0.021 to 0.047) to 0.0878 (0.057 to 0.117), and the intervals don't overlap. TikTok's spend tracks time more closely than any other channel (corr 0.85), so it loses the most credit to trend. It loses it in every week, not only the affected ones: its contribution per week fell from 12,569 to 5,726 before September.

## Recommendation
- **Today (MMM analyst):** remap campaign 105 to meta in `campaign_channel_map`. Rerun `check_data.py`, `fit_model.py configs/scenario_B.json` and `monitor.py`. Confirm that check 01 returns 0 rows and TikTok is back at 1.7096, as the fix test showed.
- **Prevention (whoever maintains the map, with the MMM analyst):** every new campaign_id must be reviewed and mapped before the next refresh. Relaunches keep their channel. A new ID is not a new channel.
- **Gate (MMM analyst):** `fit_model.py` should refuse to fit when raw spend and model-input spend differ (gap 197,345.86 here, 0 on baseline). This is broader than check 01. It also catches spend lost or doubled by routes check 01 can't see, such as dates outside `dim_date` or a campaign mapped twice.

## Impact
- TikTok ROAS 1.7096 → 0.7851 (−54.1%).
- Meta ROAS 2.3295 → 1.9957 (−14.3%). It didn't alert: the shift was under 25%, and the new mean was inside baseline's interval.
- Google ROAS 2.1620 → 2.1383 (−1.1%). Email is not measured in either run.
- CAC from 2025-09-01 reads 25.73 instead of 30.91 (−16.8%). The latest 2 weeks read 22.51 instead of 26.89 (−16.3%). The `cac_spike` rule only looks for rises, so it can't see this.
- R2 0.9624 → 0.9501 and MAPE 2.59% → 2.96%, both under the alert thresholds.

## Monitor: candidate rules for v2
Candidates only. All v2 rules will be decided together after scenario A.
- **Control shift:** fire when a control's coefficient 90% interval stops overlapping baseline's. Trend would have fired here (0.0143 → 0.0878), pointing straight at the mechanism instead of at TikTok.
- **Two-way CAC:** fire when CAC falls sharply as well as when it rises. Here the latest 2 weeks fell 16.3%, which the current rise-only rule can't see.
