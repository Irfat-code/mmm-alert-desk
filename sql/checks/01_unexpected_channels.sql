-- Spend that will NOT reach the model: campaigns with no mapping,
-- or mapped to a label outside the four model channels.
-- Expected result on clean data: zero rows.
SELECT
    COALESCE(m.channel, '(unmapped)') AS channel_label,
    COUNT(DISTINCT s.campaign_id)     AS campaigns,
    MIN(s.date)                       AS first_seen,
    ROUND(SUM(s.spend), 2)            AS spend_lost
FROM raw_ad_spend s
LEFT JOIN campaign_channel_map m ON m.campaign_id = s.campaign_id
WHERE m.channel IS NULL
   OR m.channel NOT IN ('meta', 'google', 'tiktok', 'email')
GROUP BY COALESCE(m.channel, '(unmapped)')
