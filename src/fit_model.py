"""Fit a Bayesian MMM from a config file and save its estimates and diagnostics.

Reads only the weekly_model_input view, never data/truth/.
Scoring against the truth is a separate step (score_against_truth.py).

Run:  python src/fit_model.py configs/baseline.json
      python src/fit_model.py configs/baseline.json --db data/other.duckdb
      python src/fit_model.py configs/baseline.json --estimates-only

Writes to results/<config name>/ (results/<config name>__<db name>/ with a non-default --db):
    estimates.csv     ROAS and contribution per channel, with 90% intervals, and
                      measured (whether the data narrowed the channel's beta prior) and
                      reported (measured and clear of the borderline band)
    fit.csv           actual vs predicted revenue per week
    diagnostics.json  convergence (R-hat, divergences, tree depth), fit (R2, MAPE)
                      and plausibility (media share of revenue, ROAS interval widths)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from db import DEFAULT_DB, ROOT, Database


def configure_backend():
    """Without g++, PyTensor's C backend is unavailable. Use Numba instead."""
    import pytensor

    if not pytensor.config.cxx:
        pytensor.config.mode = "NUMBA"
    return pytensor.config.mode


def load_model_input(channels, db_path=None):
    db = Database(db_path) if db_path else Database()
    df = db.query("SELECT * FROM weekly_model_input ORDER BY week_start")
    db.close()
    df["week_start"] = pd.to_datetime(df.week_start)
    df["trend"] = np.arange(len(df)) / len(df)
    df = df.rename(columns={f"{ch}_spend": ch for ch in channels})
    return df


HALFNORMAL_Q95 = 1.959964   # 95th percentile of HalfNormal(sigma=1)


def roas_floor_sigma(roas_95, weekly_spend, target_scale):
    """HalfNormal sigma whose 95th-percentile beta gives roas_95 at full saturation.

    At full saturation a channel adds beta * target_scale revenue per week, so its
    ROAS is beta * target_scale / weekly_spend.
    """
    return roas_95 * weekly_spend / target_scale / HALFNORMAL_Q95


def spend_share_sigma(cfg, df):
    """Per-channel prior sigma: n_channels x share of total spend x spend_share_scale.

    cfg["beta_floor_roas_95"] = {channel: ROAS} raises a channel's sigma, if needed,
    so its prior 95th-percentile ROAS at full saturation is at least that value.
    The target scale is max weekly revenue, matching the MMM's default max scaling.
    """
    spend = df[cfg["channels"]].sum()
    share = (spend / spend.sum()).to_numpy()
    sigma = len(cfg["channels"]) * share * cfg.get("spend_share_scale", 1.0)
    target_scale = float(df["revenue"].max())
    for ch, roas_95 in cfg.get("beta_floor_roas_95", {}).items():
        i = cfg["channels"].index(ch)
        floor = roas_floor_sigma(roas_95, spend[ch] / len(df), target_scale)
        sigma[i] = max(sigma[i], floor)
    return sigma


def make_prior(spec, cfg, df, dims=None):
    """Turn a config entry like {"dist": "HalfNormal", "sigma": 1} into a Prior.

    "sigma": "spend_share" is replaced by spend_share_sigma() and gets channel dims.
    """
    from pymc_extras.prior import Prior

    kwargs = {k: v for k, v in spec.items() if k != "dist"}
    if kwargs.get("sigma") == "spend_share":
        kwargs["sigma"] = spend_share_sigma(cfg, df)
        dims = "channel"
    return Prior(spec["dist"], **kwargs, dims=dims) if dims else Prior(spec["dist"], **kwargs)


def build_mmm(cfg, df):
    """Build the MMM. Priors not listed in cfg["priors"] keep the package defaults."""
    from pymc_marketing.mmm import GeometricAdstock, HillSaturation, LogisticSaturation
    from pymc_marketing.mmm.mmm import MMM

    priors = cfg.get("priors", {})
    saturation_priors = {
        name.removeprefix("saturation_"): make_prior(spec, cfg, df, dims="channel")
        for name, spec in priors.items() if name.startswith("saturation_")
    }
    model_config = {
        name: make_prior(spec, cfg, df)
        for name, spec in priors.items() if not name.startswith("saturation_")
    }
    saturation = {"hill": HillSaturation, "logistic": LogisticSaturation}[cfg["saturation"]]
    return MMM(
        date_column="week_start",
        target_column="revenue",
        channel_columns=cfg["channels"],
        control_columns=cfg["controls"],
        adstock=GeometricAdstock(l_max=cfg["adstock_l_max"]),
        saturation=saturation(priors=saturation_priors or None),
        yearly_seasonality=cfg["yearly_seasonality"],
        model_config=model_config or None,
    )


