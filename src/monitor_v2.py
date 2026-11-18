"""Monitor v2: pre-fit gates and post-fit alerts. Never reads data/truth/.

Run:  python src/monitor_v2.py calibrate     # metric values on the clean seed runs
      python src/monitor_v2.py refresh       # shift metrics: normal refresh vs seeds vs scenarios
      python src/monitor_v2.py scorecard     # every run: gates, alerts, first catch
      python src/monitor_v2.py rejected_cac  # evidence for the rejected two-way CAC rule

PRE-FIT GATES (run on the database and config before fitting; any gate blocks the fit):
    freshness        sources' MAX(date) agree and the latest week is complete in both
    reconciliation   raw spend total = model input spend total
    new_campaigns    every campaign_id in the data was in the last approved snapshot
    calendar         every promo/holiday row in the last approved snapshot is unchanged
    spec             config matches the live config (ignoring name, description,
                     database); otherwise it needs a changelog heading naming it AND a
                     prior check with P(prior media share > 80%) <= PRIOR_P80_MAX
    rows_absent      check 03 rows labelled 'rows absent': a launched channel with no raw
                     rows at all for a week (typical of a feed outage)

POST-FIT ALERTS (run on results/ and models/ against the baseline run):
    roas_shift       as monitor v1 (measured channels, > 25% and outside the interval)
    control_shift    a control coefficient's 90% interval stops overlapping baseline's
    convergence      divergences > MAX_DIVERGENCES or max R-hat > 1.01
    spend_zero       check 03 rows labelled 'spend zero': rows present, spend zero

WATCH (computed and shown in every run's report; never blocks, never alerts).
Provisional, calibrated on 1 refresh sample; recalibrate after 3 real monthly runs:
    param_shift      a media parameter's mean moves > PARAM_SHIFT_Z baseline posterior sds
    residual_shift   a week's residual moves > RESIDUAL_SHIFT_PTS points against baseline's
                     (cannot separate scenario E from a normal month: 0.91 vs 1.60 pts)

Rejected: two-way CAC (see configs/CHANGELOG.md).

The last approved snapshot is the clean production database (data/alert_desk.duckdb).
Thresholds marked CALIBRATED are set above the worst clean-seed value (see calibrate).
"""
import json
import re
import sys

import arviz as az
import duckdb
import numpy as np
import pandas as pd

from db import ROOT
from monitor import load_run, roas_alerts

SNAPSHOT_DB = ROOT / "data" / "alert_desk.duckdb"
BASE_CONFIG = ROOT / "configs" / "baseline.json"
BASE_RUN = "baseline"
CLEAN = ["baseline__seed20261118", "baseline__seed7", "baseline__seed31337"]
SCENARIOS = ["scenario_A", "scenario_B", "scenario_C", "scenario_D", "scenario_E", "scenario_F"]

# ---- Thresholds ---------------------------------------------------------------
MAX_RHAT = 1.01
PRIOR_P80_MAX = 0.10           # live baseline: 0.0585; its priors were set for about 5%
CALIBRATION_MARGIN = 2.0       # thresholds = margin x worst clean-seed value
MAX_DIVERGENCES = 8            # CALIBRATED: clean max 4 (seed 7), 2x margin
PARAM_SHIFT_Z = 0.70           # WATCH, provisional: 2x normal refresh (0.350 sd); clean seeds max 0.062
RESIDUAL_SHIFT_PTS = 3.2       # WATCH, provisional: 2x normal refresh (1.60 pts); clean seeds max 0.329
SPEC_IGNORE = {"name", "description", "database"}
# -------------------------------------------------------------------------------


def run_inputs(run):
    """Config and database a run was fitted from."""
    if run.startswith("baseline"):
        return BASE_CONFIG, SNAPSHOT_DB
    return ROOT / "configs" / f"{run}.json", ROOT / "data" / "scenarios" / f"{run}.duckdb"


def ds(g):
    return g.to_dataset() if hasattr(g, "to_dataset") else g


def q(con, sql):
    return con.execute(sql).df()


# ---- Gates ----------------------------------------------------------------------

