# Scored decisions (answer key)

Truth comparisons moved out of configs/CHANGELOG.md and README.md on 2026-11-18 to keep investigations blind.
Only scoring work may read this file. Investigation sessions must not (CLAUDE.md rule 1).

## From configs/CHANGELOG.md

### Scored after decision (2026-11-18)

Written after the decision above, which was not edited after scoring. Numbers come from `python src/score_against_truth.py <name>`, saved in `data/truth/scores/<name>.csv`.

| Channel | True ROAS | v0 | C v0_accept95 | A hill_spendshare | baseline (B) |
|---|---|---|---|---|---|
| meta | 1.80 | 6.60 (+266.9%) | 7.13 (+296.2%) | 2.74 (+52.2%) | 2.33 (+29.4%), truth outside interval |
| google | 2.40 | 6.01 (+150.4%) | 5.68 (+136.5%) | 1.97 (−17.8%) | 2.16 (−9.9%) |
| tiktok | 1.20 | 1.62 (+35.2%) | 1.63 (+36.0%) | 1.55 (+29.5%) | 1.71 (+42.5%) |
| email | 5.00 | not measured | not measured | not measured | not measured by the MMM (posterior = prior) |
| Truth inside 90% interval | | 3 of 4 | 3 of 4 | 4 of 4 | 3 of 4 |
| Ranking matches truth | | no | no | no | no |

**What held up**

- Rejecting v0 and C was right. Both overstated meta and google ROAS by 136% to 296%. The 157% and 166% media share flags pointed to a real problem, not a false alarm.
- C confirmed that target_accept doesn't fix this. Its errors are about the same as v0's or worse.
- B is closer to the truth than A on meta (+29.4% vs +52.2%) and google (−9.9% vs −17.8%), the two largest channels.
- The email floor was reasonable. True email ROAS (5.00) sits inside the prior's range (95th percentile 14.79 at full saturation), so the floor didn't rule out the truth. The MMM still did not measure email, and the scores don't change that.

**Where it didn't**

- **B's narrower intervals were partly overconfident.** For meta, B's 90% interval is 1.83 to 2.87 and the truth is 1.80, just outside. A's wider interval (1.48 to 4.52) contained it. Interval width was one of the reasons to prefer B, and narrow is only good if it is also right.
- **TikTok is worse in B than in A** (+42.5% vs +29.5%), and every config overstates it.
- **No config ranks meta and google correctly.** All four put meta above google, but google has the higher true ROAS. In A and B, meta is overstated and google understated. This fits the spend-share prior, which gives meta (49.2% of spend) the largest beta prior. The prior assumes that a bigger budget means a bigger effect, which is not true here. This is a hypothesis, not tested.

**For future decisions:** do not prefer a config for narrower intervals alone. Check whether the intervals are right, against a lift test where one exists. Treat the meta vs google split as uncertain in any budget advice from this baseline.


## From README.md

Scoreboard row:

| | |
|---|---|
| Recovered ROAS vs true ROAS (baseline) | Meta 2.33 (true 1.80), Google 2.16 (true 2.40), TikTok 1.71 (true 1.20). Email: not measured by the MMM (posterior = prior). Truth inside the 90% interval for Google and TikTok, not Meta. Meta and Google rank the wrong way round. |

The brand, with true parameters:

| Channel | 3-yr spend | True ROAS | True marginal ROAS | Carryover | Notes |
|---|---|---|---|---|---|
| Meta | $3.76M | 1.80 | 1.50 | slow (α 0.55) | biggest budget, S-shaped curve |
| Google | $2.41M | 2.40 | 1.55 | fast (α 0.25) | search, PMax, some YouTube |
| TikTok | $1.26M | 1.20 | 0.95 | medium (α 0.40) | launched mid-2023, ramps up |
| Email/SMS | $0.21M | 5.00 | 2.65 | very fast (α 0.10) | Klaviyo, small spend, high ROAS |

Marginal ROAS is lower than average ROAS for every channel because of saturation. TikTok's marginal ROAS is below 1, so the next dollar there loses money even though the average looks fine.

Revenue is about half baseline (trend + seasonality) and half media, plus holiday weeks (Black Friday, Cyber Monday, Mother's Day, Valentine's, a Christmas dip) and about 4 sitewide promos a year.
