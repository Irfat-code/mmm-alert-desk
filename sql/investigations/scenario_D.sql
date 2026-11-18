-- Investigation queries for alerts A004 (scenario_D, convergence divergences) and
-- A005 (scenario_D, rows:03_channel_zero_weeks).
-- Each query starts with a "-- name:" line. src/run_investigation.py runs every
-- query on the scenario database and the clean baseline database and saves
-- the output to results/investigations/scenario_D/<name>__<db>.csv.
-- Written to run on both DuckDB and SQLite. Weeks come from dim_date.

-- ---------------------------------------------------------------------------
-- Round 1: H1 (broken feed) vs H2 (real pause)
-- ---------------------------------------------------------------------------

-- name: check03_output
-- Check 03 as the monitor runs it: channel-weeks with zero spend after the
-- channel's first spend.
WITH first_spend AS (
    SELECT channel, MIN(week_start) AS first_week
    FROM weekly_channel_spend
    WHERE spend > 0
    GROUP BY channel
),
grid AS (
    SELECT w.week_start, f.channel
    FROM (SELECT DISTINCT week_start FROM dim_date) w
    JOIN first_spend f ON w.week_start >= f.first_week
)
SELECT g.channel, g.week_start, COALESCE(s.spend, 0) AS spend
FROM grid g
LEFT JOIN weekly_channel_spend s
       ON s.week_start = g.week_start AND s.channel = g.channel
WHERE COALESCE(s.spend, 0) = 0
ORDER BY g.channel, g.week_start;

-- name: channel_week
-- Raw ad rows per channel and week. Absent rows show as fewer n_rows.
-- Rows present with zero spend show in zero_spend_rows. Impressions and clicks
-- tell a real pause (all zero) from a broken spend field (activity, no spend).
SELECT COALESCE(m.channel, '(unmapped)') AS channel, d.week_start,
       COUNT(*)                                      AS n_rows,
       COUNT(DISTINCT s.date)                        AS n_dates,
       COUNT(DISTINCT s.campaign_id)                 AS n_campaigns,
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
-- Sales per sales channel and week. If revenue is unchanged from baseline
-- while spend shows zero, the spend happened and the feed lost it.
SELECT o.sales_channel, d.week_start,
       COUNT(*) AS n_rows,
       ROUND(SUM(o.revenue), 2) AS revenue,
       SUM(o.orders) AS orders,
       SUM(o.new_customers) AS new_customers
FROM shopify_orders_daily o
JOIN dim_date d ON d.date = o.date
GROUP BY o.sales_channel, d.week_start
ORDER BY o.sales_channel, d.week_start;

-- name: model_spend
-- Weekly spend per model channel, exactly as the model receives it.
SELECT week_start, meta_spend, google_spend, tiktok_spend, email_spend
FROM weekly_model_input
ORDER BY week_start;

-- name: gap_vs_neighbours
-- Analyst check that needs no baseline: TikTok spend and sales per sales channel
-- in the 3 gap weeks against the 3 weeks either side.
WITH weeks AS (
    SELECT DISTINCT week_start,
           CASE WHEN week_start < '2025-06-16'  THEN '1_before'
                WHEN week_start <= '2025-06-30' THEN '2_gap'
                ELSE '3_after' END AS period
    FROM dim_date
    WHERE week_start BETWEEN '2025-05-26' AND '2025-07-21'
),
sales AS (
    SELECT w.period, o.sales_channel, SUM(o.revenue) AS revenue
    FROM shopify_orders_daily o
    JOIN dim_date d ON d.date = o.date
    JOIN weeks w ON w.week_start = d.week_start
    GROUP BY w.period, o.sales_channel
),
tt AS (
    SELECT w.period, SUM(s.spend) AS spend
    FROM raw_ad_spend s
    JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
    JOIN dim_date d ON d.date = s.date
    JOIN weeks w ON w.week_start = d.week_start
    WHERE m.channel = 'tiktok'
    GROUP BY w.period
)
SELECT sales.period, sales.sales_channel,
       ROUND(sales.revenue / 3, 2)               AS revenue_per_week,
       ROUND(COALESCE(tt.spend, 0) / 3, 2)       AS tiktok_spend_per_week
FROM sales
LEFT JOIN tt ON tt.period = sales.period
ORDER BY sales.period, sales.sales_channel;

-- name: cac_impact
-- Pooled CAC (model spend / new customers) in the 3 gap weeks, and the latest
-- 2 weeks that the cac_spike rule uses.
WITH w AS (
    SELECT week_start,
           meta_spend + google_spend + tiktok_spend + email_spend AS spend,
           new_customers,
           ROW_NUMBER() OVER (ORDER BY week_start DESC) AS rn
    FROM weekly_model_input
)
SELECT 'gap_2025-06-16_to_06-30' AS period, SUM(spend) / SUM(new_customers) AS cac
FROM w WHERE week_start BETWEEN '2025-06-16' AND '2025-06-30'
UNION ALL
SELECT 'latest_2_weeks', SUM(spend) / SUM(new_customers)
FROM w WHERE rn <= 2;
