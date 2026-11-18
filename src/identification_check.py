"""Check whether a fitted MMM's parameters were learned from the data.

Reads the saved model in models/<name>.nc, never data/truth/.

Run:  python src/identification_check.py baseline_v0

Writes results/<name>/identification.json:
    corr_intercept_media   posterior correlation of the intercept and total media
                           contribution. Near -1 means the data only fix their sum.
    saturation             per channel: beta-kappa correlation, and the share of
                           posterior kappa above 1 (above the largest scaled spend),
                           to compare with the same share under the prior.
"""
import json
import sys

import numpy as np

from db import ROOT


def main(name):
    import arviz as az

    idata = az.from_netcdf(ROOT / "models" / f"{name}.nc")
    post = idata.posterior.to_dataset().stack(sample=("chain", "draw"))

    media = post["channel_contribution"]
    media = media.sum([d for d in media.dims if d != "sample"]).to_numpy()
    intercept = post["intercept_contribution"].to_numpy()
    out = dict(
        config=name,
        corr_intercept_media=round(float(np.corrcoef(intercept, media)[0, 1]), 4),
        saturation={},
    )

    params = [v for v in ("saturation_beta", "saturation_kappa", "saturation_lam") if v in post]
    for ch in post.channel.to_numpy():
        row = {}
        if "saturation_kappa" in post:
            beta = post["saturation_beta"].sel(channel=ch).to_numpy()
            kappa = post["saturation_kappa"].sel(channel=ch).to_numpy()
            row["corr_beta_kappa"] = round(float(np.corrcoef(beta, kappa)[0, 1]), 4)
            row["share_kappa_above_1"] = round(float((kappa > 1).mean()), 4)
        if "saturation_lam" in post:
            beta = post["saturation_beta"].sel(channel=ch).to_numpy()
            lam = post["saturation_lam"].sel(channel=ch).to_numpy()
            row["corr_beta_lam"] = round(float(np.corrcoef(beta, lam)[0, 1]), 4)
        for p in params:
            x = post[p].sel(channel=ch).to_numpy()
            row[f"{p}_mean"] = round(float(x.mean()), 4)
            row[f"{p}_sd"] = round(float(x.std()), 4)
        out["saturation"][str(ch)] = row

    path = ROOT / "results" / name / "identification.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/identification_check.py <config name>")
    main(sys.argv[1])
