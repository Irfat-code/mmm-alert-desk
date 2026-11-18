"""Generate 3 years of synthetic data for Loma Skin, a fictional DTC skincare brand
selling on Shopify and TikTok Shop.

Every channel's real effect is set here: adstock decay, Hill saturation and ROAS.
Because the truth is known, every model result and every alert investigation
can be checked against it later.

Outputs
    data/alert_desk.duckdb (or .sqlite)  raw source tables + model input views
    data/truth/channel_truth.csv          true parameters and ROAS per channel
    data/truth/weekly_truth.csv           true weekly revenue decomposition

The model code must never read data/truth/. Only the evaluation step does.

Run:  python src/generate_data.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from db import DEFAULT_DB, ROOT, Database

SEED = 42
START = "2023-01-02"  # a Monday
N_WEEKS = 156         # 3 years
L_MAX = 8             # adstock carryover window, in weeks

# ---------------------------------------------------------------------------
# Ground truth. Change these to make the brand behave differently.
# ---------------------------------------------------------------------------
# alpha     adstock decay: share of this week's effect that carries into next week
# half_sat  Hill half-saturation point, in weekly (adstocked) spend dollars
# slope     Hill shape: above 1 gives an S-curve, 1 gives plain diminishing returns
# roas      true average ROAS over the 3 years (beta is solved to hit this exactly)
CHANNELS = {
    "meta":   dict(alpha=0.55, half_sat=26_000, slope=1.6, roas=1.8),
    "google": dict(alpha=0.25, half_sat=18_000, slope=1.2, roas=2.4),
    "tiktok": dict(alpha=0.40, half_sat=9_000,  slope=2.0, roas=1.2),
    "email":  dict(alpha=0.10, half_sat=1_500,  slope=1.0, roas=5.0),
}

BASE_REVENUE = 92_000   # weekly revenue with no media, no holidays, no promos
TREND_GROWTH = 0.18     # baseline grows 18% over the 3 years
NOISE_SD = 0.035        # weekly noise as a share of revenue

HOLIDAY_EFFECTS = {     # revenue added in the week containing the holiday
    "black_friday": 60_000,
    "cyber_monday": 30_000,
    "mothers_day":  14_000,
    "valentines":    6_000,
    "christmas":   -15_000,  # post shipping-cutoff dip
}

PROMO_LIFT_AT_20PCT = 40_000  # revenue lift for a full week at 20% off

# A promo deliberately run alongside a big Meta push.
# The "missing promo flag" alert later deletes it from the calendar.
SPRING_PROMO = dict(name="SPRING25", start="2025-04-07", end="2025-04-20", discount=0.25)

CAMPAIGNS = [
    # id, platform, channel, name, first_week, last_week, base_weight
    (101, "meta", "meta", "META_Prospecting_Broad", 0, 155, 0.45),
    (102, "meta", "meta", "META_Prospecting_Lookalike", 0, 80, 0.20),
    (103, "meta", "meta", "META_Retargeting_DPA", 0, 155, 0.25),
    (104, "meta", "meta", "META_AdvantagePlus_Shopping", 60, 155, 0.40),
    (201, "google_ads", "google", "GOOG_Search_Brand", 0, 155, 0.30),
    (202, "google_ads", "google", "GOOG_Search_NonBrand", 0, 155, 0.35),
    (203, "google_ads", "google", "GOOG_PMax", 20, 155, 0.40),
    (204, "google_ads", "google", "GOOG_YouTube_Awareness", 90, 130, 0.15),
    (301, "tiktok", "tiktok", "TT_Spark_Ads", 30, 155, 0.60),
    (302, "tiktok", "tiktok", "TT_Shop_GMV_Max", 62, 155, 0.50),
    (303, "tiktok", "tiktok", "TT_Creator_Whitelisting", 100, 155, 0.30),
    (401, "klaviyo", "email", "KLAVIYO_Flows", 0, 155, 0.55),
    (402, "klaviyo", "email", "KLAVIYO_Campaigns", 0, 155, 0.45),
]
CPM = {"meta": 12, "google_ads": 30, "tiktok": 8, "klaviyo": 3}
CTR = {"meta": 0.012, "google_ads": 0.04, "tiktok": 0.009, "klaviyo": 0.02}

TIKTOK_LAUNCH_WEEK = 30       # first week of TikTok ads
TIKTOK_SHOP_LAUNCH_WEEK = 62  # first week of TikTok Shop sales


# ---------------------------------------------------------------------------
# Media transforms (same shapes PyMC-Marketing uses)
# ---------------------------------------------------------------------------
def geometric_adstock(x, alpha, l_max=L_MAX):
    """Carry part of each week's spend into the following weeks. Weights sum to 1."""
    weights = alpha ** np.arange(l_max)
    weights = weights / weights.sum()
    out = np.zeros(len(x))
    for lag, w in enumerate(weights):
        out[lag:] += w * x[: len(x) - lag]
    return out


