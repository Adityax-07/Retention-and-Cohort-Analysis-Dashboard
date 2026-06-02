"""
DuckDB SQL for cohort retention analysis.

Techniques demonstrated:
  - 6 layered CTEs (readability + composability)
  - Window functions: SUM() cumulative, LAG() delta, AVG() rolling, RANK() cross-cohort
  - PARTITION BY, ORDER BY with ROWS frame clauses
  - NULLIF for safe division
  - Derived metrics: NRR proxy, LTV build-up, churn acceleration
"""

# ─────────────────────────────────────────────────────────────────────────────
# CORE RETENTION MATRIX
# Reads from: orders table
# Output columns:
#   cohort_month, period_number, cohort_size, active_users, period_revenue,
#   arpu, total_orders, retention_rate, revenue_retention_rate,
#   cumulative_revenue, retention_delta, smoothed_retention, cohort_rank
# ─────────────────────────────────────────────────────────────────────────────
COHORT_RETENTION_SQL = """
WITH

-- ── 1. COHORT ASSIGNMENT ─────────────────────────────────────────────────────
--    First-ever purchase month per customer → their acquisition cohort.
user_cohorts AS (
    SELECT
        customer_id,
        DATE_TRUNC('month', MIN(order_date))::DATE AS cohort_month
    FROM orders
    GROUP BY customer_id
),

-- ── 2. MONTHLY ACTIVITY ──────────────────────────────────────────────────────
--    Aggregate each (customer, calendar-month) slice: revenue + order count.
user_monthly AS (
    SELECT
        customer_id,
        DATE_TRUNC('month', order_date)::DATE  AS activity_month,
        SUM(revenue)                           AS monthly_revenue,
        COUNT(DISTINCT order_id)               AS order_count
    FROM orders
    GROUP BY customer_id,
             DATE_TRUNC('month', order_date)
),

-- ── 3. COHORT × PERIOD ───────────────────────────────────────────────────────
--    Join cohorts to their activity months; derive the period number.
--    Period 0 = acquisition month, Period N = N calendar months later.
cohort_activity AS (
    SELECT
        uc.cohort_month,
        um.activity_month,
        uc.customer_id,
        um.monthly_revenue,
        um.order_count,
        datediff('month', uc.cohort_month, um.activity_month) AS period_number
    FROM user_cohorts  uc
    JOIN user_monthly  um USING (customer_id)
    WHERE um.activity_month >= uc.cohort_month
),

-- ── 4. COHORT SIZES ──────────────────────────────────────────────────────────
--    Denominators: headcount and revenue at Period 0 (acquisition month).
--    Used to compute retention rates and NRR proxy downstream.
cohort_sizes AS (
    SELECT
        cohort_month,
        COUNT(DISTINCT customer_id) AS cohort_size,
        SUM(monthly_revenue)        AS cohort_revenue_m0
    FROM cohort_activity
    WHERE period_number = 0
    GROUP BY cohort_month
),

-- ── 5. COHORT-PERIOD AGGREGATES ──────────────────────────────────────────────
--    One row per (cohort, period): active users, revenue, ARPU, order volume.
period_agg AS (
    SELECT
        ca.cohort_month,
        ca.period_number,
        cs.cohort_size,
        cs.cohort_revenue_m0,
        COUNT(DISTINCT ca.customer_id)                            AS active_users,
        SUM(ca.monthly_revenue)                                   AS period_revenue,
        SUM(ca.monthly_revenue) /
            NULLIF(COUNT(DISTINCT ca.customer_id), 0)             AS arpu,
        SUM(ca.order_count)                                       AS total_orders
    FROM cohort_activity  ca
    JOIN cohort_sizes     cs USING (cohort_month)
    GROUP BY
        ca.cohort_month, ca.period_number,
        cs.cohort_size,  cs.cohort_revenue_m0
),

-- ── 6. RETENTION MATRIX WITH WINDOW FUNCTIONS ────────────────────────────────
--    Enriches period_agg with four window-function derived metrics.
retention_matrix AS (
    SELECT
        cohort_month,
        period_number,
        cohort_size,
        active_users,
        period_revenue,
        ROUND(arpu, 2)                                            AS arpu,
        total_orders,

        -- User retention rate  (% of cohort still active this period)
        ROUND(active_users * 100.0 / cohort_size, 2)             AS retention_rate,

        -- Revenue retention rate  (NRR proxy: period revenue vs. M0 revenue)
        ROUND(period_revenue * 100.0 / cohort_revenue_m0, 2)     AS revenue_retention_rate,

        -- Cumulative LTV build-up per cohort  (running total of revenue)
        SUM(period_revenue) OVER (
            PARTITION BY cohort_month
            ORDER BY     period_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                         AS cumulative_revenue,

        -- Period-over-period retention delta  (negative = further churn)
        ROUND(active_users * 100.0 / cohort_size, 2)
        - LAG(ROUND(active_users * 100.0 / cohort_size, 2))
              OVER (PARTITION BY cohort_month ORDER BY period_number)
                                                                  AS retention_delta,

        -- 3-period centred rolling average  (smoothed trend line for charts)
        ROUND(
            AVG(ROUND(active_users * 100.0 / cohort_size, 2)) OVER (
                PARTITION BY cohort_month
                ORDER BY     period_number
                ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
            ), 2
        )                                                         AS smoothed_retention,

        -- Cross-cohort rank at each period  (1 = best-retaining cohort at Mₙ)
        RANK() OVER (
            PARTITION BY period_number
            ORDER BY     active_users * 100.0 / cohort_size DESC
        )                                                         AS cohort_rank

    FROM period_agg
)

SELECT * FROM retention_matrix
ORDER BY cohort_month, period_number
"""

# ─────────────────────────────────────────────────────────────────────────────
# CROSS-COHORT AVERAGE RETENTION CURVE
# Reads from: retention_matrix (pre-created view/table)
# ─────────────────────────────────────────────────────────────────────────────
AVERAGE_RETENTION_SQL = """
SELECT
    period_number,
    ROUND(AVG(retention_rate),          2)  AS avg_retention_rate,
    ROUND(AVG(revenue_retention_rate),  2)  AS avg_revenue_retention_rate,
    ROUND(STDDEV(retention_rate),       2)  AS retention_std,
    COUNT(DISTINCT cohort_month)            AS cohort_count
FROM retention_matrix
GROUP BY period_number
ORDER BY period_number
"""

# ─────────────────────────────────────────────────────────────────────────────
# COHORT SUMMARY  – one row per cohort for the summary table + KPIs
# Reads from: retention_matrix (pre-created view/table)
# ─────────────────────────────────────────────────────────────────────────────
COHORT_SUMMARY_SQL = """
SELECT
    cohort_month,
    cohort_size,
    ROUND(MAX(cumulative_revenue), 2)                              AS lifetime_revenue,
    ROUND(MAX(cumulative_revenue) / NULLIF(cohort_size, 0), 2)    AS ltv_per_customer,
    MAX(CASE WHEN period_number =  1 THEN retention_rate END)      AS m1_retention,
    MAX(CASE WHEN period_number =  3 THEN retention_rate END)      AS m3_retention,
    MAX(CASE WHEN period_number =  6 THEN retention_rate END)      AS m6_retention,
    MAX(CASE WHEN period_number = 12 THEN retention_rate END)      AS m12_retention,
    MAX(period_number)                                             AS observed_periods
FROM retention_matrix
GROUP BY cohort_month, cohort_size
ORDER BY cohort_month
"""
