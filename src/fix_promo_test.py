"""Causal test for scenario_A: restore the missing SPRING25 promo and nothing else.

Copies data/scenarios/scenario_A.duckdb to a scratch path, inserts promo_id 10 as
recorded in the clean snapshot (in production: as re-entered from the marketing
team's records), and checks that the model input now matches the clean database.

Run:  python src/fix_promo_test.py <scratch dir>
Then: python src/fit_model.py configs/scenario_A.json --db <scratch dir>/scenario_A_fixpromo.duckdb
      python src/compare_runs.py scenario_A__scenario_A_fixpromo scenario_A_fixpromo
Delete the scratch database afterwards. Only results/ is kept.

Writes results/investigations/scenario_A_fixpromo/fix_input_check.csv.
"""
import shutil
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SQL = "SELECT * FROM weekly_model_input ORDER BY week_start"


def main(scratch):
    dst = Path(scratch) / "scenario_A_fixpromo.duckdb"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    shutil.copyfile(ROOT / "data" / "scenarios" / "scenario_A.duckdb", dst)

    clean = duckdb.connect(str(ROOT / "data" / "alert_desk.duckdb"), read_only=True)
    row = clean.execute("SELECT * FROM promo_calendar WHERE promo_id = 10").df()
    ref = clean.execute(SQL).df()
    clean.close()

    con = duckdb.connect(str(dst))
    before = int(con.execute("SELECT COUNT(*) AS n FROM promo_calendar WHERE promo_id = 10").df().n[0])
    con.register("_row", row)
    con.execute("INSERT INTO promo_calendar SELECT * FROM _row")
    fixed = con.execute(SQL).df()
    con.close()

    cols = [c for c in ref.columns if c != "week_start"]
    rows = [dict(item="promo_id 10 rows before fix", value=before),
            dict(item="restored row", value=row.to_dict("records")[0]),
            dict(item="model input weeks (fixed / clean)", value=f"{len(fixed)} / {len(ref)}")]
    rows += [dict(item=f"max abs weekly diff vs clean: {c}",
                  value=float(np.abs(fixed[c].to_numpy(float) - ref[c].to_numpy(float)).max()))
             for c in cols]
    out = ROOT / "results" / "investigations" / "scenario_A_fixpromo"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "fix_input_check.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    diffs = [r["value"] for r in rows[3:]]
    if before != 0 or max(diffs) != 0:
        sys.exit("Fixed input does not match the clean database. Do not fit.")


if __name__ == "__main__":
    main(sys.argv[1])
