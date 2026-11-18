"""Compare a run against the baseline and add any alerts to alerts/queue.csv.

Reads results/<run>/ and results/baseline/, plus the run's database for the CAC and
data checks. Never reads data/truth/.

Run:  python src/monitor.py <run>
      python src/monitor.py <run> --db data/other.duckdb --baseline baseline

The database defaults to the one recorded in results/<run>/diagnostics.json,
and to data/alert_desk if none is recorded.

Alert types:
    fit_drop          R2 falls by more than R2_MAX_DROP, or MAPE rises by more than MAPE_MAX_RISE
    roas_shift        a channel measured in both runs: mean ROAS moves by more than
                      ROAS_MAX_SHIFT AND the new mean is outside the baseline's 90% interval
    cac_spike         CAC over the latest CAC_RECENT_WEEKS is more than CAC_MAX_RISE above
                      CAC over the CAC_TRAILING_WEEKS before them. Both are pooled
                      (total spend / total new customers). baseline_value is the trailing CAC.
    convergence       max R-hat above MAX_RHAT, or more than MAX_DIVERGENCES divergences
    plausibility      media share above MAX_MEDIA_SHARE, or a negative intercept
    data_check        any query in sql/checks/ returns rows. 03_channel_zero_weeks only
                      counts weeks after a channel's first spend (the query does this).
                      baseline_value is the row count on the baseline's database.

Re-running the monitor does not duplicate an alert that is already in the queue.
"""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

import fit_model
from db import DEFAULT_DB, ROOT, Database

# ---- Thresholds -------------------------------------------------------------
R2_MAX_DROP = 0.05           # R2 may fall by at most this much
MAPE_MAX_RISE = 0.02         # MAPE may rise by at most 2 percentage points
ROAS_MAX_SHIFT = 0.25        # relative change in mean ROAS, measured channels only
CAC_MAX_RISE = 0.30          # latest CAC may be at most 30% above the trailing CAC
CAC_RECENT_WEEKS = 2
CAC_TRAILING_WEEKS = 12
MAX_RHAT = 1.01
MAX_DIVERGENCES = 0
MAX_MEDIA_SHARE = fit_model.MAX_MEDIA_SHARE   # 0.80, same value as the fit's plausibility check
MIN_INTERCEPT_PER_WEEK = 0.0
# -----------------------------------------------------------------------------

QUEUE = ROOT / "alerts" / "queue.csv"
COLUMNS = ["alert_id", "run", "alert_type", "metric", "baseline_value", "new_value", "raised_date"]


def load_run(name):
    out = ROOT / "results" / name
    diag = json.loads((out / "diagnostics.json").read_text())
    est = pd.read_csv(out / "estimates.csv").set_index("channel")
    return diag, est


def db_for(diag, override=None):
    return Path(override) if override else Path(diag.get("database") or DEFAULT_DB)


def fit_alerts(base, new):
    alerts = []
    if new["r2"] < base["r2"] - R2_MAX_DROP:
        alerts.append(("fit_drop", "r2", base["r2"], new["r2"]))
    if new["mape"] > base["mape"] + MAPE_MAX_RISE:
        alerts.append(("fit_drop", "mape", base["mape"], new["mape"]))
    return alerts


def roas_alerts(base_est, new_est):
    alerts = []
    for ch in base_est.index.intersection(new_est.index):
        b, n = base_est.loc[ch], new_est.loc[ch]
        if not (b.measured and n.measured):
            continue
        shift = abs(n.roas_mean / b.roas_mean - 1)
        outside = n.roas_mean < b.roas_low_5 or n.roas_mean > b.roas_high_95
        if shift > ROAS_MAX_SHIFT and outside:
            alerts.append(("roas_shift", f"roas_mean:{ch}", b.roas_mean, n.roas_mean))
    return alerts


