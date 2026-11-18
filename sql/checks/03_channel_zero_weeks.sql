-- Weeks where a channel that normally spends shows zero.
-- Could be a real pause, or a broken feed. The issue column separates the two cases
-- the data can tell apart: 'rows absent' (no raw rows at all for that channel-week,
-- typical of a feed outage) and 'spend zero' (rows present with zero spend).
-- Only flags a channel after its first week of spend.
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
),
raw_rows AS (
    SELECT d.week_start, m.channel, COUNT(*) AS n_rows
    FROM raw_ad_spend s
    JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
    JOIN dim_date d ON d.date = s.date
    GROUP BY d.week_start, m.channel
)
SELECT
    g.channel,
    g.week_start,
    COALESCE(s.spend, 0)  AS spend,
    COALESCE(r.n_rows, 0) AS raw_rows,
    CASE WHEN COALESCE(r.n_rows, 0) = 0 THEN 'rows absent' ELSE 'spend zero' END AS issue
FROM grid g
LEFT JOIN weekly_channel_spend s
       ON s.week_start = g.week_start AND s.channel = g.channel
LEFT JOIN raw_rows r
       ON r.week_start = g.week_start AND r.channel = g.channel
WHERE COALESCE(s.spend, 0) = 0
ORDER BY g.channel, g.week_start
