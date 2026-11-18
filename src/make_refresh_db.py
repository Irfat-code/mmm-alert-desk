"""Build 'last month's' database for the refresh false-positive test.

Copies the clean database to a scratch path and removes the last N weeks (default 4)
from raw_ad_spend, shopify_orders_daily and dim_date, as if the data had been loaded
a month earlier. Nothing else changes.

Run:  python src/make_refresh_db.py <scratch dir> --weeks 4
Then: python src/fit_model.py configs/baseline.json --db <scratch dir>/baseline_minus4w.duckdb
Delete the scratch database afterwards. Only results/ is kept.
"""
import argparse
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]


def main(scratch, weeks):
    dst = Path(scratch) / f"baseline_minus{weeks}w.duckdb"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    shutil.copyfile(ROOT / "data" / "alert_desk.duckdb", dst)
    con = duckdb.connect(str(dst))
    cutoff = con.execute(f"""SELECT MIN(week_start) AS c FROM (
                                SELECT DISTINCT week_start FROM dim_date
                                ORDER BY week_start DESC LIMIT {weeks}) x""").df().c[0]
    for t in ("raw_ad_spend", "shopify_orders_daily", "dim_date"):
        con.execute(f"DELETE FROM {t} WHERE date >= ?", [cutoff])
    n = con.execute("SELECT COUNT(*) AS n, MAX(week_start) AS last FROM weekly_model_input").df().iloc[0]
    con.close()
    print(f"Removed weeks from {str(cutoff)[:10]}; model input now {n.n} weeks, last {str(n['last'])[:10]}")
    print(f"Database: {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scratch")
    ap.add_argument("--weeks", type=int, default=4)
    a = ap.parse_args()
    main(a.scratch, a.weeks)
