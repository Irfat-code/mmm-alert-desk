"""How a run divides credit between channels, compared with the baseline.
Reads only results/, models/ and results/investigations/. Never reads data/truth/.

Run:  python src/credit_check.py scenario_B --from 2025-09-01 --to 2025-12-22

--from/--to is the window to compare against the weeks before it (for scenario_B,
the weeks where Meta spend changed, from spend_diff_summary.csv).

Writes to results/investigations/<run>/:
    spend_corr.csv         correlation of weekly spend, Meta vs each other channel,
                           full history and within the window, baseline and run
    posterior_corr.csv     posterior correlation of beta and of total contribution,
                           for each channel pair, baseline and run
    window_credit.csv      per channel: weekly contribution and contribution/spend,
                           before vs within the window, baseline and run
    window_residuals.csv   fit residuals before vs within the window
"""
import argparse
import itertools
import json

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT

CHANNELS = ["meta", "google", "tiktok", "email"]


def posterior(name):
    idata = az.from_netcdf(ROOT / "models" / f"{name}.nc")
    p = idata.posterior
    return p.to_dataset() if hasattr(p, "to_dataset") else p


def main(run, start, end, baseline="baseline", spend_label=None):
    out = ROOT / "results" / "investigations" / run
    spend_label = spend_label or run
    spend = {
        baseline: pd.read_csv(out / "model_spend__baseline.csv", parse_dates=["week_start"]),
        run: pd.read_csv(out / f"model_spend__{spend_label}.csv", parse_dates=["week_start"]),
    }
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    # 1. Spend correlation: Meta vs each other channel.
    rows = []
    for name, s in spend.items():
        win = s[(s.week_start >= start) & (s.week_start <= end)]
        for other in CHANNELS[1:]:
            for label, frame in [("full", s), ("window", win)]:
                rows.append(dict(run=name, pair=f"meta~{other}", period=label, weeks=len(frame),
                                 corr=frame.meta_spend.corr(frame[f"{other}_spend"])))
    pd.DataFrame(rows).to_csv(out / "spend_corr.csv", index=False)

    # 2. Posterior correlation of beta and of total contribution, per channel pair.
    rows, credit, resid = [], [], []
    for name in (baseline, run):
        p = posterior(name)
        beta = p["saturation_beta"].stack(sample=("chain", "draw"))
        contrib = p["channel_contribution_original_scale"]
        date_dim = [d for d in contrib.dims if d not in ("chain", "draw", "channel")][0]
        total = contrib.sum(date_dim).stack(sample=("chain", "draw"))
        for a, b in itertools.combinations(CHANNELS, 2):
            rows.append(dict(
                run=name, pair=f"{a}~{b}",
                beta_corr=float(np.corrcoef(beta.sel(channel=a), beta.sel(channel=b))[0, 1]),
                contribution_corr=float(np.corrcoef(total.sel(channel=a), total.sel(channel=b))[0, 1]),
            ))

        # 3. Weekly credit before vs within the window.
        weekly = contrib.mean(("chain", "draw")).to_pandas()          # date x channel
        weekly.index = pd.to_datetime(weekly.index)
        s = spend[name].set_index("week_start")
        in_win = (weekly.index >= start) & (weekly.index <= end)
        before = weekly.index < start
        for ch in CHANNELS:
            sp = s[f"{ch}_spend"].reindex(weekly.index)
            for label, mask in [("before", before), ("window", in_win)]:
                credit.append(dict(
                    run=name, channel=ch, period=label, weeks=int(mask.sum()),
                    contribution_per_week=weekly.loc[mask, ch].mean(),
                    spend_per_week=sp[mask].mean(),
                    contribution_per_spend=weekly.loc[mask, ch].sum() / sp[mask].sum(),
                ))
        fit = pd.read_csv(ROOT / "results" / name / "fit.csv", parse_dates=["week_start"])
        fit["resid_pct"] = fit.actual / fit.predicted - 1
        for label, mask in [("before", fit.week_start < start),
                            ("window", (fit.week_start >= start) & (fit.week_start <= end))]:
            r = fit.loc[mask, "resid_pct"]
            resid.append(dict(run=name, period=label, weeks=int(mask.sum()),
                              mean_resid_pct=r.mean(), mean_abs_resid_pct=r.abs().mean()))

    # 4. Where the credit went: total contribution per control, and how each
    #    channel's weekly spend lines up with the baseline's control contribution.
    ctrl_rows, align = [], []
    for name in (baseline, run):
        cc = posterior(name)["control_contribution"]
        date_dim = [d for d in cc.dims if d not in ("chain", "draw", "control")][0]
        tot = cc.sum(date_dim).mean(("chain", "draw")).to_pandas()
        for ctrl, v in tot.items():
            ctrl_rows.append(dict(run=name, control=ctrl, contribution=v))
        if name == baseline:
            weekly_ctrl = cc.sum("control").mean(("chain", "draw")).to_pandas()
            weekly_ctrl.index = pd.to_datetime(weekly_ctrl.index)
    ctrl = pd.DataFrame(ctrl_rows).pivot(index="control", columns="run", values="contribution")
    ctrl["change"] = ctrl[run] - ctrl[baseline]
    ctrl.reset_index().to_csv(out / "control_credit.csv", index=False)
    for name, s in spend.items():
        s = s.set_index("week_start").reindex(weekly_ctrl.index)
        for ch in CHANNELS:
            align.append(dict(run=name, channel=ch,
                              corr_with_baseline_control_contribution=s[f"{ch}_spend"].corr(weekly_ctrl)))
    pd.DataFrame(align).to_csv(out / "spend_vs_controls.csv", index=False)

    # 5. Trend: each channel's spend against time, and the trend coefficient.
    trend_rows = []
    for name, s in spend.items():
        t = np.arange(len(s))
        for ch in CHANNELS:
            trend_rows.append(dict(run=name, item=f"corr({ch}_spend, week index)",
                                   value=float(np.corrcoef(s[f"{ch}_spend"], t)[0, 1])))
    for name in (baseline, run):
        g = posterior(name)["gamma_control"].sel(control="trend").stack(sample=("chain", "draw")).to_numpy()
        trend_rows += [dict(run=name, item="trend gamma mean", value=g.mean()),
                       dict(run=name, item="trend gamma 5%", value=np.quantile(g, 0.05)),
                       dict(run=name, item="trend gamma 95%", value=np.quantile(g, 0.95))]
    pd.DataFrame(trend_rows).to_csv(out / "trend_check.csv", index=False)

    pd.DataFrame(rows).to_csv(out / "posterior_corr.csv", index=False)
    pd.DataFrame(credit).to_csv(out / "window_credit.csv", index=False)
    pd.DataFrame(resid).to_csv(out / "window_residuals.csv", index=False)
    print(f"Saved spend_corr, posterior_corr, window_credit, window_residuals to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--baseline", default="baseline")
    args = ap.parse_args()
    main(args.run, args.start, args.end, args.baseline)