def gate_freshness(con):
    m = q(con, """SELECT (SELECT MAX(date) FROM raw_ad_spend) AS ad,
                         (SELECT MAX(date) FROM shopify_orders_daily) AS sales""").iloc[0]
    if m.ad != m.sales:
        return f"MAX(date) differ: ad spend {str(m.ad)[:10]}, sales {str(m.sales)[:10]}"
    last = q(con, """SELECT d.week_start,
                            (SELECT COUNT(DISTINCT s.date) FROM raw_ad_spend s JOIN dim_date d2
                               ON d2.date = s.date WHERE d2.week_start = d.week_start) AS ad_days,
                            (SELECT COUNT(DISTINCT o.date) FROM shopify_orders_daily o JOIN dim_date d3
                               ON d3.date = o.date WHERE d3.week_start = d.week_start) AS sales_days
                     FROM dim_date d
                     WHERE d.date = (SELECT MAX(date) FROM raw_ad_spend)""").iloc[0]
    if last.ad_days < 7 or last.sales_days < 7:
        return f"latest week {str(last.week_start)[:10]} incomplete: ad {last.ad_days} days, sales {last.sales_days} days"
    return None


def gate_reconciliation(con):
    r = q(con, """SELECT (SELECT SUM(spend) FROM raw_ad_spend) AS raw,
                         (SELECT SUM(meta_spend + google_spend + tiktok_spend + email_spend)
                            FROM weekly_model_input) AS model""").iloc[0]
    gap = float(r.raw - r.model)
    return f"raw spend - model spend = {gap:,.2f}" if abs(gap) > 0.01 else None


def gate_new_campaigns(con, snap):
    seen = set(q(snap, "SELECT campaign_id FROM campaign_channel_map").campaign_id)
    ids = set(q(con, """SELECT DISTINCT campaign_id FROM raw_ad_spend
                        UNION SELECT campaign_id FROM campaign_channel_map""").campaign_id)
    new = sorted(ids - seen)
    if not new:
        return None
    info = q(con, f"""SELECT m.campaign_id, m.campaign_name, m.channel FROM campaign_channel_map m
                      WHERE m.campaign_id IN ({",".join(str(i) for i in new)})""")
    return "unreviewed campaign_id(s): " + "; ".join(
        f"{r.campaign_id} {r.campaign_name} -> {r.channel}" for r in info.itertuples())


def gate_calendar(con, snap):
    msgs = []
    for t in ("promo_calendar", "holiday_calendar"):
        a, b = q(snap, f"SELECT * FROM {t}"), q(con, f"SELECT * FROM {t}")
        m = a.merge(b, how="left", indicator=True)
        gone = m[m._merge == "left_only"]
        if len(gone):
            msgs.append(f"{t}: {len(gone)} approved row(s) missing or changed: "
                        + "; ".join(str(r) for r in gone.drop(columns="_merge").to_dict("records")))
    return " | ".join(msgs) or None


def flat(obj, prefix=""):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out.update(flat(v, f"{prefix}.{k}" if prefix else k))
        return out
    return {prefix: json.dumps(obj)}


def gate_spec(config_path, db_path):
    cfg = json.loads(config_path.read_text())
    a = {k: v for k, v in flat(json.loads(BASE_CONFIG.read_text())).items() if k.split(".")[0] not in SPEC_IGNORE}
    b = {k: v for k, v in flat(cfg).items() if k.split(".")[0] not in SPEC_IGNORE}
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    if not diff:
        return None
    changelog = (ROOT / "configs" / "CHANGELOG.md").read_text(encoding="utf-8")
    logged = bool(re.search(rf"^##.*\b{re.escape(cfg['name'])}\b", changelog, flags=re.M))
    import prior_check
    p80 = prior_check.main(str(config_path), str(db_path))["prob_media_share_above_threshold"]
    problems = ([] if logged else ["no changelog entry"]) + \
               ([] if p80 <= PRIOR_P80_MAX else [f"prior P(media share > 80%) = {p80:.1%} > {PRIOR_P80_MAX:.0%}"])
    if not problems:
        return None
    return f"config differs from live ({', '.join(diff)}): " + "; ".join(problems)


def gates(run):
    config_path, db_path = run_inputs(run)
    con = duckdb.connect(str(db_path), read_only=True)
    snap = duckdb.connect(str(SNAPSHOT_DB), read_only=True)
    out = dict(freshness=gate_freshness(con), reconciliation=gate_reconciliation(con),
               new_campaigns=gate_new_campaigns(con, snap), calendar=gate_calendar(con, snap),
               rows_absent=check03(con, "rows absent"))
    con.close()
    snap.close()
    out["spec"] = gate_spec(config_path, db_path)
    return out


