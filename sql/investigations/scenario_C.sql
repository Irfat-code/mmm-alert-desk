-- Investigation queries for alert A003 (scenario_C, rows:02_incomplete_weeks).
-- Each query starts with a "-- name:" line. src/run_investigation.py runs every
-- query on the scenario database and the clean baseline database and saves
-- the output to results/investigations/scenario_C/<name>__<db>.csv.
-- Written to run on both DuckDB and SQLite. Weeks come from dim_date.

-- ---------------------------------------------------------------------------
-- Round 1: H1 (end truncation), H2 (mid-history gap), H3 (dates collided)
-- ---------------------------------------------------------------------------

-- name: source_week_profile
-- Per source and week: row count, distinct dates, first and last date.
-- Dropped rows show as fewer rows AND fewer dates.
-- Collided dates show as normal rows but fewer distinct dates.
SELECT 'raw_ad_spend' AS source, d.week_start,
       COUNT(*) AS n_rows, COUNT(DISTINCT s.date) AS n_dates,
       MIN(s.date) AS min_date, MAX(s.date) AS max_date
FROM raw_ad_spend s
JOIN dim_date d ON d.date = s.date
GROUP BY d.week_start
UNION ALL
SELECT 'shopify_orders_daily' AS source, d.week_start,
       COUNT(*) AS n_rows, COUNT(DISTINCT o.date) AS n_dates,
       MIN(o.date) AS min_date, MAX(o.date) AS max_date
FROM shopify_orders_daily o
JOIN dim_date d ON d.date = o.date
GROUP BY d.week_start
ORDER BY source, week_start;

-- name: source_totals
-- Per source: total rows, distinct dates, date range, and rows whose date
-- is not in dim_date (those would drop out of every weekly join).
SELECT 'raw_ad_spend' AS source,
       COUNT(*) AS n_rows, COUNT(DISTINCT date) AS n_dates,
       MIN(date) AS min_date, MAX(date) AS max_date,
       SUM(CASE WHEN date NOT IN (SELECT date FROM dim_date) THEN 1 ELSE 0 END) AS rows_outside_dim_date
FROM raw_ad_spend
UNION ALL
SELECT 'shopify_orders_daily' AS source,
       COUNT(*), COUNT(DISTINCT date), MIN(date), MAX(date),
       SUM(CASE WHEN date NOT IN (SELECT date FROM dim_date) THEN 1 ELSE 0 END)
FROM shopify_orders_daily;

-- name: model_input_rows
-- How many weeks the model is fitted on, and their range.
SELECT COUNT(*) AS n_weeks, MIN(week_start) AS first_week, MAX(week_start) AS last_week
FROM weekly_model_input;

-- ---------------------------------------------------------------------------
-- Round 1: H4 (dim_date changed)
-- ---------------------------------------------------------------------------

-- name: dim_date_profile
-- Calendar size and range, and how many weeks do not have exactly 7 days.
SELECT COUNT(*) AS n_days,
       COUNT(DISTINCT week_start) AS n_weeks,
       MIN(date) AS min_date, MAX(date) AS max_date,
       (SELECT COUNT(*) FROM (SELECT week_start FROM dim_date
                              GROUP BY week_start HAVING COUNT(*) <> 7) x) AS weeks_not_7_days
FROM dim_date;

-- ---------------------------------------------------------------------------
-- Round 2: what the model and the CAC rule see at the end of the series
-- ---------------------------------------------------------------------------

-- name: weekly_tail
-- Every calendar week, with days present per source, whether the week reaches
-- weekly_model_input, and spend / sales / CAC. Built from dim_date so a week
-- with no sales stays visible instead of dropping out.
WITH ad_days AS (
    SELECT d.week_start, COUNT(DISTINCT s.date) AS ad_days
    FROM raw_ad_spend s JOIN dim_date d ON d.date = s.date
    GROUP BY d.week_start
),
order_days AS (
    SELECT d.week_start, COUNT(DISTINCT o.date) AS order_days
    FROM shopify_orders_daily o JOIN dim_date d ON d.date = o.date
    GROUP BY d.week_start
),
spend AS (
    SELECT week_start, SUM(spend) AS spend
    FROM weekly_channel_spend
    WHERE channel IN ('meta', 'google', 'tiktok', 'email')
    GROUP BY week_start
),
sales AS (
    SELECT d.week_start, SUM(o.revenue) AS revenue, SUM(o.orders) AS orders,
           SUM(o.new_customers) AS new_customers
    FROM shopify_orders_daily o JOIN dim_date d ON d.date = o.date
    GROUP BY d.week_start
),
weeks AS (SELECT DISTINCT week_start FROM dim_date)
SELECT w.week_start,
       COALESCE(a.ad_days, 0)    AS ad_days,
       COALESCE(o.order_days, 0) AS order_days,
       CASE WHEN m.week_start IS NULL THEN 0 ELSE 1 END AS in_model_input,
       COALESCE(sp.spend, 0)          AS spend,
       COALESCE(sl.revenue, 0)        AS revenue,
       COALESCE(sl.orders, 0)         AS orders,
       COALESCE(sl.new_customers, 0)  AS new_customers,
       sp.spend / NULLIF(sl.new_customers, 0) AS cac
