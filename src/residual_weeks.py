"""The weeks where a run's model and actual revenue disagree most, with context.
Reads results/<run>/fit.csv, results/<baseline>/fit.csv and the run's model input
(results/investigations/<run>/model_input_full__<run>.csv, from run_investigation.py).

Run:  python src/residual_weeks.py scenario_A --top 5

For the run's largest absolute residuals: the residual in revenue and percent,
baseline's residual in the same week, and what was happening that week in the
run's own data (holiday flags, promo intensity, and each channel's spend as a
multiple of that channel's median week). Everything but the baseline residual
is available from the run alone.

Writes results/investigations/<run>/residual_weeks.csv.
"""
import argparse

import pandas as pd

from db import ROOT

CHANNELS = ["meta", "google", "tiktok", "email"]
HOLIDAYS = ["hol_black_friday", "hol_cyber_monday", "hol_mothers_day", "hol_valentines", "hol_christmas"]


def main(run, top, baseline="baseline"):
    out = ROOT / "results" / "investigations" / run
    fr = pd.read_csv(ROOT / "results" / run / "fit.csv")
    fb = pd.read_csv(ROOT / "results" / baseline / "fit.csv")
    mi = pd.read_csv(out / f"model_input_full__{run}.csv")
    for f in (fr, fb):
        f["resid"] = f.actual - f.predicted
        f["resid_pct"] = f.actual / f.predicted - 1
    worst = fr.reindex(fr.resid.abs().sort_values(ascending=False).index).head(top)
    m = worst.merge(fb[["week_start", "resid", "resid_pct"]], on="week_start",
                    how="left", suffixes=("", "_baseline"))
    m = m.merge(mi[["week_start"] + HOLIDAYS + ["promo_intensity"]
                   + [f"{c}_spend" for c in CHANNELS]], on="week_start", how="left")
    for c in CHANNELS:
        med = mi[f"{c}_spend"][mi[f"{c}_spend"] > 0].median()
        m[f"{c}_spend_x_median"] = m[f"{c}_spend"] / med
    m["holidays"] = m[HOLIDAYS].apply(lambda r: ",".join(h[4:] for h in HOLIDAYS if r[h] == 1), axis=1)
    m = m.drop(columns=HOLIDAYS)
    m.insert(0, "rank", range(1, len(m) + 1))
    m.to_csv(out / "residual_weeks.csv", index=False)
    print(m.round(3).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()
    main(a.run, a.top)