def split_rhat(draws):
    """Split R-hat for one scalar (chains x draws). Below 1.01 is good."""
    n = draws.shape[1] // 2
    halves = np.concatenate([draws[:, :n], draws[:, n:2 * n]], axis=0)
    within = halves.var(axis=1, ddof=1).mean()
    between = n * halves.mean(axis=1).var(ddof=1)
    var_plus = (n - 1) / n * within + between / n
    return float(np.sqrt(var_plus / within)) if within > 0 else np.nan


def convergence(idata):
    """Worst R-hat per parameter (skips anything indexed by date) and divergence count."""
    rhats = {}
    for name, var in idata.posterior.data_vars.items():
        if any("date" in d or "week" in d for d in var.dims):
            continue
        values = var.transpose("chain", "draw", ...).to_numpy()
        flat = values.reshape(values.shape[0], values.shape[1], -1)
        rhats[name] = max(split_rhat(flat[:, :, i]) for i in range(flat.shape[2]))
    divergences = int(idata.sample_stats["diverging"].sum())
    return rhats, divergences


def tree_depth_hits(idata):
    """Draws per chain that hit the sampler's max tree depth."""
    stats = idata.sample_stats
    if "reached_max_treedepth" not in stats:
        return None
    hits = stats["reached_max_treedepth"].sum("draw").to_numpy()
    return [int(h) for h in hits]


def decomposition(idata, n_weeks):
    """Total revenue credited to each model component, in dollars (posterior mean).

    The intercept has no date dimension, so its weekly value is multiplied by n_weeks.
    """
    post = idata.posterior
    scale = float(idata.constant_data["target_scale"])
    parts = {}
    for label, var in [("intercept", "intercept_contribution"),
                       ("controls", "control_contribution"),
                       ("seasonality", "yearly_seasonality_contribution"),
                       ("media", "channel_contribution")]:
        if var not in post:
            continue
        x = post[var]
        other = [d for d in x.dims if d not in ("chain", "draw")]
        total = x.sum(other) if other else x
        if not any(d == "date" or "week" in d for d in x.dims):
            total = total * n_weeks
        parts[label] = round(float(total.mean()) * scale, 2)
    if "intercept_contribution" in post and not post["intercept_contribution"].dims[2:]:
        parts["intercept_per_week"] = round(float(post["intercept_contribution"].mean()) * scale, 2)
    return parts


MAX_MEDIA_SHARE = 0.80     # media credited with more than this share of revenue is implausible
MAX_INTERVAL_RATIO = 10     # ROAS interval width above 10x its lower bound is too uncertain to report


def plausibility(est, total_revenue):
    """Business sanity checks on the channel estimates (no truth data used).

    est: the estimates table from channel_estimates().
    total_revenue: sum of weekly revenue over the modelled period.
    """
    media = float(est.contribution_mean.sum())
    share = media / total_revenue
    channels = {}
    for row in est.itertuples():
        width = row.roas_high_95 - row.roas_low_5
        ratio = width / row.roas_low_5 if row.roas_low_5 > 0 else float("inf")
        channels[row.channel] = dict(
            roas_interval_width=round(width, 4),
            width_over_lower=round(ratio, 2),
            wide_interval=bool(ratio > MAX_INTERVAL_RATIO),
        )
    wide = [ch for ch, c in channels.items() if c["wide_interval"]]
    return dict(
        total_revenue=round(total_revenue, 2),
        media_contribution=round(media, 2),
        media_share_of_revenue=round(share, 4),
        media_share_flag=bool(share > MAX_MEDIA_SHARE),
        media_share_threshold=MAX_MEDIA_SHARE,
        interval_ratio_threshold=MAX_INTERVAL_RATIO,
        wide_interval_channels=wide,
        channels=channels,
        plausible=bool(share <= MAX_MEDIA_SHARE and not wide),
    )


# A channel counts as measured by the MMM only if the data narrowed its beta prior:
# posterior sd / prior sd of beta at or below this value. Above it, the posterior is
# mostly the prior, and the channel's ROAS is reported as "not measured by the MMM".
MEASURED_MAX_SD_RATIO = 0.9
# Borderline band: a ratio above this but at or below MEASURED_MAX_SD_RATIO counts as
# measured (the monitor compares it), but its ROAS is not reported. A channel this close
# to the threshold can flip between runs on small data changes (see configs/CHANGELOG.md).
REPORTED_MAX_SD_RATIO = 0.85
PRIOR_DRAWS = 2000


