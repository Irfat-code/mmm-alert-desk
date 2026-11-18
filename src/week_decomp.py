"""Week-by-week decomposition of the model's prediction, baseline vs a run.
Reads models/<name>.nc and results/<name>/fit.csv. Never reads data/truth/.

Run:  python src/week_decomp.py scenario_A --from 2025-03-17 --to 2025-05-05

For each week in the window: actual revenue, the prediction, and its parts (posterior
means, revenue units): each channel, the promo control, the other controls, the
intercept and yearly seasonality. Also the channel spend that week.

Writes results/investigations/<run>/week_decomp.csv (long: run x week x part).
"""
import argparse

import arviz as az
import pandas as pd

from db import ROOT


def ds(group):
    return group.to_dataset() if hasattr(group, "to_dataset") else group


def decomp(name):
    idata = az.from_netcdf(ROOT / "models" / f"{name}.nc")
    post, cd = ds(idata.posterior), ds(idata.constant_data)
    ts = float(cd["target_scale"])
    mean = lambda v: post[v].mean(("chain", "draw"))
    ch = mean("channel_contribution_original_scale").to_pandas()
    ch.columns = [f"ch_{c}" for c in ch.columns]
    ctrl = (mean("control_contribution") * ts).to_pandas()
    parts = ch.copy()
    parts["ctrl_promo"] = ctrl["promo_intensity"]
    parts["ctrl_other"] = ctrl.drop(columns="promo_intensity").sum(axis=1)
    parts["intercept"] = float(mean("intercept_contribution")) * ts
    parts["seasonality"] = (mean("yearly_seasonality_contribution") * ts).to_pandas()
    parts["model_sum"] = parts.sum(axis=1)
    spend = cd["channel_data"].to_pandas()
    spend.columns = [f"spend_{c}" for c in spend.columns]
    parts = parts.join(spend)
    parts.index = pd.to_datetime(parts.index)
    fit = pd.read_csv(ROOT / "results" / name / "fit.csv", parse_dates=["week_start"]).set_index("week_start")
    return parts.join(fit)


def all_weeks_test(run, baseline, focus, out):
    """Across all weeks: does each channel's change in credit (run minus baseline)
    track its own spend (a reshaped curve), or concentrate in the focus weeks
    (the channel absorbed a lift in those weeks)?"""
    b, r = decomp(baseline), decomp(run)
    focus = pd.to_datetime(focus)
    rows = []
    for ch in ["meta", "google", "tiktok", "email"]:
        delta = r[f"ch_{ch}"] - b[f"ch_{ch}"]
        spend = b[f"spend_{ch}"]
        in_f = delta.index.isin(focus)
        rows.append(dict(channel=ch,
                         corr_delta_with_spend=float(delta.corr(spend)),
                         mean_delta_focus_weeks=float(delta[in_f].mean()),
                         mean_delta_other_weeks=float(delta[~in_f].mean()),
                         sd_delta_other_weeks=float(delta[~in_f].std()),
                         total_delta=float(delta.sum())))
    pd.DataFrame(rows).to_csv(out / "week_decomp_test.csv", index=False)
    print(pd.DataFrame(rows).round(3).to_string(index=False))


def main(run, start, end, baseline="baseline", focus=None):
    if focus:
        all_weeks_test(run, baseline, focus, ROOT / "results" / "investigations" / run)
    frames = []
    for name in (baseline, run):
        d = decomp(name)
        d = d[(d.index >= pd.Timestamp(start)) & (d.index <= pd.Timestamp(end))]
        frames.append(d.assign(run=name).reset_index(names="week_start"))
    df = pd.concat(frames)
    out = ROOT / "results" / "investigations" / run
    df.to_csv(out / "week_decomp.csv", index=False)
    print(df.round(0).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--focus", nargs="*", default=None,
                    help="weeks to test against all others (writes week_decomp_test.csv)")
    a = ap.parse_args()
    main(a.run, a.start, a.end, focus=a.focus)
