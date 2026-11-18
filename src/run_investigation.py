"""Run the named queries in sql/investigations/<scenario>.sql on the scenario
database and the clean baseline database, and save each result.

Run:  python src/run_investigation.py scenario_C

Output: results/investigations/<scenario>/<query name>__<scenario|baseline>.csv
Never reads data/truth/. Opens both databases read-only.
"""
import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def split_queries(text):
    """Return {name: sql} from '-- name: x' markers. Comment lines are kept."""
    parts = re.split(r"^-- name:\s*(\S+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip().rstrip(";") for i in range(1, len(parts), 2)}


# Queries diffed row by row against baseline on these keys -> <name>_diff.csv
KEYED_DIFFS = {
    "channel_week": ["channel", "week_start"],
    "sales_week": ["sales_channel", "week_start"],
    "model_input_full": ["week_start"],
}
RAW_TABLES = ["dim_date", "raw_ad_spend", "campaign_channel_map", "shopify_orders_daily",
              "holiday_calendar", "promo_calendar"]


def checks_and_tables(dbs, out):
    """Every sql/checks/ query on both databases (row counts), and a full row-level
    diff of every raw table against baseline (rows only on one side)."""
    counts, frames = [], {}
    for label, path in dbs.items():
        con = duckdb.connect(str(path), read_only=True)
        for p in sorted((ROOT / "sql" / "checks").glob("*.sql")):
            counts.append(dict(check=p.stem, db=label, rows=len(con.execute(p.read_text()).df())))
        frames[label] = {t: con.execute(f"SELECT * FROM {t}").df() for t in RAW_TABLES}
        con.close()
    pd.DataFrame(counts).pivot(index="check", columns="db", values="rows").reset_index() \
        .to_csv(out / "check_counts.csv", index=False)
    scen = [k for k in dbs if k != "baseline"][0]
    rows, differing = [], []
    for t in RAW_TABLES:
        b, s = frames["baseline"][t].copy(), frames[scen][t].copy()
        for df in (b, s):   # round floats so equal values compare equal
            for c in df.select_dtypes("float").columns:
                df[c] = df[c].round(6)
        cols = list(b.columns)
        m = b.merge(s, on=cols, how="outer", indicator="in_db")
        d = m[m.in_db != "both"].copy()
        if len(d) and len(d) <= 200:   # small diffs: keep the rows themselves
            d.insert(0, "table", t)
            d["in_db"] = d.in_db.map({"left_only": "baseline only", "right_only": f"{scen} only"})
            differing.append(d)
        rows.append(dict(table=t, rows_base=len(b), rows_run=len(s),
                         same_columns=list(b.columns) == list(s.columns),
                         only_in_base=int((m.in_db == "left_only").sum()),
                         only_in_run=int((m.in_db == "right_only").sum())))
    pd.DataFrame(rows).to_csv(out / "table_diff.csv", index=False)
    if differing:
        pd.concat(differing).to_csv(out / "table_rows_diff.csv", index=False)
    print("Saved check_counts.csv and table_diff.csv (+ table_rows_diff.csv if any rows differ)")


def keyed_diff(out, scenario, name, keys):
    """Rows that are missing on one side or differ in any value (float tolerance)."""
    b = pd.read_csv(out / f"{name}__baseline.csv")
    s = pd.read_csv(out / f"{name}__{scenario}.csv")
    m = b.merge(s, on=keys, how="outer", suffixes=("_base", "_run"), indicator="in_db")
    vals = [c for c in b.columns if c not in keys]
    same = np.isclose(m[[f"{c}_base" for c in vals]].to_numpy(float),
                      m[[f"{c}_run" for c in vals]].to_numpy(float),
                      rtol=1e-9, atol=1e-6, equal_nan=True).all(axis=1)
    m = m[(m.in_db != "both") | ~same]
    m.to_csv(out / f"{name}_diff.csv", index=False)
    print(f"{name}: {len(m)} row(s) differ from baseline; saved {name}_diff.csv")


def main(scenario):
    queries = split_queries((ROOT / "sql" / "investigations" / f"{scenario}.sql").read_text())
    dbs = {
        scenario: ROOT / "data" / "scenarios" / f"{scenario}.duckdb",
        "baseline": ROOT / "data" / "alert_desk.duckdb",
    }
    out = ROOT / "results" / "investigations" / scenario
    out.mkdir(parents=True, exist_ok=True)
    for label, path in dbs.items():
        con = duckdb.connect(str(path), read_only=True)
        for name, sql in queries.items():
            df = con.execute(sql).df()
            df.to_csv(out / f"{name}__{label}.csv", index=False)
        con.close()
    print(f"Ran {len(queries)} queries on {list(dbs)}; saved to {out.relative_to(ROOT)}")
    if "--full" in sys.argv:
        checks_and_tables(dbs, out)
    for name, keys in KEYED_DIFFS.items():
        if name in queries:
            keyed_diff(out, scenario, name, keys)
    if "weekly_tail" in queries:
        week_diff(out, scenario)
    if "campaign_map" in queries:
        map_diff(out, scenario)
    if "model_spend" in queries:
        spend_diff(out, scenario)
    if "cac_impact" in queries:
        b = pd.read_csv(out / "cac_impact__baseline.csv")
        s = pd.read_csv(out / f"cac_impact__{scenario}.csv")
        m = b.merge(s, on="period", suffixes=("_base", "_run"))
        m["rel_change"] = m.cac_run / m.cac_base - 1
        m.to_csv(out / "cac_impact_diff.csv", index=False)
        print("Saved cac_impact_diff.csv")


def map_diff(out, scenario):
    """Campaign map rows added, removed or changed compared with baseline,
    including campaigns whose total raw spend changed (spend moved between IDs)."""
    b = pd.read_csv(out / "campaign_map__baseline.csv")
    s = pd.read_csv(out / f"campaign_map__{scenario}.csv")
    m = b.merge(s, on="campaign_id", how="outer", suffixes=("_base", "_run"), indicator="in_db")

    def describe(r):
        if r.in_db == "left_only":
            return "removed"
        if r.in_db == "right_only":
            return "added"
        changes = [f"{c} changed" for c in ["campaign_name", "channel", "platform"]
                   if str(getattr(r, f"{c}_base")) != str(getattr(r, f"{c}_run"))]
        if abs(r.total_spend_run - r.total_spend_base) > 0.01:
            changes.append("total_spend changed")
        return ";".join(changes)

    m["change"] = [describe(r) for r in m.itertuples()]
    m["spend_diff"] = m.total_spend_run.fillna(0) - m.total_spend_base.fillna(0)
    m = m[m.change != ""].drop(columns="in_db")
    m.to_csv(out / "map_diff.csv", index=False)
    totals = pd.DataFrame([dict(raw_spend_base=round(b.total_spend.sum(), 2),
                                raw_spend_run=round(s.total_spend.sum(), 2))])
    totals.to_csv(out / "raw_spend_totals.csv", index=False)
    print(f"{len(m)} campaign map row(s) differ from baseline; saved map_diff.csv, raw_spend_totals.csv")


def spend_diff(out, scenario):
    """Weekly model spend per channel, scenario minus baseline."""
    b = pd.read_csv(out / "model_spend__baseline.csv")
    s = pd.read_csv(out / f"model_spend__{scenario}.csv")
    m = b.merge(s, on="week_start", how="outer", suffixes=("_base", "_run"))
    chans = ["meta", "google", "tiktok", "email"]
    for ch in chans:
        m[f"{ch}_diff"] = m[f"{ch}_spend_run"].fillna(0) - m[f"{ch}_spend_base"].fillna(0)
    m.to_csv(out / "spend_diff_weekly.csv", index=False)
    rows = []
    for ch in chans:
        d = m[f"{ch}_diff"]
        changed = m.loc[~np.isclose(d, 0, atol=0.01), "week_start"]
        rows.append(dict(
            channel=ch,
            spend_base=round(m[f"{ch}_spend_base"].sum(), 2),
            spend_run=round(m[f"{ch}_spend_run"].sum(), 2),
            diff=round(d.sum(), 2),
            rel_change=m[f"{ch}_spend_run"].sum() / m[f"{ch}_spend_base"].sum() - 1,
            weeks_changed=len(changed),
            rel_change_in_changed_weeks=(
                d[m.week_start.isin(changed)].sum()
                / m.loc[m.week_start.isin(changed), f"{ch}_spend_base"].sum()) if len(changed) else 0.0,
            first_week_changed=changed.min() if len(changed) else None,
            last_week_changed=changed.max() if len(changed) else None,
        ))
    pd.DataFrame(rows).to_csv(out / "spend_diff_summary.csv", index=False)
    print("Saved spend_diff_weekly.csv and spend_diff_summary.csv")


def week_diff(out, scenario):
    """Weeks whose inputs differ from baseline, with relative changes."""
    b = pd.read_csv(out / "weekly_tail__baseline.csv")
    s = pd.read_csv(out / f"weekly_tail__{scenario}.csv")
    m = b.merge(s, on="week_start", suffixes=("_base", "_run"))
    cols = ["ad_days", "order_days", "in_model_input", "spend", "revenue", "orders",
            "new_customers", "cac"]
    # Tolerance, so float noise from summation order does not count as a change.
    same = np.isclose(m[[f"{c}_base" for c in cols]].to_numpy(float),
                      m[[f"{c}_run" for c in cols]].to_numpy(float),
                      rtol=1e-9, atol=1e-6, equal_nan=True)
    m = m[~same.all(axis=1)].copy()
    for c in ["revenue", "orders", "new_customers", "cac"]:
        m[f"{c}_rel_change"] = m[f"{c}_run"] / m[f"{c}_base"] - 1
    m.to_csv(out / "week_diff.csv", index=False)
    print(f"{len(m)} week(s) differ from baseline; saved week_diff.csv")


if __name__ == "__main__":
    main(sys.argv[1])
