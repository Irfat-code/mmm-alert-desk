-- Investigation queries for alerts A001 (scenario_B, roas_shift tiktok) and
-- A002 (scenario_B, rows:01_unexpected_channels).
-- Each query starts with a "-- name:" line. src/run_investigation.py runs every
-- query on the scenario database and the clean baseline database and saves
-- the output to results/investigations/scenario_B/<name>__<db>.csv.
-- Written to run on both DuckDB and SQLite. Weeks come from dim_date.

-- ---------------------------------------------------------------------------
-- Round 1
-- ---------------------------------------------------------------------------

-- name: check01_detail
-- Check 01 broken out per campaign: which spend never reaches the model,
-- which platform it came from, and when it started and stopped.
SELECT
    COALESCE(m.channel, '(unmapped)') AS channel_label,
    s.campaign_id,
    MIN(s.campaign_name)              AS campaign_name,
    MIN(s.platform)                   AS platform,
    COUNT(DISTINCT s.platform)        AS n_platforms,
    MIN(s.date)                       AS first_seen,
    MAX(s.date)                       AS last_seen,
    COUNT(DISTINCT s.date)            AS n_days,
    ROUND(SUM(s.spend), 2)            AS spend_lost
FROM raw_ad_spend s
LEFT JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
WHERE m.channel IS NULL
   OR m.channel NOT IN ('meta', 'google', 'tiktok', 'email')
GROUP BY COALESCE(m.channel, '(unmapped)'), s.campaign_id
ORDER BY channel_label, s.campaign_id;

-- name: campaign_map
-- The full campaign map, plus the platform(s) each campaign spends on and its
-- total spend. src/run_investigation.py diffs this against baseline.
SELECT m.campaign_id, m.campaign_name, m.channel,
       MIN(s.platform)            AS platform,
       COUNT(DISTINCT s.platform) AS n_platforms,
       ROUND(SUM(s.spend), 2)     AS total_spend
FROM campaign_channel_map m
LEFT JOIN raw_ad_spend s ON s.campaign_id = m.campaign_id
GROUP BY m.campaign_id, m.campaign_name, m.channel
ORDER BY m.campaign_id;

-- name: model_spend
-- Weekly spend per model channel, exactly as the model receives it.
SELECT week_start, meta_spend, google_spend, tiktok_spend, email_spend
FROM weekly_model_input
ORDER BY week_start;

-- ---------------------------------------------------------------------------
-- Round 2
-- ---------------------------------------------------------------------------

-- name: spend_reconciliation
-- Would a reconciliation gate have caught this? Total raw spend against the
-- spend the model receives. On clean data the gap is zero.
SELECT
    (SELECT ROUND(SUM(spend), 2) FROM raw_ad_spend) AS raw_spend,
    (SELECT ROUND(SUM(meta_spend + google_spend + tiktok_spend + email_spend), 2)
       FROM weekly_model_input)                      AS model_spend,
    (SELECT ROUND(SUM(spend), 2) FROM raw_ad_spend)
      - (SELECT ROUND(SUM(meta_spend + google_spend + tiktok_spend + email_spend), 2)
           FROM weekly_model_input)                  AS gap;

-- name: cac_impact
-- Pooled CAC (model spend / new customers) before and within the weeks where
-- Meta spend dropped out (2025-09-01 on, from spend_diff_summary.csv), and over
-- the latest 2 weeks that the cac_spike rule uses.
WITH w AS (
    SELECT week_start,
           meta_spend + google_spend + tiktok_spend + email_spend AS spend,
           new_customers,
           ROW_NUMBER() OVER (ORDER BY week_start DESC) AS rn
    FROM weekly_model_input
)
SELECT 'before_2025-09-01' AS period, SUM(spend) / SUM(new_customers) AS cac
FROM w WHERE week_start < '2025-09-01'
UNION ALL
SELECT 'from_2025-09-01', SUM(spend) / SUM(new_customers)
FROM w WHERE week_start >= '2025-09-01'
UNION ALL
SELECT 'latest_2_weeks', SUM(spend) / SUM(new_customers)
FROM w WHERE rn <= 2;
