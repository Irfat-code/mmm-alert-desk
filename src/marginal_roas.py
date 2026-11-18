"""Marginal ROAS (return on the next dollar) per channel, baseline vs a run.
Reads only models/<run>.nc: spend, scales, spec and posterior draws.

Run:  python src/marginal_roas.py scenario_E

Rebuilds each channel's contribution from the posterior, using the model's own spec:
normalized geometric adstock (l_max from the saved spec), then logistic saturation
beta * (1 - e^-lam*x) / (1 + e^-lam*x) on spend / peak weekly spend, times the target
scale. The rebuild is first checked against the saved channel contributions.

Two marginal ROAS measures, per posterior draw, reported as mean and 90% interval:
    at_average_spend   steady weekly spend at the channel's average week: d(contribution)/d(spend)
    history_plus_1pct  every historical week +1%: extra contribution / extra spend

Writes to results/investigations/<run>/:
    marginal_roas.csv          per run and channel: average ROAS and both marginal measures
    marginal_roas_check.csv    rebuild vs saved contributions (max relative error)
"""
import json
import sys

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT

THIN = 4   # every 4th draw: 1,000 of 4,000, enough for means and 90% intervals


def ds(group):
    return group.to_dataset() if hasattr(group, "to_dataset") else group


def adstock(x, alpha, l_max):
    """x: weeks; alpha: draws. Normalized geometric adstock, zero-padded. Returns draws x weeks."""
    w = alpha[:, None] ** np.arange(l_max)[None, :]          # draws x lags
    w = w / w.sum(axis=1, keepdims=True)
    out = np.zeros((len(alpha), len(x)))
    for lag in range(l_max):
        out[:, lag:] += w[:, [lag]] * x[None, : len(x) - lag]
    return out


def logistic(z):
    return (1 - np.exp(-z)) / (1 + np.exp(-z))


def contribution(spend, peak, alpha, lam, beta, target_scale, l_max):
    """Weekly contribution in revenue units, draws x weeks."""
    xs = adstock(spend / peak, alpha, l_max)
    return beta[:, None] * logistic(lam[:, None] * xs) * target_scale


def q(x):
    return x.mean(), np.quantile(x, 0.05), np.quantile(x, 0.95)


def main(run, baseline="baseline"):
    rows, checks = [], []
    for name in (baseline, run):
        idata = az.from_netcdf(ROOT / "models" / f"{name}.nc")
        spec = json.loads(idata.attrs["adstock"])
        assert spec["__type__"].endswith("GeometricAdstock") and spec["normalize"]
        assert json.loads(idata.attrs["saturation"])["__type__"].endswith("LogisticSaturation")
        l_max = int(spec["l_max"])
        cd, post = ds(idata.constant_data), ds(idata.posterior)
        target_scale = float(cd["target_scale"])
        spend_all = cd["channel_data"].to_pandas()
        saved = post["channel_contribution_original_scale"].mean(("chain", "draw")).to_pandas()
        stacked = {v: post[v].stack(sample=("chain", "draw")) for v in
                   ["adstock_alpha", "saturation_lam", "saturation_beta"]}
        for ch in spend_all.columns:
            spend = spend_all[ch].to_numpy(float)
            peak = float(cd["channel_scale"].sel(channel=ch))
            a_all, l_all, b_all = (stacked[v].sel(channel=ch).to_numpy() for v in
                                   ["adstock_alpha", "saturation_lam", "saturation_beta"])

            # Check the rebuild against the model's saved contributions (all draws).
            rebuilt = contribution(spend, peak, a_all, l_all, b_all, target_scale, l_max).mean(axis=0)
            ref = saved[ch].to_numpy()
            checks.append(dict(run=name, channel=ch,
                               max_rel_error=float(np.max(np.abs(rebuilt - ref)) / ref.max())))

            a, lam, beta = a_all[::THIN], l_all[::THIN], b_all[::THIN]
            base = contribution(spend, peak, a, lam, beta, target_scale, l_max).sum(axis=1)
            up = contribution(spend * 1.01, peak, a, lam, beta, target_scale, l_max).sum(axis=1)
            hist_m = (up - base) / (0.01 * spend.sum())
            avg_roas = base / spend.sum()
            # Steady spend s: adstock of a constant is the constant (normalized weights).
            s_bar = spend.mean()
            z = lam * s_bar / peak
            at_avg = target_scale * beta * lam / peak * 2 * np.exp(-z) / (1 + np.exp(-z)) ** 2
            for label, x in [("average_roas", avg_roas), ("mroas_at_average_spend", at_avg),
                             ("mroas_history_plus_1pct", hist_m)]:
                m, lo, hi = q(x)
                rows.append(dict(run=name, channel=ch, measure=label, mean=m, q05=lo, q95=hi,
                                 average_weekly_spend=s_bar, peak_weekly_spend=peak))
    out = ROOT / "results" / "investigations" / run
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(checks).to_csv(out / "marginal_roas_check.csv", index=False)
    df = pd.DataFrame(rows)
    df.to_csv(out / "marginal_roas.csv", index=False)
    wide = df.pivot_table(index=["channel", "measure"], columns="run", values="mean").reset_index()
    wide["rel_change"] = wide[run] / wide[baseline] - 1
    wide.to_csv(out / "marginal_roas_diff.csv", index=False)
    print(pd.DataFrame(checks).to_string(index=False))
    print(df.round(4).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
