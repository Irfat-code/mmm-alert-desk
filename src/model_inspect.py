"""What did a fitted model assume, compared with the baseline? Reads only models/<run>.nc.

Run:  python src/model_inspect.py scenario_E

The saved model carries its own spec (priors, sampler settings, adstock and saturation
functions, columns, scaling) as attributes. This is what an analyst can always inspect
from a fitted model, without the config file.

Writes to results/investigations/<run>/:
    model_spec_diff.csv     every spec entry that differs between baseline and run
    sampler_stats.csv       draws, tuning, acceptance, step size, tree depth, divergences
    posterior_structure.csv posterior variables and their dims, and whether they match
"""
import json
import sys

import arviz as az
import numpy as np
import pandas as pd

from db import ROOT

SPEC_KEYS = ["adstock", "saturation", "adstock_first", "channel_columns", "control_columns",
             "scaling", "yearly_seasonality", "time_varying_intercept", "time_varying_media",
             "model_config", "sampler_config", "version"]


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = json.dumps(obj, sort_keys=True) if isinstance(obj, (list, tuple)) else obj
    return out


def spec(idata):
    flat = {}
    for k in SPEC_KEYS:
        v = idata.attrs.get(k)
        try:
            v = json.loads(v) if isinstance(v, str) else v
        except json.JSONDecodeError:
            pass
        flat.update(flatten(v, k))
    return flat


def ds(group):
    return group.to_dataset() if hasattr(group, "to_dataset") else group


def main(run, baseline="baseline"):
    out = ROOT / "results" / "investigations" / run
    out.mkdir(parents=True, exist_ok=True)
    ids = {name: az.from_netcdf(ROOT / "models" / f"{name}.nc") for name in (baseline, run)}

    sb, sr = spec(ids[baseline]), spec(ids[run])
    rows = [dict(key=k, baseline=str(sb.get(k)), run=str(sr.get(k)))
            for k in sorted(set(sb) | set(sr)) if str(sb.get(k)) != str(sr.get(k))]
    pd.DataFrame(rows, columns=["key", "baseline", "run"]).to_csv(out / "model_spec_diff.csv", index=False)

    stats = []
    for name, idata in ids.items():
        ss = ds(idata.sample_stats)
        stats.append(dict(
            run=name, chains=ss.sizes["chain"], draws=ss.sizes["draw"],
            tuning_steps=int(ss.attrs.get("tuning_steps", -1)),
            acceptance_rate_mean=float(ss["acceptance_rate"].mean()),
            step_size_mean=float(ss["step_size"].mean()),
            tree_depth_mean=float(ss["tree_depth"].mean()),
            tree_depth_max=int(ss["tree_depth"].max()),
            max_treedepth_hits=int(ss["reached_max_treedepth"].sum()),
            divergences=int(ss["diverging"].sum()),
            divergences_by_chain=json.dumps(ss["diverging"].sum("draw").to_numpy().tolist()),
        ))
    pd.DataFrame(stats).to_csv(out / "sampler_stats.csv", index=False)

    struct = []
    pb, pr = ds(ids[baseline].posterior), ds(ids[run].posterior)
    for v in sorted(set(pb.data_vars) | set(pr.data_vars)):
        db = dict(pb[v].sizes) if v in pb else None
        dr = dict(pr[v].sizes) if v in pr else None
        struct.append(dict(var=v, dims_base=str(db), dims_run=str(dr), same=db == dr))
    pd.DataFrame(struct).to_csv(out / "posterior_structure.csv", index=False)
    print(f"Saved model_spec_diff ({len(rows)} differing keys), sampler_stats, posterior_structure")


if __name__ == "__main__":
    main(sys.argv[1])
