"""Compare a fitted model's channel ROAS against the known truth.

This is the only step that reads data/truth/. In a real job there is no answer key;
here it lets me prove whether the model (and later, each investigation) got it right.

Run:  python src/score_against_truth.py baseline

Writes data/truth/scores/<run>.csv. Scores live under data/truth/, not results/,
so investigation sessions (which may read results/) never see them.
"""
import sys

import pandas as pd

from db import ROOT


def main(run_name):
    est = pd.read_csv(ROOT / "results" / run_name / "estimates.csv")
    truth = pd.read_csv(ROOT / "data" / "truth" / "channel_truth.csv")
    m = est.merge(truth[["channel", "true_roas"]], on="channel")

    m["error_pct"] = (m.roas_mean / m.true_roas - 1).round(4)
    m["truth_in_90pct_interval"] = (m.true_roas >= m.roas_low_5) & (m.true_roas <= m.roas_high_95)
    m["true_rank"] = m.true_roas.rank(ascending=False).astype(int)
    m["est_rank"] = m.roas_mean.rank(ascending=False).astype(int)

    cols = ["channel", "measured", "true_roas", "roas_mean", "roas_low_5", "roas_high_95",
            "error_pct", "truth_in_90pct_interval", "true_rank", "est_rank"]
    scores = ROOT / "data" / "truth" / "scores"
    scores.mkdir(parents=True, exist_ok=True)
    m[cols].to_csv(scores / f"{run_name}.csv", index=False)

    show = m[cols].copy()
    show["error_pct"] = show.error_pct.map("{:+.1%}".format)
    print(f"Scorecard: {run_name}\n")
    print(show.to_string(index=False))
    print(f"\nTruth inside 90% interval: {m.truth_in_90pct_interval.sum()} of {len(m)} channels")
    print(f"Channel ranking matches truth: {'yes' if (m.true_rank == m.est_rank).all() else 'no'}")
    unmeasured = m.loc[~m.measured, "channel"].tolist()
    if unmeasured:
        print(f"Not measured by the MMM (posterior = prior): {', '.join(unmeasured)}. "
              "Their rows score the prior, not the data.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "baseline")
