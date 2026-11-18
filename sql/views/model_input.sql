-- Weekly spend per model channel, rolled up through the campaign map.
CREATE VIEW weekly_channel_spend AS
SELECT
    d.week_start,
    m.channel,
    SUM(s.spend) AS spend
FROM raw_ad_spend s
JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
JOIN dim_date d ON d.date = s.date
GROUP BY d.week_start, m.channel;

-- One row per week: what the MMM is fitted on.
-- Note: the pivot only knows the four expected channels.
-- Spend mapped to any other label silently drops out here,
-- which is why sql/checks/01_unexpected_channels.sql exists.
CREATE VIEW weekly_model_input AS
WITH spend AS (
    SELECT
        week_start,
        SUM(CASE WHEN channel = 'meta'   THEN spend ELSE 0 END) AS meta_spend,
        SUM(CASE WHEN channel = 'google' THEN spend ELSE 0 END) AS google_spend,
        SUM(CASE WHEN channel = 'tiktok' THEN spend ELSE 0 END) AS tiktok_spend,
        SUM(CASE WHEN channel = 'email'  THEN spend ELSE 0 END) AS email_spend
    FROM weekly_channel_spend
    GROUP BY week_start
),
sales AS (
    SELECT
        d.week_start,
        SUM(o.revenue)       AS revenue,
        SUM(o.orders)        AS orders,
        SUM(o.new_customers) AS new_customers
    FROM shopify_orders_daily o
    JOIN dim_date d ON d.date = o.date
    GROUP BY d.week_start
),
holidays AS (
    SELECT
        d.week_start,
        MAX(CASE WHEN h.holiday_name = 'black_friday' THEN 1 ELSE 0 END) AS hol_black_friday,
        MAX(CASE WHEN h.holiday_name = 'cyber_monday' THEN 1 ELSE 0 END) AS hol_cyber_monday,
        MAX(CASE WHEN h.holiday_name = 'mothers_day'  THEN 1 ELSE 0 END) AS hol_mothers_day,
        MAX(CASE WHEN h.holiday_name = 'valentines'   THEN 1 ELSE 0 END) AS hol_valentines,
        MAX(CASE WHEN h.holiday_name = 'christmas'    THEN 1 ELSE 0 END) AS hol_christmas
    FROM dim_date d
    LEFT JOIN holiday_calendar h ON h.date = d.date
    GROUP BY d.week_start
),
promos AS (
    -- promo_intensity = average discount across the 7 days of the week.
    -- A full week at 20% off gives 0.20; three days at 20% gives about 0.086.
    SELECT
        d.week_start,
        COALESCE(SUM(p.discount_pct), 0) / 7.0 AS promo_intensity
    FROM dim_date d
    LEFT JOIN promo_calendar p ON d.date BETWEEN p.start_date AND p.end_date
    GROUP BY d.week_start
)
SELECT
    sales.week_start,
    sales.revenue,
    sales.orders,
    sales.new_customers,
    COALESCE(spend.meta_spend, 0)   AS meta_spend,
    COALESCE(spend.google_spend, 0) AS google_spend,
    COALESCE(spend.tiktok_spend, 0) AS tiktok_spend,
    COALESCE(spend.email_spend, 0)  AS email_spend,
    holidays.hol_black_friday,
    holidays.hol_cyber_monday,
    holidays.hol_mothers_day,
    holidays.hol_valentines,
    holidays.hol_christmas,
    promos.promo_intensity
FROM sales
LEFT JOIN spend    ON spend.week_start    = sales.week_start
LEFT JOIN holidays ON holidays.week_start = sales.week_start
LEFT JOIN promos   ON promos.week_start   = sales.week_start
ORDER BY sales.week_start;