def hill(x, half_sat, slope):
    """Diminishing returns: 0 at no spend, 0.5 at half_sat, approaching 1."""
    x = np.maximum(x, 0)
    return x**slope / (x**slope + half_sat**slope)


def channel_response(spend, p, beta):
    return beta * hill(geometric_adstock(spend, p["alpha"]), p["half_sat"], p["slope"])


# ---------------------------------------------------------------------------
# Calendar pieces
# ---------------------------------------------------------------------------
def nth_weekday(year, month, weekday, n):
    """nth occurrence (1-based) of a weekday (Mon=0) in a month."""
    first = pd.Timestamp(year=year, month=month, day=1)
    offset = (weekday - first.weekday()) % 7
    return first + pd.Timedelta(days=offset + 7 * (n - 1))


def build_holidays(first_day, last_day):
    rows = []
    for year in range(first_day.year, last_day.year + 1):
        thanksgiving = nth_weekday(year, 11, 3, 4)
        rows += [
            (pd.Timestamp(year=year, month=2, day=14), "valentines"),
            (nth_weekday(year, 5, 6, 2), "mothers_day"),
            (thanksgiving + pd.Timedelta(days=1), "black_friday"),
            (thanksgiving + pd.Timedelta(days=4), "cyber_monday"),
            (pd.Timestamp(year=year, month=12, day=25), "christmas"),
        ]
    df = pd.DataFrame(rows, columns=["date", "holiday_name"])
    return df[(df.date >= first_day) & (df.date <= last_day)].reset_index(drop=True)


def build_promos(rng, first_day, last_day):
    """About 4 random sitewide promos a year (Jan to Oct), plus SPRING25.
    No overlaps, at least 3 weeks apart."""
    spring_start = pd.Timestamp(SPRING_PROMO["start"])
    spring_end = pd.Timestamp(SPRING_PROMO["end"])
    taken = [(spring_start, spring_end)]
    rows = [(SPRING_PROMO["name"], spring_start, spring_end, SPRING_PROMO["discount"])]

    for year in range(first_day.year, last_day.year + 1):
        placed, tries = 0, 0
        while placed < 4 and tries < 500:
            tries += 1
            start = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=int(rng.integers(10, 290)))
            end = start + pd.Timedelta(days=int(rng.integers(3, 10)))
            if start < first_day:
                continue
            gap = pd.Timedelta(weeks=3)
            if any(start <= e + gap and end >= s - gap for s, e in taken):
                continue
            taken.append((start, end))
            rows.append((f"PROMO_{year}_{placed + 1}", start, end, float(rng.choice([0.15, 0.20, 0.25, 0.30]))))
            placed += 1

    df = pd.DataFrame(rows, columns=["promo_name", "start_date", "end_date", "discount_pct"])
    df = df.sort_values("start_date").reset_index(drop=True)
    df.insert(0, "promo_id", np.arange(1, len(df) + 1))
    return df


