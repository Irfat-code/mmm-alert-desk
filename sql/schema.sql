-- Raw tables, shaped like what lands from each source system.
-- The model never reads these directly. It reads the views in sql/views/.

-- Calendar: maps every day to its Monday week start.
-- Keeps weekly SQL the same in DuckDB and SQLite.
CREATE TABLE dim_date (
    date        DATE PRIMARY KEY,
    week_start  DATE NOT NULL
);

-- Daily campaign-level spend, as exported from Meta, Google Ads, TikTok and Klaviyo.
CREATE TABLE raw_ad_spend (
    date           DATE,
    platform       VARCHAR,
    campaign_id    INTEGER,
    campaign_name  VARCHAR,
    spend          DOUBLE,
    impressions    BIGINT,
    clicks         BIGINT
);

-- Which model channel each campaign rolls up to. Maintained by hand, so it can go wrong.
CREATE TABLE campaign_channel_map (
    campaign_id    INTEGER PRIMARY KEY,
    campaign_name  VARCHAR,
    channel        VARCHAR
);

-- Daily Shopify sales, split by sales channel (online store vs TikTok Shop).
CREATE TABLE shopify_orders_daily (
    date           DATE,
    sales_channel  VARCHAR,
    revenue        DOUBLE,
    orders         INTEGER,
    new_customers  INTEGER
);

-- Retail holidays the model controls for.
CREATE TABLE holiday_calendar (
    date          DATE,
    holiday_name  VARCHAR
);

-- Sitewide promotions, entered by the brand's marketing team.
CREATE TABLE promo_calendar (
    promo_id      INTEGER,
    promo_name    VARCHAR,
    start_date    DATE,
    end_date      DATE,
    discount_pct  DOUBLE
);
