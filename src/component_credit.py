"""Dollar credit per control and per channel, run vs baseline, from the saved models.
Reads only models/. Never reads data/truth/.

Run:  python src/component_credit.py scenario_F [--split 2025-10-06]

Writes to results/investigations/<run>/:
    component_credit.csv   per control and per channel: total credit in dollars
                           (posterior mean, 5% and 95%), baseline and run, and the change.
                           With --split, also the credit before and from that week.
"""
import argparse

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT


def ds(g):
    return g.to_dataset() if hasattr(g, "to_dataset") else g


def credit(run):
    idata = az.from_netcdf(ROOT / "models" / f"{run}.nc")
    post = ds(idata.posterior)
    scale = float(ds(idata.constant_data)["target_scale"])
    out = {}
    for var, dim in (("control_contribution", "control"), ("channel_contribution", "channel")):
        x = post[var] * scale
        for name in x[dim].values:
            out[(dim, str(name))] = x.sel({dim: name})
    return out


def summarise(x, dates, mask):
    tot = x.isel(date=np.where(mask)[0]).sum("date").stack(s=("chain", "draw")).to_numpy()
    return tot.mean(), np.quantile(tot, 0.05), np.quantile(tot, 0.95)


def main(run, split):
    base, new = credit("baseline"), credit(run)
    rows = []
    for key in base:
        dates = pd.to_datetime(base[key].date.values)
        periods = [("all", np.ones(len(dates), bool))]
        if split:
            s = pd.Timestamp(split)
            periods += [(f"before {split}", dates < s), (f"from {split}", dates >= s)]
        for label, mask in periods:
            bm, bl, bh = summarise(base[key], dates, mask)
            rm, rl, rh = summarise(new[key], dates, mask)
            rows.append(dict(kind=key[0], name=key[1], period=label, weeks=int(mask.sum()),
                             baseline=round(bm, 2), baseline_5=round(bl, 2), baseline_95=round(bh, 2),
                             run=round(rm, 2), run_5=round(rl, 2), run_95=round(rh, 2),
                             change=round(rm - bm, 2)))
    df = pd.DataFrame(rows)
    out = ROOT / "results" / "investigations" / run
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "component_credit.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("--split", default=None)
    a = p.parse_args()
    main(a.run, a.split)
