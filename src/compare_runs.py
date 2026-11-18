"""Compare a run's saved results with the baseline's. Reads only results/.

Run:  python src/compare_runs.py scenario_C

Writes to results/investigations/<run>/:
    run_metrics.csv   fit, convergence and plausibility, baseline vs run
    run_roas.csv      ROAS per channel, baseline vs run, with relative change
    run_fit_tail.csv  last 4 fitted weeks of each run, actual vs predicted
"""
import json
import sys

import numpy as np
import pandas as pd

from db import ROOT

METRICS = ["r2", "mape", "max_rhat", "divergences"]
ROAS_MAX_SHIFT = 0.25   # same value as src/monitor.py


def main(run, baseline="baseline", out_name=None):
    res = ROOT / "results"
    out = res / "investigations" / (out_name or run)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    # NOTE: diagnostics.json also holds the run's config. It is never read here (rule 1).
    for name in (baseline, run):
        d = json.loads((res / name / "diagnostics.json").read_text())
        row = {"run": name, **{k: d[k] for k in METRICS}}
        row["media_share_of_revenue"] = d["plausibility"]["media_share_of_revenue"]
        row["intercept_per_week"] = d["decomposition"]["intercept_per_week"]
        for part in ["intercept", "controls", "seasonality", "media"]:
            row[f"decomp_{part}"] = d["decomposition"][part]
        row["n_fit_weeks"] = len(pd.read_csv(res / name / "fit.csv"))
        rows.append(row)
    metrics = pd.DataFrame(rows)
    metrics.to_csv(out / "run_metrics.csv", index=False)
    delta = (metrics.iloc[1][["r2", "mape"]] - metrics.iloc[0][["r2", "mape"]]).rename("run_minus_base")
    delta.to_frame().to_csv(out / "run_metrics_delta.csv")

    cols = ["channel", "spend", "contribution_mean", "roas_mean", "roas_low_5", "roas_high_95",
            "sd_ratio_post_over_prior", "measured", "reported"]
    b = pd.read_csv(res / baseline / "estimates.csv")[cols]
    n = pd.read_csv(res / run / "estimates.csv")[cols]
    roas = b.merge(n, on="channel", suffixes=("_base", "_run"))
    roas["roas_rel_change"] = roas.roas_mean_run / roas.roas_mean_base - 1
    roas["contribution_change"] = roas.contribution_mean_run - roas.contribution_mean_base
    roas["run_mean_outside_base_90"] = (roas.roas_mean_run < roas.roas_low_5_base) | (
        roas.roas_mean_run > roas.roas_high_95_base)
    # The monitor's roas_shift rule fires only if both parts hold, for measured channels.
    roas["shift_over_25pct"] = roas.roas_rel_change.abs() > ROAS_MAX_SHIFT
    roas["roas_rule_fires"] = (roas.shift_over_25pct & roas.run_mean_outside_base_90
                               & roas.measured_base & roas.measured_run)
    roas.to_csv(out / "run_roas.csv", index=False)

    # Where the change in total media credit came from, channel by channel.
    total_rev = json.loads((res / baseline / "diagnostics.json").read_text())["plausibility"]["total_revenue"]
    media_change = metrics.iloc[1]["decomp_media"] - metrics.iloc[0]["decomp_media"]
    shift = roas[["channel", "contribution_mean_base", "contribution_mean_run", "contribution_change"]].copy()
    shift["share_of_media_change"] = shift.contribution_change / media_change
    shift["media_share_pts_change"] = shift.contribution_change / total_rev * 100
    shift = pd.concat([shift, pd.DataFrame([dict(
        channel="TOTAL media (decomposition)", contribution_change=media_change,
        share_of_media_change=1.0, media_share_pts_change=media_change / total_rev * 100),
        dict(channel="intercept (decomposition)",
             contribution_change=metrics.iloc[1]["decomp_intercept"] - metrics.iloc[0]["decomp_intercept"])])])
    shift.to_csv(out / "media_shift.csv", index=False)

    # Posterior summaries of the per-channel media parameters, from models/<name>.nc.
    params = []
    for name in (baseline, run):
        nc = ROOT / "models" / f"{name}.nc"
        if not nc.exists():
            continue
        import arviz as az
        p = az.from_netcdf(nc).posterior
        p = p.to_dataset() if hasattr(p, "to_dataset") else p
        g = p["gamma_control"].stack(sample=("chain", "draw"))
        for c in g.control.values:
            x = g.sel(control=c).to_numpy()
            params.append(dict(run=name, param="gamma_control", channel=str(c), mean=x.mean(),
                               q05=np.quantile(x, 0.05), q95=np.quantile(x, 0.95)))
        for var in ["adstock_alpha", "saturation_lam", "saturation_beta"]:
            draws = p[var].stack(sample=("chain", "draw"))
            for ch in draws.channel.values:
                x = draws.sel(channel=ch).to_numpy()
                params.append(dict(run=name, param=var, channel=str(ch), mean=x.mean(),
                                   q05=np.quantile(x, 0.05), q95=np.quantile(x, 0.95)))
    if params:
        pr = pd.DataFrame(params)
        wide = pr[pr.run == baseline].merge(pr[pr.run == run], on=["param", "channel"],
                                            suffixes=("_base", "_run")).drop(columns=["run_base", "run_run"])
        wide["intervals_overlap"] = (wide.q05_run <= wide.q95_base) & (wide.q05_base <= wide.q95_run)
        wide.to_csv(out / "run_params.csv", index=False)

    tails = []
    for name in (baseline, run):
        f = pd.read_csv(res / name / "fit.csv").tail(4).assign(run=name)
        f["resid_pct"] = f.actual / f.predicted - 1
        tails.append(f)
    pd.concat(tails).to_csv(out / "run_fit_tail.csv", index=False)
    print(f"Saved run_metrics.csv, run_roas.csv, run_fit_tail.csv to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    # Optional 2nd arg: folder under results/investigations/ (default: the run name).
    main(sys.argv[1], out_name=sys.argv[2] if len(sys.argv) > 2 else None)
