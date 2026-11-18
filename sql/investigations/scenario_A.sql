-- Monthly review of scenario_A (no alert fired; ROAS moved under the 25% threshold).
-- Each query starts with a "-- name:" line. src/run_investigation.py runs every
-- query on the scenario database and the clean baseline database and saves
-- the output to results/investigations/scenario_A/<name>__<db>.csv.
-- With --full it also runs every query in sql/checks/ and diffs every raw table.
-- Written to run on both DuckDB and SQLite. Weeks come from dim_date.

-- ---------------------------------------------------------------------------
-- Round 1
-- ---------------------------------------------------------------------------

-- name: model_input_full
-- Everything the model is fitted on, including controls.
SELECT * FROM weekly_model_input ORDER BY week_start;

-- name: channel_week
-- Raw ad rows per channel and week: rows, zero-spend rows, spend, impressions, clicks.
SELECT COALESCE(m.channel, '(unmapped)') AS channel, d.week_start,
       COUNT(*)                                      AS n_rows,
       SUM(CASE WHEN s.spend = 0 THEN 1 ELSE 0 END)  AS zero_spend_rows,
       ROUND(SUM(s.spend), 2)                        AS spend,
       SUM(s.impressions)                            AS impressions,
       SUM(s.clicks)                                 AS clicks
FROM raw_ad_spend s
JOIN dim_date d ON d.date = s.date
LEFT JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
GROUP BY COALESCE(m.channel, '(unmapped)'), d.week_start
ORDER BY channel, d.week_start;

-- name: sales_week
-- Sales per sales channel and week.
SELECT o.sales_channel, d.week_start,
       COUNT(*) AS n_rows,
       ROUND(SUM(o.revenue), 2) AS revenue,
       SUM(o.orders) AS orders,
       SUM(o.new_customers) AS new_customers
FROM shopify_orders_daily o
JOIN dim_date d ON d.date = o.date
GROUP BY o.sales_channel, d.week_start
ORDER BY o.sales_channel, d.week_start;

-- name: campaign_map
-- The full campaign map with each campaign's platform(s) and total spend.
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

-- name: spend_reconciliation
-- Total raw spend against the spend the model receives.
SELECT
    (SELECT ROUND(SUM(spend), 2) FROM raw_ad_spend) AS raw_spend,
    (SELECT ROUND(SUM(meta_spend + google_spend + tiktok_spend + email_spend), 2)
       FROM weekly_model_input)                      AS model_spend,
    (SELECT ROUND(SUM(spend), 2) FROM raw_ad_spend)
      - (SELECT ROUND(SUM(meta_spend + google_spend + tiktok_spend + email_spend), 2)
           FROM weekly_model_input)                  AS gap;

-- name: platform_channel
-- Spend by source platform and mapped model channel. A campaign mapped to a
-- channel that is not its platform's shows up as an off-diagonal cell.
SELECT s.platform, COALESCE(m.channel, '(unmapped)') AS channel,
       COUNT(DISTINCT s.campaign_id) AS campaigns,
       ROUND(SUM(s.spend), 2)        AS spend
FROM raw_ad_spend s
LEFT JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
GROUP BY s.platform, COALESCE(m.channel, '(unmapped)')
ORDER BY s.platform, channel;

-- name: promo_calendar
-- The promo calendar as loaded. From the scenario alone, an analyst can see the
-- cadence of promos per year and spot a missing one.
SELECT promo_id, promo_name, start_date, end_date, discount_pct
FROM promo_calendar
ORDER BY start_date;
