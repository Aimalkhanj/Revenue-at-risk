-- ============================================================
-- Revenue at Risk - core SQL models (DuckDB / PostgreSQL style)
-- Source tables: sales (clean product sales), returns (cancelled lines)
-- Fiscal year = Dec-Nov  (FY2010 = Dec-2009..Nov-2010, FY2011 = Dec-2010..Nov-2011)
-- ============================================================

-- name: fact_orders
-- One row per invoice with order value and fiscal year
CREATE OR REPLACE VIEW fact_orders AS
SELECT
    Invoice,
    CustomerID,
    Country,
    MIN(InvoiceDate)                                   AS order_ts,
    SUM(Revenue)                                       AS order_value,
    SUM(Quantity)                                      AS units,
    COUNT(DISTINCT StockCode)                          AS distinct_items,
    CASE WHEN MIN(InvoiceDate) <  TIMESTAMP '2010-12-01' THEN 'FY2010'
         WHEN MIN(InvoiceDate) <  TIMESTAMP '2011-12-01' THEN 'FY2011'
         ELSE 'Dec-2011 (partial)' END                 AS fiscal_year
FROM sales
GROUP BY Invoice, CustomerID, Country;

-- name: kpi_by_year
SELECT
    fiscal_year,
    ROUND(SUM(order_value), 0)                         AS net_sales,
    COUNT(*)                                           AS orders,
    ROUND(SUM(order_value) / COUNT(*), 2)              AS avg_order_value,
    COUNT(DISTINCT CustomerID)                         AS active_customers
FROM fact_orders
GROUP BY fiscal_year
ORDER BY fiscal_year;

-- name: monthly_revenue
SELECT
    DATE_TRUNC('month', order_ts)                      AS month,
    ROUND(SUM(order_value), 0)                         AS revenue,
    COUNT(*)                                           AS orders,
    COUNT(DISTINCT CustomerID)                         AS customers
FROM fact_orders
GROUP BY 1
ORDER BY 1;

-- name: customer_first_purchase
CREATE OR REPLACE VIEW dim_customer AS
SELECT
    CustomerID,
    DATE_TRUNC('month', MIN(order_ts))                 AS cohort_month,
    MIN(order_ts)                                      AS first_order_ts,
    MAX(order_ts)                                      AS last_order_ts,
    COUNT(*)                                           AS orders,
    SUM(order_value)                                   AS lifetime_revenue
FROM fact_orders
WHERE CustomerID IS NOT NULL
GROUP BY CustomerID;

-- name: cohort_retention
-- Share of each monthly acquisition cohort that purchased again N months later
WITH activity AS (
    SELECT DISTINCT o.CustomerID,
           c.cohort_month,
           DATE_DIFF('month', c.cohort_month, DATE_TRUNC('month', o.order_ts)) AS month_n
    FROM fact_orders o
    JOIN dim_customer c USING (CustomerID)
)
SELECT
    cohort_month,
    month_n,
    COUNT(*)                                                       AS customers,
    ROUND(COUNT(*) * 1.0 /
          FIRST_VALUE(COUNT(*)) OVER (PARTITION BY cohort_month ORDER BY month_n), 4) AS retention
FROM activity
GROUP BY cohort_month, month_n
ORDER BY cohort_month, month_n;

-- name: returns_by_year
SELECT
    CASE WHEN InvoiceDate < TIMESTAMP '2010-12-01' THEN 'FY2010'
         WHEN InvoiceDate < TIMESTAMP '2011-12-01' THEN 'FY2011'
         ELSE 'Dec-2011 (partial)' END                 AS fiscal_year,
    ROUND(SUM(Revenue), 0)                             AS returned_value,
    COUNT(DISTINCT Invoice)                            AS cancelled_invoices
FROM returns
GROUP BY 1
ORDER BY 1;