def as_dataset(group):
    """arviz 1.x returns DataTree groups; convert to a plain xarray Dataset."""
    return group.to_dataset() if hasattr(group, "to_dataset") else group


def sample_prior(mmm, seed):
    """Prior draws for every model variable, stacked into one 'sample' dim.

    Used by fit_model.py (prior sd of beta) and prior_check.py, so both see the same draws.
    """
    import pymc as pm

    with mmm.model:
        prior = pm.sample_prior_predictive(draws=PRIOR_DRAWS, random_seed=seed).prior
    return as_dataset(prior).stack(sample=("chain", "draw"))


def channel_estimates(idata, df, channels, prior_beta_sd):
    """ROAS per channel with 90% intervals, plus whether the data informed the channel."""
    posterior = as_dataset(idata.posterior)
    contrib = posterior["channel_contribution_original_scale"]
    date_dim = [d for d in contrib.dims if d not in ("chain", "draw", "channel")][0]
    totals = contrib.sum(date_dim).stack(sample=("chain", "draw"))   # channel x sample
    beta = posterior["saturation_beta"].stack(sample=("chain", "draw"))
    rows = []
    for ch in channels:
        spend = df[ch].sum()
        samples = totals.sel(channel=ch).to_numpy()
        roas = samples / spend
        post_sd = float(beta.sel(channel=ch).std())
        ratio = post_sd / prior_beta_sd[ch]
        rows.append(dict(
            channel=ch, spend=round(spend, 2),
            contribution_mean=round(samples.mean(), 2),
            roas_mean=round(roas.mean(), 4),
            roas_low_5=round(np.quantile(roas, 0.05), 4),
            roas_high_95=round(np.quantile(roas, 0.95), 4),
            prior_beta_sd=round(prior_beta_sd[ch], 4),
            post_beta_sd=round(post_sd, 4),
            sd_ratio_post_over_prior=round(ratio, 3),
            measured=bool(ratio <= MEASURED_MAX_SD_RATIO),
            reported=bool(ratio <= REPORTED_MAX_SD_RATIO),
        ))
    return pd.DataFrame(rows)


def prior_beta_sd(mmm, cfg):
    beta = sample_prior(mmm, cfg["sampler"]["random_seed"])["saturation_beta"]
    return {ch: float(beta.sel(channel=ch).std()) for ch in cfg["channels"]}


def run_name(cfg, db_path):
    """Results folder name. A non-default database gets its own folder so it
    can never overwrite the results of the same config on the main database."""
    if db_path is None or Path(db_path).resolve().with_suffix("") == DEFAULT_DB.resolve():
        return cfg["name"]
    return f"{cfg['name']}__{Path(db_path).stem}"


def refresh_estimates(cfg, run, db_path):
    """Rewrite estimates.csv from the saved model, without resampling."""
    import arviz as az

    df = load_model_input(cfg["channels"], db_path)
    X = df[["week_start"] + cfg["channels"] + cfg["controls"]]
    mmm = build_mmm(cfg, df)
    mmm.build_model(X, df["revenue"])
    idata = az.from_netcdf(ROOT / "models" / f"{run}.nc")
    est = channel_estimates(idata, df, cfg["channels"], prior_beta_sd(mmm, cfg))
    est.to_csv(ROOT / "results" / run / "estimates.csv", index=False)
    print(est.to_string(index=False))


