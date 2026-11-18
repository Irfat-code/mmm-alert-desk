"""Causal test for alert A001: rebuild scenario_B with one mapping fixed.

Copies data/scenarios/scenario_B.duckdb to a scratch path, remaps campaign 105
from 'social' to 'meta' (nothing else changes), and checks that the fixed
database's model input now matches the clean baseline's.

Run:  python src/fix_mapping_test.py <scratch dir>
Then: python src/fit_model.py configs/baseline.json --db <scratch dir>/scenario_B_fix105.duckdb
      python src/compare_runs.py baseline__scenario_B_fix105 scenario_B_fix105
Delete the scratch database afterwards. Only results/ is kept.

Writes results/investigations/scenario_B_fix105/fix_input_check.csv.
Never reads data/truth/.
"""
import shutil
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SPEND_SQL = "SELECT * FROM weekly_model_input ORDER BY week_start"


def main(scratch):
    src = ROOT / "data" / "scenarios" / "scenario_B.duckdb"
    dst = Path(scratch) / "scenario_B_fix105.duckdb"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    shutil.copyfile(src, dst)

    con = duckdb.connect(str(dst))
    before = con.execute("SELECT channel FROM campaign_channel_map WHERE campaign_id = 105").fetchall()
    con.execute("UPDATE campaign_channel_map SET channel = 'meta' WHERE campaign_id = 105")
    fixed = con.execute(SPEND_SQL).df()
    lost = con.execute("""SELECT COUNT(*) FROM raw_ad_spend s
                          LEFT JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
                          WHERE m.channel IS NULL
                             OR m.channel NOT IN ('meta','google','tiktok','email')""").fetchone()[0]
    con.close()

    base = duckdb.connect(str(ROOT / "data" / "alert_desk.duckdb"), read_only=True)
    clean = base.execute(SPEND_SQL).df()
    base.close()

    cols = [c for c in clean.columns if c != "week_start"]   # every model input column
    rows = [dict(item="campaign 105 channel before fix", value=before[0][0] if before else None),
            dict(item="raw_ad_spend rows still unmapped after fix", value=lost),
            dict(item="model input weeks (fixed / clean)", value=f"{len(fixed)} / {len(clean)}")]
    for c in cols:
        rows.append(dict(item=f"max abs weekly diff vs clean: {c}",
                         value=float(np.abs(fixed[c].to_numpy() - clean[c].to_numpy()).max())))
    out = ROOT / "results" / "investigations" / "scenario_B_fix105"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "fix_input_check.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"Fixed database: {dst}")


if __name__ == "__main__":
    main(sys.argv[1])
