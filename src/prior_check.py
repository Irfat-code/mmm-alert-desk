"""Prior-only check: what does a config believe before it sees revenue?

Samples the model's priors (no MCMC) and reports the media share of revenue they
imply, plus the prior moments of each parameter for later prior-vs-posterior
comparison. Reads only the weekly_model_input view, never data/truth/.

Run:  python src/prior_check.py configs/hill_spendshare.json

Writes results/<name>/prior_check.json.
"""
import json
import sys
from pathlib import Path

import numpy as np

from db import ROOT
from fit_model import (MAX_MEDIA_SHARE, PRIOR_DRAWS, build_mmm, configure_backend,
                       load_model_input, sample_prior)

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]


def moments(x):
    return dict(mean=round(float(x.mean()), 4), sd=round(float(x.std()), 4),
                q10=round(float(np.quantile(x, 0.10)), 4),
                q50=round(float(np.quantile(x, 0.50)), 4),
                q90=round(float(np.quantile(x, 0.90)), 4),
                q95=round(float(np.quantile(x, 0.95)), 4))


def main(config_path, db=None):
    cfg = json.loads(Path(config_path).read_text())
    out_dir = ROOT / "results" / cfg["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    configure_backend()

    # Same database rule as fit_model.py: --db, else the config's own, else the default.
    db_path = db or (str(ROOT / cfg["database"]) if cfg.get("database") else None)
    df = load_model_input(cfg["channels"], db_path)
    X = df[["week_start"] + cfg["channels"] + cfg["controls"]]
    y = df["revenue"]
    mmm = build_mmm(cfg, df)
    mmm.build_model(X, y)

    prior = sample_prior(mmm, cfg["sampler"]["random_seed"])

    target_scale = float(mmm.scalers["_target"])
    total_revenue = float(y.sum())
    media = prior["channel_contribution"]
    media = media.sum([d for d in media.dims if d != "sample"]).to_numpy() * target_scale
    share = media / total_revenue

    params = {}
    for name in prior.data_vars:
        var = prior[name]
        if any(d in var.dims for d in ("date", "week_start")) or name.startswith("y"):
            continue
        extra = [d for d in var.dims if d != "sample"]
        if not extra:
            params[name] = moments(var.to_numpy())
        else:
            key = extra[0]
            params[name] = {str(k): moments(var.sel({key: k}).to_numpy())
                            for k in var[key].to_numpy()}

    # ROAS a channel would reach at full saturation: beta * target_scale / weekly spend
    beta = prior["saturation_beta"]
    roas_ceiling = {}
    for ch in cfg["channels"]:
        weekly_spend = float(df[ch].mean())
        ceiling = beta.sel(channel=ch).to_numpy() * target_scale / weekly_spend
        roas_ceiling[ch] = dict(weekly_spend=round(weekly_spend, 2),
                                q50=round(float(np.quantile(ceiling, 0.5)), 2),
                                q95=round(float(np.quantile(ceiling, 0.95)), 2))

    result = dict(
        config=cfg["name"], draws=PRIOR_DRAWS, total_revenue=round(total_revenue, 2),
        media_share_quantiles={str(q): round(float(np.quantile(share, q)), 4) for q in QUANTILES},
        prob_media_share_above_threshold=round(float((share > MAX_MEDIA_SHARE).mean()), 4),
        prob_media_share_above_1=round(float((share > 1).mean()), 4),
        media_share_threshold=MAX_MEDIA_SHARE,
        target_scale=round(target_scale, 2),
        prior_roas_at_full_saturation=roas_ceiling,
        prior_moments=params,
    )
    (out_dir / "prior_check.json").write_text(json.dumps(result, indent=2))
    return result

    q = result["media_share_quantiles"]
    print(f"{cfg['name']}: prior media share median {q['0.5']:.1%} "
          f"(90% interval {q['0.05']:.1%} to {q['0.95']:.1%})   "
          f"P(>{MAX_MEDIA_SHARE:.0%}) {result['prob_media_share_above_threshold']:.1%}   "
          f"P(>100%) {result['prob_media_share_above_1']:.1%}")
    print("Prior ROAS at full saturation (median / 95th pct): " + ", ".join(
        f"{ch} {r['q50']} / {r['q95']}" for ch, r in roas_ceiling.items()))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/prior_check.py configs/<name>.json")
    main(sys.argv[1])
