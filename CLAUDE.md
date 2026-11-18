# MMM Alert Desk

Portfolio project that simulates the MMM analyst job: a Bayesian marketing mix model for a fictional DTC skincare brand (Loma Skin), production-style alerts caused by injected data and model faults, and an investigation note for each alert. Synthetic data with known ground truth, so every result can be checked.

## Environment

- Windows, PowerShell, VS Code. Python 3.14 in `.venv` (activate with `.venv\Scripts\Activate.ps1`). Always run Python as `python` inside the venv and install with `python -m pip`. Never install packages globally.
- pymc-marketing 1.4.0, pymc 6.4, pytensor 3.3.8, duckdb 2.0, pandas 3.1, arviz 1.3.
- No g++ on this machine. `fit_model.py` switches PyTensor to Numba mode. Don't try to install a C compiler.
- MMM API used: `from pymc_marketing.mmm.mmm import MMM`, with `target_column`, `channel_columns`, `control_columns`, `GeometricAdstock`, `HillSaturation`. Check the installed package before assuming an API from older tutorials.

## Layout and run order

```
python src/generate_data.py                      # builds data/alert_desk.duckdb + data/truth/
python src/check_data.py                         # reconciles SQL vs truth, runs sql/checks/
python src/fit_model.py configs/baseline.json    # fits the MMM, writes results/<name>/
python src/score_against_truth.py baseline       # compares estimates to the truth, writes data/truth/scores/<name>.csv
```

- `sql/schema.sql` holds the raw source tables, `sql/views/model_input.sql` the weekly model input, and `sql/checks/` the data quality queries (one query per file).
- `configs/*.json` holds one model configuration per file; results go to `results/<config name>/`.
- `alerts/` holds one markdown investigation note per alert. `configs/CHANGELOG.md` logs every promoted or rejected config.

## Rules

1. **The answer key is off-limits to the model and the investigations.** Only `score_against_truth.py` and other scoring scripts may read `data/truth/`. Never tune a model or write an investigation by looking at the truth. Tune on diagnostics, fit and business plausibility only, as a real analyst would. Investigation sessions must not read src/inject_faults.py, data/truth/scenario_key.json, or configs/scenario_*.json diffs against baseline. Investigate from the databases, results and alert queue only, as an analyst would. Investigation sessions must also not read data/truth/scored_decisions.md or any README section that compares results to the truth.
2. **Every number in a note or the README comes from a saved script output** in `results/` or a query I can rerun. No numbers typed from memory, no rounding that changes the story.
3. **Never invent the AI-validation story.** `docs/ai_review_log.md` is written by the user, from real moments when she caught an AI mistake. Don't add entries to it. You may help format her entries.
4. SQL must run on both DuckDB and SQLite. Use `dim_date` for week grouping, and avoid engine-specific date functions.
5. Keep the generator's fixed seed. If you change `generate_data.py`, rerun `check_data.py`, and all reconciliations must still pass.
6. Writing style: plain, short sentences, no hype words. Notes are under one page. The README stays practical.
7. Stop and show me results after each step rather than chaining several big steps.

## Investigation note template (alerts/<id>_<short_name>.md)

```
# Alert <id>: <what fired>
Raised: <date>  |  Triage done: <date>  |  Resolved: <date>
## Symptom          what the monitor saw, with the numbers
## Hypotheses       2-4, ranked, each with how it would be tested
## Evidence         queries/scripts run and what they showed (link files)
## Classification   DATA or MODEL issue, and why
## Root cause       one paragraph
## Recommendation   what to fix, who owns it, what to rerun
## Impact           which ROAS/CAC numbers were wrong and by how much
```

## Git

- Only commit when asked. Never push unless asked.
- Commits are authored as GitHub user irfat-code with email ruckkyvilla@gmail.com.
- No `Co-Authored-By` line, no "Generated with Claude" line, and no other Claude trailer in commit messages or PR text. Claude must not appear as a contributor.
