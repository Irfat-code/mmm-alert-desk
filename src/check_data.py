"""Sanity checks on the generated data.

1. Reconcile: does the weekly model input built by SQL match the generator's truth?
2. Shape: is the revenue split between baseline and media believable?
3. Data quality: run every query in sql/checks/ and report rows found.

On clean data, every reconciliation passes and every check returns zero rows,
except 03 (zero-spend weeks), which can legitimately flag pauses.

Run:  python src/check_data.py
      python src/check_data.py --db data/other.duckdb
"""
import numpy as np
import pandas as pd

from db import ROOT, Database

CHANNELS = ["meta", "google", "tiktok", "email"]


def reconcile(model_input, truth):
    print("1. Reconciliation: SQL model input vs generator truth")
    m = model_input.merge(truth, on="week_start", suffixes=("_sql", "_truth"))
    ok = len(m) == len(truth)
    print(f"   weeks matched: {len(m)} of {len(truth)}")
    checks = [("revenue", 1.0)] + [(f"{ch}_spend", 1.0) for ch in CHANNELS]
    checks += [(f"hol_{h}", 0) for h in ["black_friday", "cyber_monday", "mothers_day", "valentines", "christmas"]]
    checks += [("promo_intensity", 1e-4)]  # truth csv is rounded to 4 dp
    for col, tol in checks:
        gap = (m[f"{col}_sql"] - m[f"{col}_truth"]).abs().max()
        passed = gap <= tol
        ok &= passed
        print(f"   {'PASS' if passed else 'FAIL'}  {col:<20} max weekly gap {gap:,.4f}")
    return ok


def describe_truth(truth):
    print("\n2. Revenue decomposition (3-year totals)")
    parts = {
        "baseline (intercept+trend+seasonality)": truth[["intercept", "trend", "seasonality"]].sum().sum(),
        "holidays": truth.holidays.sum(),
        "promos": truth.promo.sum(),
        **{f"media: {ch}": truth[f"{ch}_contribution"].sum() for ch in CHANNELS},
        "noise": truth.noise.sum(),
    }
    total = truth.revenue.sum()
    for name, value in parts.items():
        print(f"   {name:<40} {value:>14,.0f}  {value / total:>6.1%}")
    print(f"   {'total revenue':<40} {total:>14,.0f}")
    print(f"\n   weekly revenue: min {truth.revenue.min():,.0f}  "
          f"median {truth.revenue.median():,.0f}  max {truth.revenue.max():,.0f}")

    corr = truth[[f"{ch}_spend" for ch in CHANNELS] + ["seasonality"]].corr().round(2)
    print("\n   Spend correlation (high values make channels harder to separate):")
    print("   " + corr.to_string().replace("\n", "\n   "))


def run_checks(db):
    print("\n3. Data quality checks")
    for path in sorted((ROOT / "sql" / "checks").glob("*.sql")):
        result = db.query_file(path)
        print(f"   {path.name:<32} {len(result)} row(s)")
        if len(result):
            print("   " + result.head(10).to_string(index=False).replace("\n", "\n   "))


def main(db_path=None):
    db = Database(db_path) if db_path else Database()
    path = db.path.resolve()
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"Database: {shown} ({db.engine})\n")
    model_input = db.query("SELECT * FROM weekly_model_input")
    model_input["week_start"] = pd.to_datetime(model_input.week_start)
    truth = pd.read_csv(ROOT / "data" / "truth" / "weekly_truth.csv", parse_dates=["week_start"])

    ok = reconcile(model_input, truth)
    describe_truth(truth)
    run_checks(db)
    db.close()
    print("\nAll reconciliations passed." if ok else "\nSome reconciliations FAILED.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reconcile and check the model input data.")
    parser.add_argument("--db", default=None, help="database file (default data/alert_desk)")
    main(parser.parse_args().db)
