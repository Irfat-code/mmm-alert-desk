"""Compare fitted configs side by side. Reads only results/ and models/, never data/truth/.

Run:  python src/compare_configs.py baseline_v0 hill_spendshare logistic_spendshare v0_accept95

Needs for each config: results/<name>/diagnostics.json, estimates.csv, prior_check.json
and models/<name>.nc. Writes:
    results/comparison.csv          one row per config: convergence, fit, plausibility, trend
    results/comparison_channels.csv one row per config x channel: ROAS, interval width,
                                    prior vs posterior beta, too-tight flag
"""
import json
import sys

import numpy as np
import pandas as pd

from db import ROOT

TIGHT_QUANTILE = "q90"   # rule set before fitting: posterior median beta above prior q90 -> too tight


def load(name):
    import arviz as az

    out = ROOT / "results" / name
    diag = json.loads((out / "diagnostics.json").read_text())
    est = pd.read_csv(out / "estimates.csv")
    prior = json.loads((out / "prior_check.json").read_text())
    idata = az.from_netcdf(ROOT / "models" / f"{name}.nc")
    post = idata.posterior.to_dataset().stack(sample=("chain", "draw"))
    return diag, est, prior, post, float(idata.constant_data["target_scale"])


def summarise(name):
    diag, est, prior, post, target_scale = load(name)
    plaus = diag["plausibility"]
    dec = diag["decomposition"]

    trend = post["gamma_control"].sel(control="trend").to_numpy()
    media = post["channel_contribution"]
    media = media.sum([d for d in media.dims if d != "sample"]).to_numpy()
    intercept = post["intercept_contribution"].to_numpy()

    row = dict(
        config=name,
        divergences=diag["divergences"],
        max_treedepth_hits=sum(diag["max_treedepth_hits_by_chain"] or [0]),
        max_rhat=diag["max_rhat"],
        worst_rhat_param=diag["worst_rhat_param"],
        r2=diag["r2"],
        mape=diag["mape"],
        sampling_minutes=diag["sampling_minutes"],
        media_share=plaus["media_share_of_revenue"],
        media_share_flag=plaus["media_share_flag"],
        wide_interval_channels=" ".join(plaus["wide_interval_channels"]) or "none",
        intercept_per_week=dec.get("intercept_per_week"),
        corr_intercept_media=round(float(np.corrcoef(intercept, media)[0, 1]), 4),
        # trend runs from 0 to (n-1)/n, so gamma * target_scale is roughly the
        # weekly revenue change from the first week to the last
        trend_gamma_mean=round(float(trend.mean()), 4),
        trend_gamma_low_5=round(float(np.quantile(trend, 0.05)), 4),
        trend_gamma_high_95=round(float(np.quantile(trend, 0.95)), 4),
        trend_weekly_change_mean=round(float(trend.mean()) * target_scale, 2),
        corr_trend_intercept=round(float(np.corrcoef(trend, intercept)[0, 1]), 4),
        corr_trend_media=round(float(np.corrcoef(trend, media)[0, 1]), 4),
    )

    prior_beta = prior["prior_moments"]["saturation_beta"]
    channels = []
    for r in est.itertuples():
        beta = post["saturation_beta"].sel(channel=r.channel).to_numpy()
        pb = prior_beta[r.channel]
        post_median = float(np.median(beta))
        channels.append(dict(
            config=name, channel=r.channel,
            roas_mean=r.roas_mean, roas_low_5=r.roas_low_5, roas_high_95=r.roas_high_95,
            width_over_lower=plaus["channels"][r.channel]["width_over_lower"],
            wide_interval=plaus["channels"][r.channel]["wide_interval"],
            prior_beta_median=pb["q50"], prior_beta_q90=pb["q90"], prior_beta_sd=pb["sd"],
            post_beta_median=round(post_median, 4), post_beta_sd=r.post_beta_sd,
            # below 1: the data narrowed the prior. Near 1: the posterior is the prior.
            # Both come from estimates.csv, written by fit_model.py.
            sd_ratio_post_over_prior=r.sd_ratio_post_over_prior,
            measured=bool(r.measured),
            # how far the median moved, in prior standard deviations
            median_shift_in_prior_sd=round((post_median - pb["q50"]) / pb["sd"], 2),
            prior_too_tight=bool(post_median > pb[TIGHT_QUANTILE]),
        ))
    return row, channels


def main(names):
    rows, channel_rows = [], []
    for name in names:
        row, channels = summarise(name)
        rows.append(row)
        channel_rows.extend(channels)
    summary = pd.DataFrame(rows)
    channels = pd.DataFrame(channel_rows)
    summary.to_csv(ROOT / "results" / "comparison.csv", index=False)
    channels.to_csv(ROOT / "results" / "comparison_channels.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        print(summary.set_index("config").T.to_string())
        print()
        print(channels.to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python src/compare_configs.py <config name> [<config name> ...]")
    main(sys.argv[1:])
