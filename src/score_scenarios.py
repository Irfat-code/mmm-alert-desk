"""Score each scenario investigation against the answer key.

This is a scoring script: it reads data/truth/scenario_key.json, which the
investigations never did. Run it only after the notes are final.

Run:  python src/score_scenarios.py

For each scenario: the DATA or MODEL classification in its alert note, the true
fault and kind from the key, whether the classification matches, and whether
monitor v1 (alerts/queue.csv) and monitor v2 (results/monitor_v2_scorecard.csv)
caught it.

Writes data/truth/scores/scenarios.csv.
"""
import json
import re

import pandas as pd

from db import ROOT


def note_classification(letter):
    notes = sorted((ROOT / "alerts").glob(f"{letter}_*.md"))
    assert len(notes) == 1, f"expected one note for scenario {letter}, found {notes}"
    text = notes[0].read_text(encoding="utf-8")
    section = re.search(r"^## Classification\s*\n(.*?)(?=^## )", text, flags=re.M | re.S)
    assert section, f"no Classification section in {notes[0].name}"
    found = re.search(r"\b(DATA|MODEL)\b", section.group(1))
    assert found, f"no DATA/MODEL in the Classification section of {notes[0].name}"
    return found.group(1), notes[0].name


def main():
    key = json.loads((ROOT / "data" / "truth" / "scenario_key.json").read_text())
    queue = pd.read_csv(ROOT / "alerts" / "queue.csv")
    v2 = pd.read_csv(ROOT / "results" / "monitor_v2_scorecard.csv").set_index("run")
    rows = []
    for scenario, truth in sorted(key.items()):
        letter = scenario.split("_")[1]
        mine, note = note_classification(letter)
        v1 = queue[queue.run == scenario]
        r2 = v2.loc[scenario]
        rows.append(dict(
            scenario=scenario, note=note,
            my_classification=mine,
            true_kind=truth["kind"], true_fault=truth["fault"], true_detail=truth["detail"],
            correct=mine.upper() == str(truth["kind"]).upper(),
            v1_caught=len(v1) > 0,
            v1_alerts=";".join(f"{a.alert_id} {a.alert_type} {a.metric}" for a in v1.itertuples()),
            v2_caught=r2.caught != "not caught",
            v2_when=r2.caught,
            v2_gates=r2.gates_fired if isinstance(r2.gates_fired, str) else "",
            v2_alerts=r2.alerts_fired if isinstance(r2.alerts_fired, str) else "",
        ))
    df = pd.DataFrame(rows)
    out = ROOT / "data" / "truth" / "scores"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "scenarios.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    print(df[["scenario", "my_classification", "true_kind", "true_fault", "correct",
              "v1_caught", "v2_caught", "v2_when"]].to_string(index=False))
    print(f"\nCorrectly classified: {df.correct.sum()} of {len(df)}. "
          f"Caught by v1: {df.v1_caught.sum()} of {len(df)}. Caught by v2: {df.v2_caught.sum()} of {len(df)} "
          f"({(df.v2_when == 'before fit (gate)').sum()} before fitting).")


if __name__ == "__main__":
    main()