def cac_alerts(db):
    weekly = db.query_file(ROOT / "sql" / "monitor" / "weekly_cac.sql")
    needed = CAC_RECENT_WEEKS + CAC_TRAILING_WEEKS
    if len(weekly) < needed:
        return []
    recent = weekly.tail(CAC_RECENT_WEEKS)
    trailing = weekly.iloc[-needed:-CAC_RECENT_WEEKS]
    cac_recent = recent.spend.sum() / recent.new_customers.sum()
    cac_trailing = trailing.spend.sum() / trailing.new_customers.sum()
    if cac_recent > cac_trailing * (1 + CAC_MAX_RISE):
        return [("cac_spike", f"cac_latest_{CAC_RECENT_WEEKS}w_vs_trailing_{CAC_TRAILING_WEEKS}w",
                 round(cac_trailing, 2), round(cac_recent, 2))]
    return []


def convergence_alerts(base, new):
    alerts = []
    if new["max_rhat"] > MAX_RHAT:
        alerts.append(("convergence", "max_rhat", base["max_rhat"], new["max_rhat"]))
    if new["divergences"] > MAX_DIVERGENCES:
        alerts.append(("convergence", "divergences", base["divergences"], new["divergences"]))
    return alerts


def plausibility_alerts(base, new):
    alerts = []
    b_share = base["plausibility"]["media_share_of_revenue"]
    n_share = new["plausibility"]["media_share_of_revenue"]
    if n_share > MAX_MEDIA_SHARE:
        alerts.append(("plausibility", "media_share", b_share, n_share))
    b_int = base["decomposition"]["intercept_per_week"]
    n_int = new["decomposition"]["intercept_per_week"]
    if n_int < MIN_INTERCEPT_PER_WEEK:
        alerts.append(("plausibility", "intercept_per_week", b_int, n_int))
    return alerts


def check_counts(db):
    return {p.stem: len(db.query_file(p)) for p in sorted((ROOT / "sql" / "checks").glob("*.sql"))}


def data_alerts(base_db, run_db):
    base_counts, run_counts = check_counts(base_db), check_counts(run_db)
    return [("data_check", f"rows:{name}", base_counts.get(name, 0), rows)
            for name, rows in run_counts.items() if rows > 0]


def append_to_queue(run, alerts, raised, queue_path=QUEUE):
    queue_path.parent.mkdir(exist_ok=True)
    queue = pd.read_csv(queue_path) if queue_path.exists() else pd.DataFrame(columns=COLUMNS)
    seen = {(r.run, r.alert_type, r.metric, float(r.new_value)) for r in queue.itertuples()}
    next_id = len(queue) + 1
    rows = []
    for alert_type, metric, base_value, new_value in alerts:
        if (run, alert_type, metric, float(new_value)) in seen:
            continue
        rows.append(dict(alert_id=f"A{next_id:03d}", run=run, alert_type=alert_type,
                         metric=metric, baseline_value=base_value, new_value=new_value,
                         raised_date=raised))
        next_id += 1
    if rows or not queue_path.exists():
        pd.concat([queue, pd.DataFrame(rows, columns=COLUMNS)]).to_csv(queue_path, index=False)
    return rows


def main(run, baseline="baseline", db_override=None, raised=None, queue_path=QUEUE):
    base_diag, base_est = load_run(baseline)
    new_diag, new_est = load_run(run)
    base_db = Database(db_for(base_diag))
    run_db = Database(db_for(new_diag, db_override))

    alerts = (fit_alerts(base_diag, new_diag)
              + roas_alerts(base_est, new_est)
              + cac_alerts(run_db)
              + convergence_alerts(base_diag, new_diag)
              + plausibility_alerts(base_diag, new_diag)
              + data_alerts(base_db, run_db))
    base_db.close()
    run_db.close()

    added = append_to_queue(run, alerts, raised or date.today().isoformat(), Path(queue_path))
    print(f"Run {run} vs {baseline}: {len(alerts)} alert(s) fired, {len(added)} new in {queue_path}")
    for a in alerts:
        print(f"   {a[0]:<13} {a[1]:<40} baseline {a[2]}   new {a[3]}")
    return alerts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare a run against the baseline.")
    parser.add_argument("run", help="results/<run>/ to check")
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--db", default=None, help="database for CAC and data checks")
    parser.add_argument("--raised", default=None, help="raised_date (default today)")
    parser.add_argument("--queue", default=QUEUE, help="queue file (default alerts/queue.csv)")
    args = parser.parse_args()
    main(args.run, args.baseline, args.db, args.raised, args.queue)
