"""Compare runs fitted with different sampler seeds. Reads only results/ and models/.

Run:  python src/seed_check.py scenario_D baseline scenario_D__seed20261118 baseline__seed20261118 \
          --out scenario_D --channel tiktok

Writes results/investigations/<out>/seed_check.csv: divergences, max R-hat, and the
chosen channel's ROAS, SD ratio and adstock alpha for each run.
"""
import argparse
import json

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT


def main(runs, out, channel):
    rows = []
    for run in runs:
        d = json.loads((ROOT / "results" / run / "diagnostics.json").read_text())
        est = pd.read_csv(ROOT / "results" / run / "estimates.csv").set_index("channel").loc[channel]
        post = az.from_netcdf(ROOT / "models" / f"{run}.nc").posterior
        post = post.to_dataset() if hasattr(post, "to_dataset") else post
        alpha = post["adstock_alpha"].sel(channel=channel).to_numpy().ravel()
        rows.append(dict(run=run, divergences=d["divergences"], max_rhat=d["max_rhat"],
                         roas_mean=est.roas_mean, roas_low_5=est.roas_low_5, roas_high_95=est.roas_high_95,
                         sd_ratio=est.sd_ratio_post_over_prior,
                         alpha_mean=alpha.mean(), alpha_q05=np.quantile(alpha, 0.05),
                         alpha_q95=np.quantile(alpha, 0.95)))
    df = pd.DataFrame(rows)
    path = ROOT / "results" / "investigations" / out / "seed_check.csv"
    df.to_csv(path, index=False)
    print(df.round(4).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--channel", required=True)
    a = ap.parse_args()
    main(a.runs, a.out, a.channel)
