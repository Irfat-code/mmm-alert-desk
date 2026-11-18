"""Causal test for scenario_F: restore the missing TikTok Shop sales rows and nothing else.

Copies data/scenarios/scenario_F.duckdb to a scratch path, inserts the tiktok_shop rows
from 2025-10-06 on as recorded in the clean snapshot (in production: a re-pull of the
TikTok Shop feed for those dates), and checks that the model input now matches the
clean database.

Run:  python src/fix_feed_test.py <scratch dir>
Then: python src/fit_model.py configs/scenario_F.json --db <scratch dir>/scenario_F_fixfeed.duckdb
      python src/compare_runs.py scenario_F__scenario_F_fixfeed scenario_F_fixfeed
Delete the scratch database afterwards. Only results/ is kept.

Writes results/investigations/scenario_F_fixfeed/fix_input_check.csv.
"""
import shutil
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SQL = "SELECT * FROM weekly_model_input ORDER BY week_start"
GAP = "sales_channel = 'tiktok_shop' AND date >= DATE '2025-10-06'"


def main(scratch):
    dst = Path(scratch) / "scenario_F_fixfeed.duckdb"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    shutil.copyfile(ROOT / "data" / "scenarios" / "scenario_F.duckdb", dst)

    clean = duckdb.connect(str(ROOT / "data" / "alert_desk.duckdb"), read_only=True)
    rows_in = clean.execute(f"SELECT * FROM shopify_orders_daily WHERE {GAP}").df()
    ref = clean.execute(SQL).df()
    clean.close()

    con = duckdb.connect(str(dst))
    before = int(con.execute(f"SELECT COUNT(*) AS n FROM shopify_orders_daily WHERE {GAP}").df().n[0])
    con.register("_rows", rows_in)
    con.execute("INSERT INTO shopify_orders_daily SELECT * FROM _rows")
    fixed = con.execute(SQL).df()
    con.close()

    cols = [c for c in ref.columns if c != "week_start"]
    rows = [dict(item="tiktok_shop rows from 2025-10-06 before fix", value=before),
            dict(item="rows restored", value=len(rows_in)),
            dict(item="revenue restored", value=round(float(rows_in.revenue.sum()), 2)),
            dict(item="model input weeks (fixed / clean)", value=f"{len(fixed)} / {len(ref)}")]
    rows += [dict(item=f"max abs weekly diff vs clean: {c}",
                  value=float(np.abs(fixed[c].to_numpy(float) - ref[c].to_numpy(float)).max()))
             for c in cols]
    out = ROOT / "results" / "investigations" / "scenario_F_fixfeed"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "fix_input_check.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    diffs = [r["value"] for r in rows[4:]]
    if before != 0 or max(diffs) > 1e-6:
        sys.exit("Fixed input does not match the clean database. Do not fit.")


if __name__ == "__main__":
    main(sys.argv[1])
