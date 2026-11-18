-- PROPOSED pre-fit gate (not adopted): sales_channel_gaps.
-- The sales-side twin of the rows_absent gate. For each Shopify sales channel, every
-- week from its first sale to the last week in dim_date must have 7 days of rows.
-- A sub-feed that stops early (scenario_F) or drops days mid-history shows here,
-- even when another sales channel keeps MAX(date) and the 7-day count looking normal.
-- A real channel closure would also fire: that is intended, it needs a sign-off.
-- Expected result on clean data: zero rows. Runs on DuckDB and SQLite.
WITH first_sale AS (
    SELECT o.sales_channel, MIN(d.week_start) AS first_week
    FROM shopify_orders_daily o
    JOIN dim_date d ON d.date = o.date
    GROUP BY o.sales_channel
),
grid AS (
    SELECT w.week_start, f.sales_channel
    FROM (SELECT DISTINCT week_start FROM dim_date) w
    JOIN first_sale f ON w.week_start >= f.first_week
),
days AS (
    SELECT o.sales_channel, d.week_start, COUNT(DISTINCT o.date) AS n_days
    FROM shopify_orders_daily o
    JOIN dim_date d ON d.date = o.date
    GROUP BY o.sales_channel, d.week_start
)
SELECT g.sales_channel, g.week_start, COALESCE(x.n_days, 0) AS days_with_rows
FROM grid g
LEFT JOIN days x ON x.sales_channel = g.sales_channel AND x.week_start = g.week_start
WHERE COALESCE(x.n_days, 0) < 7
ORDER BY g.sales_channel, g.week_start
