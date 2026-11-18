-- Weekly total media spend and new customers, for the CAC spike monitor.
-- CAC = spend / new customers. Spend covers all four model channels.
SELECT
    week_start,
    meta_spend + google_spend + tiktok_spend + email_spend AS spend,
    new_customers
FROM weekly_model_input
ORDER BY week_start