def main(config_path, db_cli=None, estimates_only=False, seed=None):
    cfg = json.loads(Path(config_path).read_text())
    # A config may name its own database ("database": "data/scenarios/x.duckdb").
    # --db on the command line overrides it, and only then is the run name suffixed.
    run = run_name(cfg, db_cli)
    if seed is not None:
        # Seed check: same config and data, different sampler seed, own results folder.
        cfg["sampler"]["random_seed"] = seed
        run = f"{run}__seed{seed}"
    db_path = db_cli or (str(ROOT / cfg["database"]) if cfg.get("database") else None)
    out_dir = ROOT / "results" / run
    out_dir.mkdir(parents=True, exist_ok=True)

    mode = configure_backend()
    print(f"Config: {cfg['name']}   Run: {run}   PyTensor mode: {mode}")
    if estimates_only:
        refresh_estimates(cfg, run, db_path)
        return

    df = load_model_input(cfg["channels"], db_path)
    X = df[["week_start"] + cfg["channels"] + cfg["controls"]]
    y = df["revenue"]

    mmm = build_mmm(cfg, df)
    mmm.build_model(X, y)
    beta_sd = prior_beta_sd(mmm, cfg)
    mmm.add_original_scale_contribution_variable(var=["channel_contribution", "y"])

    start = time.time()
    # The progress bar crashes on Windows when output is redirected to a file (cp1252)
    mmm.fit(X, y, progressbar=sys.stdout.isatty(), **cfg["sampler"])
    minutes = (time.time() - start) / 60
    print(f"Sampling took {minutes:.1f} minutes")

    # Fit: posterior predictive mean vs actual revenue
    pp = mmm.sample_posterior_predictive(X, random_seed=cfg["sampler"]["random_seed"])
    pred = pp["y_original_scale"]
    pred_mean = pred.mean([d for d in pred.dims if d != "date" and d != "week_start"]).to_numpy()
    actual = y.to_numpy()
    r2 = 1 - ((actual - pred_mean) ** 2).sum() / ((actual - actual.mean()) ** 2).sum()
    mape = np.mean(np.abs(actual - pred_mean) / actual)
    pd.DataFrame({"week_start": df.week_start, "actual": actual, "predicted": pred_mean.round(2)}) \
        .to_csv(out_dir / "fit.csv", index=False)

    rhats, divergences = convergence(mmm.idata)
    worst = max(rhats, key=rhats.get)
    est = channel_estimates(mmm.idata, df, cfg["channels"], beta_sd)
    est.to_csv(out_dir / "estimates.csv", index=False)
    checks = plausibility(est, float(actual.sum()))

    diagnostics = dict(
        config=cfg["name"], run=run,
        database=str(Path(db_path).resolve()) if db_path else None,
        sampling_minutes=round(minutes, 1),
        r2=round(float(r2), 4), mape=round(float(mape), 4),
        max_rhat=round(rhats[worst], 4), worst_rhat_param=worst,
        divergences=divergences,
        max_treedepth_hits_by_chain=tree_depth_hits(mmm.idata),
        converged=bool(rhats[worst] < 1.01 and divergences == 0),
        plausibility=checks,
        decomposition=decomposition(mmm.idata, len(df)),
        rhat_by_param={k: round(v, 4) for k, v in sorted(rhats.items())},
    )
    (out_dir / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))

    try:
        (ROOT / "models").mkdir(exist_ok=True)
        mmm.save(str(ROOT / "models" / f"{run}.nc"))
    except Exception as exc:  # saving is a convenience, not required
        print(f"Model not saved: {exc}")

    print(f"\nFit:  R2 {r2:.3f}   MAPE {mape:.1%}")
    print(f"Convergence:  max R-hat {rhats[worst]:.3f} ({worst})   divergences {divergences}")
    print("\nEstimated ROAS (90% interval). measured = data narrowed the beta prior;"
          " reported = measured and not borderline:")
    print(est[["channel", "roas_mean", "roas_low_5", "roas_high_95",
               "sd_ratio_post_over_prior", "measured", "reported"]].to_string(index=False))
    flag = "  FLAG" if checks["media_share_flag"] else ""
    print(f"\nPlausibility:  media share of revenue {checks['media_share_of_revenue']:.1%}{flag}")
    print(f"Wide ROAS intervals (>{MAX_INTERVAL_RATIO}x lower bound): "
          f"{', '.join(checks['wide_interval_channels']) or 'none'}")
    print(f"\nSaved to results/{run}/")


if __name__ == "__main__":   # required on Windows: sampling starts worker processes
    import argparse

    parser = argparse.ArgumentParser(description="Fit the MMM for one config.")
    parser.add_argument("config", help="configs/<name>.json")
    parser.add_argument("--db", default=None,
                        help="database file (default: the config's 'database', else "
                             "data/alert_desk). A non-default --db writes to "
                             "results/<config>__<db name>/")
    parser.add_argument("--estimates-only", action="store_true",
                        help="rewrite estimates.csv from the saved model, no sampling")
    parser.add_argument("--seed", type=int, default=None,
                        help="override the sampler seed; writes to results/<run>__seed<N>/")
    args = parser.parse_args()
    main(args.config, args.db, args.estimates_only, args.seed)
