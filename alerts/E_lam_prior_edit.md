# Alert A006: Undocumented prior edit told the model every channel maxes out at 10% of its peak week (scenario_E)
Raised: 2026-11-18  |  Triage done: 2026-11-18  |  Resolved: open, waiting on revert and refit

**Bottom line.** One model setting was changed without a record. Before seeing data, the model assumed every channel stops working after about a tenth of its biggest week's spend. For Meta, Google and TikTok, the data overruled this. Average ROAS is within 9% of baseline, and the return on the next dollar within 2%. Email has too little data to overrule anything, so the bad setting alone shapes its curve and pulls credit from baseline sales. Don't use this run. Revert the setting and refit.

## Symptom
A006 `convergence divergences`: 14, against 0 on baseline. The clean model gives 0–1 across seeds (`scenario_D/seed_check.csv`), so this is not noise. The worst R-hat is `saturation_lam` at 1.0020, under the threshold. No data checks fired.

## Hypotheses
1. **Confirmed:** the `saturation_lam` prior changed.
2. **Rejected:** sampler settings, model structure, a data change, sampler noise.

## Evidence
Outputs are in [results/investigations/scenario_E/](../results/investigations/scenario_E/).
- **Data identical:** all checks return 0, all 6 raw tables match baseline row for row, and the model input matches in every column (`check_counts`, `table_diff`, `model_input_full_diff`).
- **What the fitted model assumed** (`model_spec_diff`): one entry differs, the lam prior: Gamma(3, 0.1), mean 30, instead of Gamma(3, 1), mean 3. Sampler, structure, adstock, beta priors and scaling are identical.
- **In plain terms** (`saturation_points`): at the prior mean, baseline assumes 90% of a channel's maximum effect at 98% of its peak week. E assumes 10%: Meta at $5,337 a week against a $54,377 peak.
- **Divergences** (`divergence_summary`, `saturation_points`): 64% of divergent draws sit in the outer 10% of email's beta, and 50% in the bottom 10% of the intercept, against about 20% by chance. Under E, email is past its 90% point in every week, so its effect is close to a constant the intercept can stand in for. The email beta–intercept correlation went from −0.29 to −0.53.
- **Confirmation, done after classifying:** `configs/scenario_E.json` adds `priors.saturation_lam` = Gamma(3, 0.1). Neither its description nor `configs/CHANGELOG.md` mentions it.

## Classification
MODEL. The data is identical, one prior differs, and the divergences sit on the ridge that prior creates.

## Root cause
A prior override made lam's prior mean 10 times larger. The data pulled the paid channels back (lam 3.2–3.6). Email's posterior stayed at the prior (lam 29.4), and its near-constant effect traded off against the intercept, which caused the divergences.

## Recommendation
- **Today (MMM analyst):** remove the override from `configs/scenario_E.json`, refit, and rerun `monitor.py`. Expect 0–1 divergences and lam around 3.
- **Prevention:** any prior change needs a changelog entry and a `prior_check.py` run before fitting. That check already fails this config: the prior median media share is 73.2% against 36.0%, and P(> 80%) is 41.6% against 5.9%, where the priors were set to give about 5%. Add a saturation-point line to it ("90% effect at X% of peak"). A config review would have prevented this.

## Impact
- **Paid channels: not material.** Average ROAS: Meta +5.9%, Google +8.2%, TikTok +1.0%, inside baseline's intervals. Saturation points moved earlier (Meta 91% → 82% of peak), but average spend sits far below them ($24,105 against a $54,377 peak for Meta). Marginal ROAS at average spend: Meta 1.71 → 1.70, Google 1.70 → 1.71, TikTok 1.67 → 1.65 (`marginal_roas_diff`).
- **Email: not a measurement in either run, but the bad prior still acts.** Email's curve restates its prior, so the 0.12 return on the next dollar (baseline 2.31) is what the bad prior alone would hand a budget tool. A tool reading the curves would cut email. Email also took 511,366 of contribution: 34.5% of the +1,481,904 media change and 1.61 of the 4.66-point rise in media share. The intercept fell by 1,543,989 (`media_shift`).

## Monitor: candidate rule for v2
**Spec diff:** fire when a run's saved model spec differs from baseline's beyond its database and name. Here it would have named the prior. Candidate only.