def check03(con, issue):
    """Check 03 rows of one kind: 'rows absent' (gate) or 'spend zero' (alert)."""
    rows = q(con, (ROOT / "sql" / "checks" / "03_channel_zero_weeks.sql").read_text())
    rows = rows[rows.issue == issue]
    if not len(rows):
        return None
    return "; ".join(f"{r.channel} {str(r.week_start)[:10]} ({r.issue})" for r in rows.itertuples())


# ---- Alert metrics --------------------------------------------------------------

def posterior(run):
    return ds(az.from_netcdf(ROOT / "models" / f"{run}.nc").posterior)


def interval(x):
    return np.quantile(x, 0.05), np.quantile(x, 0.95)


def metric_values(run, ref_post, ref_run=BASE_RUN, exclude_latest=0):
    """Raw values behind the threshold rules, run against a reference run.
    Residuals are compared on the weeks both runs share, minus the latest
    `exclude_latest` of those weeks. Parameter shift is in reference posterior sds."""
    post = posterior(run)
    z_rows = []
    for v in ("adstock_alpha", "saturation_lam", "saturation_beta"):
        b, r = ref_post[v].stack(s=("chain", "draw")), post[v].stack(s=("chain", "draw"))
        for ch in b.channel.values:
            bb, rr = b.sel(channel=ch).to_numpy(), r.sel(channel=ch).to_numpy()
            z_rows.append((abs(rr.mean() - bb.mean()) / bb.std(), f"{v}:{ch}"))
    z, z_where = max(z_rows)
    f = {n: pd.read_csv(ROOT / "results" / n / "fit.csv") for n in (ref_run, run)}
    m = f[ref_run].merge(f[run], on="week_start", suffixes=("_b", "_r")).sort_values("week_start")
    if exclude_latest:
        m = m.iloc[:-exclude_latest]
    m = m.reset_index(drop=True)
    d = ((m.actual_r / m.predicted_r - 1) - (m.actual_b / m.predicted_b - 1)).abs() * 100
    diag = json.loads((ROOT / "results" / run / "diagnostics.json").read_text())
    return dict(param_shift_z=float(z), param_shift_where=z_where,
                residual_shift_pts=float(d.max()), residual_shift_week=m.week_start[d.idxmax()],
                overlap_weeks=len(m),
                divergences=int(diag["divergences"]), max_rhat=float(diag["max_rhat"]))


def alert_control_shift(run, base_post):
    post = posterior(run)
    b, r = base_post["gamma_control"].stack(s=("chain", "draw")), post["gamma_control"].stack(s=("chain", "draw"))
    hits = []
    for c in b.control.values:
        (bl, bh), (rl, rh) = interval(b.sel(control=c).to_numpy()), interval(r.sel(control=c).to_numpy())
        if rh < bl or bh < rl:
            hits.append(f"{c}: {b.sel(control=c).mean():.4f} -> {r.sel(control=c).mean():.4f}")
    return "; ".join(hits) or None


def alerts(run, base_post):
    """Adopted alerts, plus the WATCH tier (shown, never alerting)."""
    _, db_path = run_inputs(run)
    _, base_est = load_run(BASE_RUN)
    _, new_est = load_run(run)
    roas = roas_alerts(base_est, new_est)
    mv = metric_values(run, base_post)
    con = duckdb.connect(str(db_path), read_only=True)
    zero = check03(con, "spend zero")
    con.close()
    adopted = dict(
        roas_shift="; ".join(f"{a[1]} {a[2]} -> {a[3]}" for a in roas) or None,
        control_shift=alert_control_shift(run, base_post),
        convergence=(f"{mv['divergences']} divergences, max R-hat {mv['max_rhat']}"
                     if mv["divergences"] > MAX_DIVERGENCES or mv["max_rhat"] > MAX_RHAT else None),
        spend_zero=zero,
    )
    watch = dict(
        param_shift=(f"{mv['param_shift_where']} moved {mv['param_shift_z']:.2f} sd"
                     if mv["param_shift_z"] > PARAM_SHIFT_Z else None),
        residual_shift=(f"week {mv['residual_shift_week']} moved {mv['residual_shift_pts']:.2f} pts"
                        if mv["residual_shift_pts"] > RESIDUAL_SHIFT_PTS else None),
    )
    return adopted, watch, mv


# ---- Modes ------------------------------------------------------------------------

def calibrate():
    base_post = posterior(BASE_RUN)
    rows = [dict(run=r, **metric_values(r, base_post)) for r in CLEAN]
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "monitor_v2_calibration.csv", index=False)
    print(df.to_string(index=False))
    for k in ("param_shift_z", "residual_shift_pts", "divergences"):
        print(f"{k}: clean max {df[k].max():.3f} -> threshold at {CALIBRATION_MARGIN}x = {df[k].max() * CALIBRATION_MARGIN:.3f}")