FROM weeks w
LEFT JOIN ad_days a     ON a.week_start  = w.week_start
LEFT JOIN order_days o  ON o.week_start  = w.week_start
LEFT JOIN spend sp      ON sp.week_start = w.week_start
LEFT JOIN sales sl      ON sl.week_start = w.week_start
LEFT JOIN weekly_model_input m ON m.week_start = w.week_start
ORDER BY w.week_start;

-- name: cac_rule_variants
-- The monitor's cac_spike rule (latest 2 weeks vs the 12 before, pooled
-- spend / new customers, fires above +30%), computed three ways:
--   current         rows of weekly_model_input, as src/monitor.py does it
--   complete_weeks  only weeks where both sources have 7 days
--   calendar_weeks  every dim_date week, missing sales counted as zero
WITH ad_days AS (
    SELECT d.week_start, COUNT(DISTINCT s.date) AS ad_days
    FROM raw_ad_spend s JOIN dim_date d ON d.date = s.date
    GROUP BY d.week_start
),
order_days AS (
    SELECT d.week_start, COUNT(DISTINCT o.date) AS order_days
    FROM shopify_orders_daily o JOIN dim_date d ON d.date = o.date
    GROUP BY d.week_start
),
mi AS (
    SELECT week_start,
           meta_spend + google_spend + tiktok_spend + email_spend AS spend,
           new_customers
    FROM weekly_model_input
),
cal AS (
    SELECT w.week_start,
           COALESCE(sp.spend, 0) AS spend,
           COALESCE(sl.new_customers, 0) AS new_customers
    FROM (SELECT DISTINCT week_start FROM dim_date) w
    LEFT JOIN (SELECT week_start, SUM(spend) AS spend FROM weekly_channel_spend
               WHERE channel IN ('meta', 'google', 'tiktok', 'email')
               GROUP BY week_start) sp ON sp.week_start = w.week_start
    LEFT JOIN (SELECT d.week_start, SUM(o.new_customers) AS new_customers
               FROM shopify_orders_daily o JOIN dim_date d ON d.date = o.date
               GROUP BY d.week_start) sl ON sl.week_start = w.week_start
),
ranked AS (
    SELECT 'current' AS rule_variant, week_start, spend, new_customers,
           ROW_NUMBER() OVER (ORDER BY week_start DESC) AS rn
    FROM mi
    UNION ALL
    SELECT 'complete_weeks', mi.week_start, mi.spend, mi.new_customers,
           ROW_NUMBER() OVER (ORDER BY mi.week_start DESC)
    FROM mi
    JOIN ad_days a    ON a.week_start = mi.week_start
    JOIN order_days o ON o.week_start = mi.week_start
    WHERE a.ad_days = 7 AND o.order_days = 7
    UNION ALL
    SELECT 'calendar_weeks', week_start, spend, new_customers,
           ROW_NUMBER() OVER (ORDER BY week_start DESC)
    FROM cal
),
pooled AS (
    SELECT rule_variant,
           MIN(CASE WHEN rn <= 2 THEN week_start END)            AS recent_first_week,
           MAX(CASE WHEN rn <= 2 THEN week_start END)            AS recent_last_week,
           MIN(CASE WHEN rn BETWEEN 3 AND 14 THEN week_start END) AS trailing_first_week,
           MAX(CASE WHEN rn BETWEEN 3 AND 14 THEN week_start END) AS trailing_last_week,
           SUM(CASE WHEN rn <= 2 THEN spend END)
             / NULLIF(SUM(CASE WHEN rn <= 2 THEN new_customers END), 0)            AS cac_recent,
           SUM(CASE WHEN rn BETWEEN 3 AND 14 THEN spend END)
             / NULLIF(SUM(CASE WHEN rn BETWEEN 3 AND 14 THEN new_customers END), 0) AS cac_trailing
    FROM ranked
    GROUP BY rule_variant
)
SELECT rule_variant, recent_first_week, recent_last_week,
       trailing_first_week, trailing_last_week,
       cac_recent, cac_trailing,
       cac_recent / cac_trailing - 1 AS rise,
       CASE WHEN cac_recent > cac_trailing * 1.30 THEN 1 ELSE 0 END AS would_fire
FROM pooled
ORDER BY rule_variant;