def weekly_promo_intensity(promos, weeks):
    """Average discount across the 7 days of each week (matches the SQL view)."""
    out = np.zeros(len(weeks))
    for i, wk in enumerate(weeks):
        days = pd.date_range(wk, periods=7)
        for _, p in promos.iterrows():
            covered = ((days >= p.start_date) & (days <= p.end_date)).sum()
            out[i] += covered * p.discount_pct
    return out / 7


def weekly_holiday_flags(holidays, weeks):
    flags = pd.DataFrame(0, index=range(len(weeks)), columns=list(HOLIDAY_EFFECTS))
    week_of = holidays.date - pd.to_timedelta(holidays.date.dt.day_of_week, unit="D")
    for wk, name in zip(week_of, holidays.holiday_name):
        flags.loc[weeks.get_loc(wk), name] = 1
    return flags


# ---------------------------------------------------------------------------
# Spend
# ---------------------------------------------------------------------------
def flight_multipliers(rng, n, burst_p=0.08, dark_p=0.05):
    """Random bursts (x1.45 for 3 weeks) and pauses (x0.45 for 2 weeks).
    Gives the model spend variation that isn't tied to seasonality."""
    mult = np.ones(n)
    t = 0
    while t < n:
        r = rng.random()
        if r < burst_p:
            mult[t:t + 3] = 1.45
            t += 3
        elif r < burst_p + dark_p:
            mult[t:t + 2] = 0.45
            t += 2
        else:
            t += 1
    return mult


def build_weekly_spend(rng, weeks, seasonality, holiday_flags):
    n = len(weeks)
    t = np.arange(n)
    growth = t / n
    spend = {}

    spend["meta"] = (21_000 * (1 + 0.20 * growth) * (1 + 1.5 * seasonality)
                     * flight_multipliers(rng, n) * rng.lognormal(0, 0.10, n))
    spend["google"] = (13_000 * (1 + 0.25 * growth) * (1 + 1.0 * seasonality)
                       * flight_multipliers(rng, n, 0.06, 0.04) * rng.lognormal(0, 0.12, n))
    ramp = np.clip((t - TIKTOK_LAUNCH_WEEK) / 90, 0, 1)
    spend["tiktok"] = np.where(
        t >= TIKTOK_LAUNCH_WEEK,
        (1_500 + 12_000 * ramp) * flight_multipliers(rng, n, 0.06, 0.04) * rng.lognormal(0, 0.18, n),
        0.0,
    )
    spend["email"] = 1_300 * (1 + 0.5 * seasonality) * rng.lognormal(0, 0.15, n)

    # Holiday pushes
    bf = holiday_flags["black_friday"].to_numpy() == 1
    cm = holiday_flags["cyber_monday"].to_numpy() == 1
    md = holiday_flags["mothers_day"].to_numpy() == 1
    for ch, lift in {"meta": 1.7, "google": 1.4, "tiktok": 1.6, "email": 1.5}.items():
        spend[ch][bf] *= lift
    spend["meta"][cm] *= 1.3
    spend["meta"][md] *= 1.2

    # Meta push around SPRING25: the week before plus both promo weeks
    spring_week = weeks.get_loc(pd.Timestamp(SPRING_PROMO["start"]))
    spend["meta"][spring_week - 1: spring_week + 2] *= 1.6

    return pd.DataFrame({ch: np.round(v, 2) for ch, v in spend.items()})


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def build_truth(rng):
    weeks = pd.date_range(START, periods=N_WEEKS, freq="W-MON")
    first_day, last_day = weeks[0], weeks[-1] + pd.Timedelta(days=6)

    # Yearly seasonality: main peak early December, smaller bump in May
    doy = (weeks + pd.Timedelta(days=3)).day_of_year.to_numpy()
    seasonality = (0.12 * np.cos(2 * np.pi * (doy - 340) / 365.25)
                   + 0.05 * np.cos(4 * np.pi * (doy - 130) / 365.25))

    holidays = build_holidays(first_day, last_day)
    promos = build_promos(rng, first_day, last_day)
    hol_flags = weekly_holiday_flags(holidays, weeks)
    promo_int = weekly_promo_intensity(promos, weeks)
    spend = build_weekly_spend(rng, weeks, seasonality, hol_flags)

    trend = TREND_GROWTH * np.arange(N_WEEKS) / N_WEEKS
    truth = pd.DataFrame({"week_start": weeks})
    truth["intercept"] = BASE_REVENUE
    truth["trend"] = BASE_REVENUE * trend
    truth["seasonality"] = BASE_REVENUE * (1 + trend) * seasonality
    truth["holidays"] = sum(hol_flags[h] * eff for h, eff in HOLIDAY_EFFECTS.items())
    truth["promo"] = PROMO_LIFT_AT_20PCT * promo_int / 0.20

    channel_rows = []
    for ch, p in CHANNELS.items():
        x = spend[ch].to_numpy()
        unit = hill(geometric_adstock(x, p["alpha"]), p["half_sat"], p["slope"])
        beta = p["roas"] * x.sum() / unit.sum()   # solve beta so ROAS is exact
        contrib = beta * unit
        # Marginal ROAS: extra revenue from 1% more spend every week
        contrib_up = channel_response(x * 1.01, p, beta)
        mroas = (contrib_up.sum() - contrib.sum()) / (0.01 * x.sum())
        truth[f"{ch}_contribution"] = contrib
        channel_rows.append(dict(
            channel=ch, adstock_alpha=p["alpha"], hill_half_sat=p["half_sat"],
            hill_slope=p["slope"], beta_max_weekly=round(beta, 2),
            total_spend=round(x.sum(), 2), total_contribution=round(contrib.sum(), 2),
            true_roas=round(contrib.sum() / x.sum(), 4), true_mroas=round(mroas, 4),
        ))

    noiseless = truth.drop(columns="week_start").sum(axis=1)
    truth["noise"] = rng.normal(0, NOISE_SD * noiseless.mean(), N_WEEKS)
    truth["revenue"] = noiseless + truth["noise"]
    for ch in CHANNELS:
        truth[f"{ch}_spend"] = spend[ch]
    for h in HOLIDAY_EFFECTS:
        truth[f"hol_{h}"] = hol_flags[h]
    truth["promo_intensity"] = promo_int

    return truth, pd.DataFrame(channel_rows), holidays, promos