REFRESH_NEW, REFRESH_OLD = "baseline", "baseline__baseline_minus4w"


def refresh():
    """Shift metrics for a normal monthly refresh (this month's baseline against last
    month's 152-week fit), next to the clean seeds and the scenarios, each on the
    overlapping weeks: all of them, and without the latest 4 and 8."""
    base_post, old_post = posterior(BASE_RUN), posterior(REFRESH_OLD)
    rows = []
    for kind, run, ref_post, ref_run in (
            [("refresh", REFRESH_NEW, old_post, REFRESH_OLD)]
            + [("clean seed", r, base_post, BASE_RUN) for r in CLEAN]
            + [("scenario", r, base_post, BASE_RUN) for r in SCENARIOS]):
        for excl in (0, 4, 8):
            mv = metric_values(run, ref_post, ref_run, exclude_latest=excl)
            rows.append(dict(kind=kind, run=run, against=ref_run, exclude_latest_weeks=excl,
                             overlap_weeks=mv["overlap_weeks"],
                             param_shift_z=round(mv["param_shift_z"], 3), param_shift_where=mv["param_shift_where"],
                             residual_shift_pts=round(mv["residual_shift_pts"], 2),
                             residual_shift_week=mv["residual_shift_week"]))
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "monitor_v2_refresh_test.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


def scorecard():
    base_post = posterior(BASE_RUN)
    rows = []
    for run in CLEAN + SCENARIOS:
        g = gates(run)
        a, watch, mv = alerts(run, base_post)
        fired_g = [k for k, v in g.items() if v]
        fired_a = [k for k, v in a.items() if v]
        rows.append(dict(
            run=run, clean=run in CLEAN,
            gates_fired=";".join(fired_g), alerts_fired=";".join(fired_a),
            caught=("before fit (gate)" if fired_g else "after fit (alert)" if fired_a else "not caught"),
            watch_flags=";".join(k for k, v in watch.items() if v),
            **{f"gate_{k}": v for k, v in g.items()},
            **{f"alert_{k}": v for k, v in a.items()},
            **{f"watch_{k}": v for k, v in watch.items()},
            param_shift_z=round(mv["param_shift_z"], 3), residual_shift_pts=round(mv["residual_shift_pts"], 2),
            divergences=mv["divergences"],
        ))
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "monitor_v2_scorecard.csv", index=False)
    pd.set_option("display.width", 250)
    print(df[["run", "gates_fired", "alerts_fired", "caught", "watch_flags"]].to_string(index=False))


def rejected_cac():
    """Evidence for the REJECTED two-way CAC rule: CAC on complete weeks, latest 2 vs
    the 12 before, on every run's database. Saved so the changelog can cite it."""
    sql = """WITH ad AS (SELECT d.week_start, COUNT(DISTINCT s.date) AS n FROM raw_ad_spend s
                         JOIN dim_date d ON d.date = s.date GROUP BY d.week_start),
                  od AS (SELECT d.week_start, COUNT(DISTINCT o.date) AS n FROM shopify_orders_daily o
                         JOIN dim_date d ON d.date = o.date GROUP BY d.week_start)
             SELECT mi.week_start,
                    mi.meta_spend + mi.google_spend + mi.tiktok_spend + mi.email_spend AS spend,
                    mi.new_customers
             FROM weekly_model_input mi
             JOIN ad ON ad.week_start = mi.week_start
             JOIN od ON od.week_start = mi.week_start
             WHERE ad.n = 7 AND od.n = 7
             ORDER BY mi.week_start"""
    rows = []
    for run in CLEAN + SCENARIOS:
        con = duckdb.connect(str(run_inputs(run)[1]), read_only=True)
        w = q(con, sql)
        con.close()
        recent, trailing = w.tail(2), w.iloc[-14:-2]
        change = (recent.spend.sum() / recent.new_customers.sum()) / (
            trailing.spend.sum() / trailing.new_customers.sum()) - 1
        rows.append(dict(run=run, clean=run in CLEAN, cac_change_latest2_vs_12=round(change, 4),
                         would_fire_at_30pct=abs(change) > 0.30))
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "monitor_v2_rejected_cac.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    {"calibrate": calibrate, "refresh": refresh, "scorecard": scorecard, "rejected_cac": rejected_cac}[sys.argv[1]]()
