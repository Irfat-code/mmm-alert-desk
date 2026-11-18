-- Weeks where a source has fewer than 7 days of data.
-- A short final week usually means a reporting delay, not a real drop.
-- Expected result on clean data: zero rows.
WITH ad_days AS (
    SELECT d.week_start, COUNT(DISTINCT s.date) AS days
    FROM raw_ad_spend s
    JOIN dim_date d ON d.date = s.date
    GROUP BY d.week_start
),
order_days AS (
    SELECT d.week_start, COUNT(DISTINCT o.date) AS days
    FROM shopify_orders_daily o
    JOIN dim_date d ON d.date = o.date
    GROUP BY d.week_start
)
SELECT
    w.week_start,
    COALESCE(a.days, 0) AS ad_spend_days,
    COALESCE(o.days, 0) AS order_days
FROM (SELECT DISTINCT week_start FROM dim_date) w
LEFT JOIN ad_days a    ON a.week_start = w.week_start
LEFT JOIN order_days o ON o.week_start = w.week_start
WHERE COALESCE(a.days, 0) < 7
   OR COALESCE(o.days, 0) < 7
ORDER BY w.week_start
