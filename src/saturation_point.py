"""Translate the logistic saturation parameter lam into plain terms.
Reads only models/<run>.nc (spec, priors, posterior and channel scale).

Run:  python src/saturation_point.py scenario_E

Logistic saturation: effect = beta * (1 - exp(-lam*x)) / (1 + exp(-lam*x)), where x is the
channel's (normalized adstock) spend divided by its peak weekly spend (channel_scale).
The effect reaches 90% of its maximum at x90 = ln(19) / lam. For steady spend, x90 is the
share of the channel's peak week at which extra spend adds almost nothing.

Writes results/investigations/<run>/saturation_points.csv: for baseline and run, at the
prior mean and the posterior mean (with 90% interval) of lam, the share of peak spend and
the weekly spend at which each channel reaches 90% of its maximum effect.
"""
import json
import sys

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT

X90 = np.log(19.0)   # lam * x at which (1 - e^-z) / (1 + e^-z) = 0.9


def check_formula():
    """Confirm the closed form against pymc-marketing's own function."""
    import xarray as xr
    from pymc_marketing.mmm.transformers import logistic_saturation
    lam = 3.0
    x = xr.DataArray(np.array([X90 / lam]), dims=["date"])
    v = float(np.asarray(logistic_saturation(x, lam).eval()).ravel()[0])
    assert abs(v - 0.9) < 1e-9, v


def main(run, baseline="baseline"):
    check_formula()
    rows = []
    for name in (baseline, run):
        idata = az.from_netcdf(ROOT / "models" / f"{name}.nc")
        cfg = json.loads(idata.attrs["model_config"])["saturation_lam"]
        assert cfg["dist"] == "Gamma"
        a, b = cfg["kwargs"]["alpha"], cfg["kwargs"]["beta"]
        cd = idata.constant_data.to_dataset() if hasattr(idata.constant_data, "to_dataset") else idata.constant_data
        scale = cd["channel_scale"].to_pandas()
        post = idata.posterior.to_dataset() if hasattr(idata.posterior, "to_dataset") else idata.posterior
        lam = post["saturation_lam"].stack(sample=("chain", "draw"))
        spend = cd["channel_data"].to_pandas()                 # raw weekly spend, date x channel
        beta = post["saturation_beta"].stack(sample=("chain", "draw"))
        intercept = post["intercept_contribution"].stack(sample=("chain", "draw")).to_numpy()
        for ch in scale.index:
            peak = float(scale[ch])
            draws = lam.sel(channel=ch).to_numpy()
            beta_intercept_corr = float(np.corrcoef(beta.sel(channel=ch).to_numpy(), intercept)[0, 1])
            for source, value, lo, hi in [
                ("prior mean", a / b, None, None),
                ("posterior mean", draws.mean(), np.quantile(draws, 0.05), np.quantile(draws, 0.95)),
            ]:
                share = X90 / value
                rows.append(dict(
                    run=name, source=source, channel=str(ch), prior=f"Gamma({a}, {b})",
                    lam=value, lam_q05=lo, lam_q95=hi,
                    prior_sd=np.sqrt(a) / b,
                    posterior_sd=draws.std() if source == "posterior mean" else None,
                    peak_weekly_spend=peak,
                    share_of_peak_at_90pct=share,
                    weekly_spend_at_90pct=share * peak,
                    # Weeks whose raw spend is past the 90% point: there, the effect is
                    # close to a constant beta, which the intercept can stand in for.
                    share_of_weeks_above_90pct=float((spend[ch] > share * peak).mean()),
                    posterior_corr_beta_intercept=beta_intercept_corr,
                ))
    df = pd.DataFrame(rows)
    out = ROOT / "results" / "investigations" / run
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "saturation_points.csv", index=False)
    print(df.round(3).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
