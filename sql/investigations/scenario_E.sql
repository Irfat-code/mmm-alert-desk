-- Investigation queries for alert A006 (scenario_E, convergence divergences).
-- Each query starts with a "-- name:" line. src/run_investigation.py runs every
-- query on the scenario database and the clean baseline database and saves
-- the output to results/investigations/scenario_E/<name>__<db>.csv.
-- It also runs every query in sql/checks/ and diffs every raw table row by row.
-- Written to run on both DuckDB and SQLite. Weeks come from dim_date.

-- ---------------------------------------------------------------------------
-- Round 1, step 1: has any data changed? (H4)
-- ---------------------------------------------------------------------------

-- name: model_input_full
-- Everything the model is fitted on. Catches changes in the views as well as
-- in the raw tables.
SELECT * FROM weekly_model_input ORDER BY week_start;

-- name: channel_week
-- Raw ad rows per channel and week: rows, zero-spend rows, spend, impressions, clicks.
SELECT COALESCE(m.channel, '(unmapped)') AS channel, d.week_start,
       COUNT(*)                                      AS n_rows,
       SUM(CASE WHEN s.spend = 0 THEN 1 ELSE 0 END)  AS zero_spend_rows,
       ROUND(SUM(s.spend), 2)                        AS spend,
       MAX(s.spend)                                  AS max_daily_row_spend,
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