def daily_weights(rng, boost_day=None):
    """Split a week across 7 days with a little noise. boost_day triples one day."""
    w = np.array([0.15, 0.145, 0.14, 0.14, 0.145, 0.14, 0.14]) * rng.lognormal(0, 0.05, 7)
    if boost_day is not None:
        w[boost_day] *= 3
    return w / w.sum()


def build_raw_tables(rng, truth, holidays, promos):
    weeks = pd.DatetimeIndex(truth.week_start)
    days = pd.date_range(weeks[0], periods=7 * len(weeks))

    dim_date = pd.DataFrame({"date": days, "week_start": days - pd.to_timedelta(days.day_of_week, unit="D")})

    # --- Ad spend: weekly channel spend -> campaigns -> days
    camp = pd.DataFrame(CAMPAIGNS, columns=["campaign_id", "platform", "channel", "campaign_name",
                                            "first_week", "last_week", "weight"])
    spend_rows = []
    for i, wk in enumerate(weeks):
        for ch in CHANNELS:
            total = truth.at[i, f"{ch}_spend"]
            if total <= 0:
                continue
            active = camp[(camp.channel == ch) & (camp.first_week <= i) & (camp.last_week >= i)]
            shares = rng.dirichlet(active.weight.to_numpy() * 40)
            for (_, c), share in zip(active.iterrows(), shares):
                for d, w in enumerate(daily_weights(rng)):
                    s = round(total * share * w, 2)
                    impressions = int(s / CPM[c.platform] * 1000 * rng.lognormal(0, 0.1))
                    clicks = int(impressions * CTR[c.platform] * rng.lognormal(0, 0.1))
                    spend_rows.append((wk + pd.Timedelta(days=d), c.platform, c.campaign_id,
                                       c.campaign_name, s, impressions, clicks))
    raw_ad_spend = pd.DataFrame(spend_rows, columns=["date", "platform", "campaign_id", "campaign_name",
                                                     "spend", "impressions", "clicks"])
    channel_map = camp[["campaign_id", "campaign_name", "channel"]].copy()

    # --- Shopify orders: weekly revenue -> sales channel -> days
    media = truth[[f"{ch}_contribution" for ch in CHANNELS]].sum(axis=1)
    noiseless = truth.revenue - truth.noise
    baseline = truth[["intercept", "trend", "seasonality"]].sum(axis=1)
    tt_shop = 0.55 * truth.tiktok_contribution + np.where(
        np.arange(len(weeks)) >= TIKTOK_SHOP_LAUNCH_WEEK, 0.015 * baseline, 0)
    tt_share = tt_shop / noiseless
    media_share = media / noiseless

    bf_weeks = set(holidays.loc[holidays.holiday_name == "black_friday", "date"]
                   .pipe(lambda s: s - pd.to_timedelta(s.dt.day_of_week, unit="D")))
    order_rows = []
    for i, wk in enumerate(weeks):
        boost = 4 if wk in bf_weeks else None   # Friday spike in Black Friday week
        split = {"online_store": truth.revenue[i] * (1 - tt_share[i]),
                 "tiktok_shop": truth.revenue[i] * tt_share[i]}
        for sales_channel, rev in split.items():
            if rev <= 0:
                continue
            aov = (54 if sales_channel == "online_store" else 38) * rng.lognormal(0, 0.03)
            new_share = (0.30 + 0.35 * media_share[i] if sales_channel == "online_store" else 0.60)
            for d, w in enumerate(daily_weights(rng, boost)):
                day_rev = round(rev * w, 2)
                orders = max(int(round(day_rev / aov)), 0)
                new_cust = int(round(orders * np.clip(new_share + rng.normal(0, 0.01), 0, 1)))
                order_rows.append((wk + pd.Timedelta(days=d), sales_channel, day_rev, orders, new_cust))
    orders = pd.DataFrame(order_rows, columns=["date", "sales_channel", "revenue", "orders", "new_customers"])

    return dict(dim_date=dim_date, raw_ad_spend=raw_ad_spend, campaign_channel_map=channel_map,
                shopify_orders_daily=orders, holiday_calendar=holidays, promo_calendar=promos)


def build_database(tables, db_path=DEFAULT_DB):
    Database.remove(db_path)
    db = Database(db_path)
    db.run_script(ROOT / "sql" / "schema.sql")
    for name, df in tables.items():
        db.write(name, df)
    for view_file in sorted((ROOT / "sql" / "views").glob("*.sql")):
        db.run_script(view_file)
    return db


def main():
    rng = np.random.default_rng(SEED)
    truth, channel_truth, holidays, promos = build_truth(rng)
    tables = build_raw_tables(rng, truth, holidays, promos)

    truth_dir = ROOT / "data" / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    num_cols = truth.select_dtypes("number").columns
    truth[num_cols] = truth[num_cols].round(4)
    truth.to_csv(truth_dir / "weekly_truth.csv", index=False)
    channel_truth.to_csv(truth_dir / "channel_truth.csv", index=False)

    db = build_database(tables)
    print(f"Database: {db.path.relative_to(ROOT)} ({db.engine})")
    for name, df in tables.items():
        print(f"  {name:<22} {len(df):>7,} rows")
    print("\nGround truth per channel:")
    print(channel_truth[["channel", "total_spend", "true_roas", "true_mroas"]].to_string(index=False))
    db.close()


if __name__ == "__main__":
    main()
