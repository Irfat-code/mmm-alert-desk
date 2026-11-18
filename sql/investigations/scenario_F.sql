-- Investigation queries for scenario_F (roas_shift tiktok 1.7096 -> 2.4523, no gate fired).
-- Each query starts with a "-- name:" line. src/run_investigation.py runs every
-- query on the scenario database and the clean baseline database (last approved
-- snapshot) and saves the output to results/investigations/scenario_F/<name>__<db>.csv.
-- With --full it also runs sql/checks/ and diffs every raw table row by row.
-- Written to run on both DuckDB and SQLite. Weeks come from dim_date.

-- ---------------------------------------------------------------------------
-- Step 1, F alone: does every source cover the full date range? (H2)
-- ---------------------------------------------------------------------------

-- name: source_coverage
-- First and last day, and day count, per sales channel and per ad platform,
-- next to the overall data range. A sub-source that stops early shows here.
SELECT 'sales' AS source, sales_channel AS part, MIN(date) AS first_day, MAX(date) AS last_day,
       COUNT(DISTINCT date) AS days, ROUND(SUM(revenue), 2) AS revenue
FROM shopify_orders_daily GROUP BY sales_channel
UNION ALL
SELECT 'ads' AS source, platform AS part, MIN(date), MAX(date), COUNT(DISTINCT date), ROUND(SUM(spend), 2)
FROM raw_ad_spend GROUP BY platform
UNION ALL
SELECT 'dim_date' AS source, 'all' AS part, MIN(date), MAX(date), COUNT(*), NULL
FROM dim_date
ORDER BY source, part;

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

-- name: tiktok_shop_vs_spend
-- TikTok Shop revenue next to TikTok ad spend, per week since TikTok launched.
-- Weeks with spend but no TikTok Shop rows show tiktok_shop_days = 0.
SELECT d.week_start,
       ROUND(SUM(s.spend), 2) AS tiktok_spend,
       (SELECT COUNT(DISTINCT o.date) FROM shopify_orders_daily o JOIN dim_date d2 ON d2.date = o.date
         WHERE o.sales_channel = 'tiktok_shop' AND d2.week_start = d.week_start) AS tiktok_shop_days,
       (SELECT ROUND(SUM(o.revenue), 2) FROM shopify_orders_daily o JOIN dim_date d2 ON d2.date = o.date
         WHERE o.sales_channel = 'tiktok_shop' AND d2.week_start = d.week_start) AS tiktok_shop_revenue
FROM raw_ad_spend s
JOIN dim_date d ON d.date = s.date
WHERE s.platform = 'tiktok'
GROUP BY d.week_start
ORDER BY d.week_start;

-- ---------------------------------------------------------------------------
-- Step 2, against the snapshot: what else differs? (H1, H3)
-- ---------------------------------------------------------------------------

-- name: model_input_full
-- Everything the model is fitted on.
SELECT * FROM weekly_model_input ORDER BY week_start;

-- name: channel_week
-- Raw ad rows per channel and week: rows, spend.
SELECT COALESCE(m.channel, '(unmapped)') AS channel, d.week_start,
       COUNT(*)                 AS n_rows,
       ROUND(SUM(s.spend), 2)   AS spend
FROM raw_ad_spend s
JOIN dim_date d ON d.date = s.date
LEFT JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
GROUP BY COALESCE(m.channel, '(unmapped)'), d.week_start
ORDER BY channel, d.week_start;

-- ---------------------------------------------------------------------------
-- Impact: blended CAC and revenue before and during the gap weeks.
-- ---------------------------------------------------------------------------

-- name: cac_impact
SELECT CASE WHEN week_start >= '2025-10-06' THEN 'gap weeks (from 2025-10-06)'
            ELSE 'before 2025-10-06' END AS period,
       COUNT(*) AS weeks,
       ROUND(SUM(revenue), 2) AS revenue,
       SUM(new_customers) AS new_customers,
       ROUND(SUM(meta_spend + google_spend + tiktok_spend + email_spend), 2) AS spend,
       SUM(meta_spend + google_spend + tiktok_spend + email_spend) / SUM(new_customers) AS cac
FROM weekly_model_input
GROUP BY CASE WHEN week_start >= '2025-10-06' THEN 'gap weeks (from 2025-10-06)'
              ELSE 'before 2025-10-06' END
ORDER BY period;
