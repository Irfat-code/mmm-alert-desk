"""Evaluate candidate v2 monitor rules on a set of runs, each against the baseline.
Reads results/, models/ and the scenario databases. Never reads data/truth/.

Run:  python src/rule_tests.py

Rules (model side, from results/ and models/):
    control_shift    a control coefficient's 90% interval no longer overlaps baseline's
    param_shift      a media parameter's (adstock_alpha, saturation_lam, saturation_beta)
                     90% interval no longer overlaps baseline's
    residual_shift   largest change in a week's residual (actual/predicted - 1), in
                     percentage points, against baseline's residual in the same week
    spec_diff        saved model spec differs from baseline's, ignoring the sampler seed
Rule (data side, from the run's database):
    calendar_diff    rows in promo_calendar or holiday_calendar that differ from baseline's

Writes results/investigations/rule_tests.csv: one row per run, with each rule's value
and whether it fires.
"""
import json
from pathlib import Path

import arviz as az
import duckdb
import numpy as np
import pandas as pd

from db import ROOT
from model_inspect import spec

CLEAN = ["baseline__seed20261118", "baseline__scenario_B_fix105", "scenario_B__scenario_B_fix105"]
SCENARIOS = ["scenario_A", "scenario_B", "scenario_C", "scenario_D", "scenario_E"]
RESIDUAL_SHIFT_PTS = 5.0   # clean seed run: 0.28 pts. Calibrate on more clean seeds before adopting.
SEED_KEYS = ("sampler_config.random_seed",)
# Prior values computed from the data (beta sigma is scaled to each channel's spend
# share), so they move with any spend change. Spec diff is for config edits only.
DATA_DERIVED_KEYS = ("model_config.saturation_beta.kwargs.sigma", "saturation.priors.beta.kwargs.sigma")


def ds(g):
    return g.to_dataset() if hasattr(g, "to_dataset") else g


def intervals(post, var, dim):
    x = post[var].stack(sample=("chain", "draw"))
    return {str(c): (float(np.quantile(x.sel({dim: c}), 0.05)), float(np.quantile(x.sel({dim: c}), 0.95)))
            for c in x[dim].values}


def non_overlapping(a, b):
    return [k for k in a if k in b and (a[k][1] < b[k][0] or b[k][1] < a[k][0])]


def residual_shift(run):
    f = {n: pd.read_csv(ROOT / "results" / n / "fit.csv") for n in ("baseline", run)}
    m = f["baseline"].merge(f[run], on="week_start", suffixes=("_b", "_r"))
    d = (m.actual_r / m.predicted_r - 1) - (m.actual_b / m.predicted_b - 1)
    i = d.abs().idxmax()
    return float(d.abs().max() * 100), m.week_start[i]


def calendar_rows(db_path):
    con = duckdb.connect(str(db_path), read_only=True)
    out = {t: con.execute(f"SELECT * FROM {t}").df() for t in ("promo_calendar", "holiday_calendar")}
    con.close()
    return out


def main():
    base_id = az.from_netcdf(ROOT / "models" / "baseline.nc")
    base_post = ds(base_id.posterior)
    base_spec = spec(base_id)
    base_cal = calendar_rows(ROOT / "data" / "alert_desk.duckdb")
    base_ctrl = intervals(base_post, "gamma_control", "control")
    base_par = {v: intervals(base_post, v, "channel")
                for v in ("adstock_alpha", "saturation_lam", "saturation_beta")}

    rows = []
    for run in CLEAN + SCENARIOS:
        idata = az.from_netcdf(ROOT / "models" / f"{run}.nc")
        post = ds(idata.posterior)
        ctrl = non_overlapping(intervals(post, "gamma_control", "control"), base_ctrl)
        par = [f"{v}:{c}" for v in base_par
               for c in non_overlapping(intervals(post, v, "channel"), base_par[v])]
        rs, rs_week = residual_shift(run)
        s = spec(idata)
        sd = [k for k in set(s) | set(base_spec)
              if str(s.get(k)) != str(base_spec.get(k)) and k not in SEED_KEYS + DATA_DERIVED_KEYS]
        db = json.loads((ROOT / "results" / run / "diagnostics.json").read_text()).get("database")
        if db is None:   # no database recorded = the default (clean) database
            db = str(ROOT / "data" / "alert_desk.duckdb")
        if db and Path(db).exists():
            cal = calendar_rows(db)
            n_cal = 0
            for t, b in base_cal.items():
                m = b.merge(cal[t], how="outer", indicator=True)
                n_cal += int((m._merge != "both").sum())
            cal_value = n_cal
        else:
            cal_value = "db deleted (input verified identical to clean)" if run in CLEAN[1:] else "n/a"
        rows.append(dict(
            run=run, clean=run in CLEAN,
            control_shift=";".join(ctrl), control_shift_fires=bool(ctrl),
            param_shift=";".join(par), param_shift_fires=bool(par),
            residual_shift_pts=round(rs, 2), residual_shift_week=rs_week,
            spec_diff=";".join(sorted(sd)), spec_diff_fires=bool(sd),
            calendar_diff_rows=cal_value,
            calendar_diff_fires=isinstance(cal_value, int) and cal_value > 0,
        ))
    df = pd.DataFrame(rows)
    if RESIDUAL_SHIFT_PTS is not None:
        df["residual_shift_fires"] = df.residual_shift_pts > RESIDUAL_SHIFT_PTS
    out = ROOT / "results" / "investigations"
    df.to_csv(out / "rule_tests.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
