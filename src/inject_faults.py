"""Build 5 fault scenarios from the clean database, for the alert desk to investigate.

Each scenario gets its own database copy in data/scenarios/ and its own config in
configs/. Letters A to E are assigned in a shuffled order (fixed seed, so the build
is reproducible). The letter-to-fault mapping is written only to
data/truth/scenario_key.json and is never printed.

Investigation sessions must not read this file. See CLAUDE.md rule 1.

Run:  python src/inject_faults.py
"""
import json
import random
import shutil

import pandas as pd

from db import DEFAULT_DB, ROOT, Database

SCENARIO_SEED = 2025          # fixed, so the letter assignment is reproducible
SCENARIO_DIR = ROOT / "data" / "scenarios"
KEY_PATH = ROOT / "data" / "truth" / "scenario_key.json"
LETTERS = ["A", "B", "C", "D", "E"]

# Fault settings
TIKTOK_GAP_START, TIKTOK_GAP_END = "2025-06-16", "2025-07-06"   # 3 full weeks (Mon to Sun)
RELABEL_CAMPAIGN_ID, RELABEL_NEW_ID = 104, 105                   # META_AdvantagePlus_Shopping
RELABEL_FROM = "2025-09-01"
RELABEL_CHANNEL = "social"
ORDER_DELAY_DAYS = 9
DROPPED_PROMO = "SPRING25"

# Model fault: a bad edit to the logistic saturation prior.
#
# The baseline uses PyMC-Marketing's default lam ~ Gamma(alpha=3, beta=1) (mean 3).
# The edit adds  "saturation_lam": {"dist": "Gamma", "alpha": 3, "beta": 0.1}.
#
# Why this is realistic: the person editing wanted gentler curves, a lam around 0.3,
# and wrote the Gamma the way numpy and scipy define it, with a shape and a SCALE
# (mean = shape x scale = 3 x 0.1 = 0.3). PyMC's Gamma takes beta as a RATE
# (mean = alpha / beta = 3 / 0.1 = 30). The rate-vs-scale mix-up is a common
# parametrisation error. It passes every schema check, the model fits without
# errors, and the config diff looks like a small, reasonable tweak.
#
# Effect: spend is max-scaled to [0, 1]. With lam near 30, logistic saturation reaches
# about 90% of its ceiling at 10% of a channel's peak weekly spend, so every channel
# saturates almost immediately and media stops tracking spend.
BAD_LAM_PRIOR = {"dist": "Gamma", "alpha": 3, "beta": 0.1}


def execute(db, sql):
    """Run a statement that changes data, on DuckDB or SQLite."""
    db.con.execute(sql)
    if db.engine == "sqlite":
        db.con.commit()


def tiktok_feed_gap(db):
    execute(db, f"""DELETE FROM raw_ad_spend
                 WHERE platform = 'tiktok'
                   AND date BETWEEN '{TIKTOK_GAP_START}' AND '{TIKTOK_GAP_END}'""")


def relabelled_campaign(db):
    # How the mistake happens: the platform re-issues the campaign under a new ID
    # (same name), and whoever maintains the map files the new ID under "social".
    name = db.query(f"SELECT campaign_name FROM campaign_channel_map "
                    f"WHERE campaign_id = {RELABEL_CAMPAIGN_ID}").campaign_name[0]
    execute(db, f"INSERT INTO campaign_channel_map (campaign_id, campaign_name, channel) "
                f"VALUES ({RELABEL_NEW_ID}, '{name}', '{RELABEL_CHANNEL}')")
    execute(db, f"""UPDATE raw_ad_spend SET campaign_id = {RELABEL_NEW_ID}
                 WHERE campaign_id = {RELABEL_CAMPAIGN_ID} AND date >= '{RELABEL_FROM}'""")


def reporting_delay(db):
    last = pd.Timestamp(db.query("SELECT MAX(date) AS d FROM shopify_orders_daily").d[0])
    cutoff = (last - pd.Timedelta(days=ORDER_DELAY_DAYS - 1)).strftime("%Y-%m-%d")
    execute(db, f"DELETE FROM shopify_orders_daily WHERE date >= '{cutoff}'")


def missing_promo(db):
    execute(db, f"DELETE FROM promo_calendar WHERE promo_name = '{DROPPED_PROMO}'")


def no_data_change(db):
    pass


FAULTS = [
    dict(fault="broken_tiktok_feed", kind="DATA", apply=tiktok_feed_gap,
         detail=f"TikTok ad spend rows deleted {TIKTOK_GAP_START} to {TIKTOK_GAP_END}. Orders unchanged."),
    dict(fault="relabelled_campaign", kind="DATA", apply=relabelled_campaign,
         detail=f"Campaign {RELABEL_CAMPAIGN_ID} spend from {RELABEL_FROM} moved to new campaign_id "
                f"{RELABEL_NEW_ID}, same name, mapped to '{RELABEL_CHANNEL}'."),
    dict(fault="reporting_delay", kind="DATA", apply=reporting_delay,
         detail=f"Last {ORDER_DELAY_DAYS} days of shopify_orders_daily deleted. Ad spend complete."),
    dict(fault="missing_promo_flag", kind="DATA", apply=missing_promo,
         detail=f"{DROPPED_PROMO} deleted from promo_calendar."),
    dict(fault="bad_saturation_prior", kind="MODEL", apply=no_data_change,
         detail="Clean data. Config sets saturation_lam to Gamma(alpha=3, beta=0.1): meant as "
                "shape/scale (mean 0.3), read by PyMC as shape/rate (mean 30)."),
]


def scenario_config(letter, fault, baseline):
    name = f"scenario_{letter}"
    cfg = {"name": name,
           "description": f"Scenario run on data/scenarios/{name}.duckdb.",
           "database": f"data/scenarios/{name}.duckdb"}
    cfg.update({k: v for k, v in baseline.items() if k not in ("name", "description")})
    if fault["fault"] == "bad_saturation_prior":
        cfg["priors"] = {**cfg["priors"], "saturation_lam": BAD_LAM_PRIOR}
    return cfg


def main():
    baseline = json.loads((ROOT / "configs" / "baseline.json").read_text())
    clean_db = DEFAULT_DB.with_suffix(".duckdb")
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)

    faults = FAULTS.copy()
    random.Random(SCENARIO_SEED).shuffle(faults)

    key = {}
    for letter, fault in zip(LETTERS, faults):
        name = f"scenario_{letter}"
        target = SCENARIO_DIR / name
        Database.remove(target)
        shutil.copy(clean_db, target.with_suffix(".duckdb"))
        db = Database(target)
        fault["apply"](db)
        db.close()

        cfg = scenario_config(letter, fault, baseline)
        (ROOT / "configs" / f"{name}.json").write_text(json.dumps(cfg, indent=2) + "\n")
        key[name] = dict(fault=fault["fault"], kind=fault["kind"], detail=fault["detail"])

    KEY_PATH.write_text(json.dumps(key, indent=2) + "\n")
    print(f"Built {len(key)} scenarios in data/scenarios/ with configs/scenario_*.json.")
    print("Letter-to-fault key saved to data/truth/scenario_key.json (not printed).")


if __name__ == "__main__":
    main()
