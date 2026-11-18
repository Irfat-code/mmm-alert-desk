"""Test the PROPOSED sales_channel_gaps gate on every run's database. Not part of monitor_v2.
Never reads data/truth/.

Run:  python src/proposed_gate_test.py

The 3 clean seed runs are fitted on the same clean database, so they share one result.
Writes results/investigations/scenario_F/proposed_gate_test.csv.
"""
import duckdb
import pandas as pd

from db import ROOT
from monitor_v2 import CLEAN, SCENARIOS, run_inputs

SQL = (ROOT / "sql" / "investigations" / "proposed_gate_sales_channel_gaps.sql").read_text()


def main():
    rows = []
    for run in CLEAN + SCENARIOS:
        db = run_inputs(run)[1]
        con = duckdb.connect(str(db), read_only=True)
        hits = con.execute(SQL).df()
        con.close()
        rows.append(dict(run=run, clean=run in CLEAN, database=db.name, rows=len(hits),
                         fires=len(hits) > 0,
                         detail="; ".join(sorted({f"{r.sales_channel} from {str(hits[hits.sales_channel == r.sales_channel].week_start.min())[:10]}"
                                                  f" ({(hits.sales_channel == r.sales_channel).sum()} weeks)"
                                                  for r in hits.itertuples()}))))
    df = pd.DataFrame(rows)
    out = ROOT / "results" / "investigations" / "scenario_F"
    df.to_csv(out / "proposed_gate_test.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
