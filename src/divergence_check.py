"""Where do a run's divergent draws sit in the posterior? Reads only models/<run>.nc.

Run:  python src/divergence_check.py scenario_D

For each divergent draw and each scalar or per-channel parameter, reports the
draw's percentile within that parameter's posterior. Divergences that cluster
at the edge of one channel's parameters (near 0 or 100) point to a hard region
of the geometry. Percentiles spread around the middle point to no clear region.

Writes results/investigations/<run>/divergences.csv and divergence_summary.csv.
"""
import sys

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT

PARAMS = ["adstock_alpha", "saturation_lam", "saturation_beta", "intercept_contribution", "y_sigma"]


def main(run):
    idata = az.from_netcdf(ROOT / "models" / f"{run}.nc")
    post = idata.posterior.to_dataset() if hasattr(idata.posterior, "to_dataset") else idata.posterior
    ss = idata.sample_stats.to_dataset() if hasattr(idata.sample_stats, "to_dataset") else idata.sample_stats
    div = ss["diverging"].to_numpy()                  # chain x draw
    where = np.argwhere(div)
    rows = []
    for chain, draw in where:
        for var in PARAMS:
            da = post[var]
            names = [str(c) for c in da.channel.values] if "channel" in da.dims else [None]
            for ch in names:
                x = da.sel(channel=ch) if ch else da
                allv = x.to_numpy().ravel()
                v = float(x.isel(chain=chain, draw=draw))
                rows.append(dict(chain=int(chain), draw=int(draw), param=var, channel=ch or "",
                                 value=v, percentile=float((allv < v).mean() * 100)))
    df = pd.DataFrame(rows)
    out = ROOT / "results" / "investigations" / run
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "divergences.csv", index=False)
    if len(df):
        g = df.groupby(["param", "channel"]).percentile
        s = g.agg(["min", "median", "max"]).reset_index()
        # With no clustering, about 20% of draws fall in the outer 10% (both tails together).
        s["share_in_outer_10pct"] = g.apply(lambda p: float(((p <= 10) | (p >= 90)).mean())).to_numpy()
        s["share_in_top_10pct"] = g.apply(lambda p: float((p >= 90).mean())).to_numpy()
        s["share_in_bottom_10pct"] = g.apply(lambda p: float((p <= 10).mean())).to_numpy()
        s["all_in_outer_10pct"] = s.share_in_outer_10pct == 1.0
        s.to_csv(out / "divergence_summary.csv", index=False)
    print(f"{len(where)} divergent draw(s) in {run}: chains {sorted(set(where[:, 0].tolist()))}")


if __name__ == "__main__":
    main(sys.argv[1])
