"""DuckDB queries for monthly cohorts and observed retention.

The caller creates orders and a one-row analysis_window table containing
last_complete_month. Observed months with no orders have zero activity.
"""

COHORT_RETENTION_SQL = """
WITH
user_cohorts AS (
    SELECT customer_id, DATE_TRUNC('month', MIN(order_date))::DATE AS cohort_month
    FROM orders GROUP BY customer_id
),
user_monthly AS (
    SELECT customer_id, DATE_TRUNC('month', order_date)::DATE AS activity_month,
           SUM(revenue) AS monthly_revenue,
           COUNT(DISTINCT order_id) AS order_count
    FROM orders GROUP BY customer_id, activity_month
),
cohort_sizes AS (
    SELECT uc.cohort_month, COUNT(*) AS cohort_size,
           SUM(COALESCE(um.monthly_revenue, 0)) AS cohort_revenue_m0
    FROM user_cohorts uc
    LEFT JOIN user_monthly um
      ON uc.customer_id = um.customer_id AND uc.cohort_month = um.activity_month
    GROUP BY uc.cohort_month
),
period_spine AS (
    SELECT cs.cohort_month, cs.cohort_size, cs.cohort_revenue_m0,
           month_start::DATE AS activity_month,
           DATEDIFF('month', cs.cohort_month, month_start) AS period_number
    FROM cohort_sizes cs
    CROSS JOIN analysis_window aw
    CROSS JOIN LATERAL GENERATE_SERIES(
        cs.cohort_month, aw.last_complete_month, INTERVAL '1 month'
    ) AS months(month_start)
),
period_agg AS (
    SELECT ps.cohort_month, ps.period_number, ps.cohort_size,
           ps.cohort_revenue_m0,
           COUNT(DISTINCT um.customer_id) AS active_users,
           COALESCE(SUM(um.monthly_revenue), 0) AS period_revenue,
           COALESCE(SUM(um.order_count), 0) AS total_orders
    FROM period_spine ps
    LEFT JOIN user_cohorts uc ON uc.cohort_month = ps.cohort_month
    LEFT JOIN user_monthly um
      ON um.customer_id = uc.customer_id AND um.activity_month = ps.activity_month
    GROUP BY ps.cohort_month, ps.period_number, ps.cohort_size,
             ps.cohort_revenue_m0
),
retention_matrix AS (
    SELECT cohort_month, period_number, cohort_size, active_users,
           period_revenue,
           ROUND(period_revenue / NULLIF(active_users, 0), 2) AS arpu,
           total_orders,
           ROUND(active_users * 100.0 / cohort_size, 2) AS retention_rate,
           ROUND(period_revenue * 100.0 / NULLIF(cohort_revenue_m0, 0), 2)
             AS revenue_retention_rate,
           SUM(period_revenue) OVER (
               PARTITION BY cohort_month ORDER BY period_number
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS cumulative_revenue,
           ROUND(active_users * 100.0 / cohort_size, 2)
             - LAG(ROUND(active_users * 100.0 / cohort_size, 2)) OVER (
                 PARTITION BY cohort_month ORDER BY period_number
               ) AS retention_delta,
           ROUND(AVG(active_users * 100.0 / cohort_size) OVER (
               PARTITION BY cohort_month ORDER BY period_number
               ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
           ), 2) AS smoothed_retention,
           RANK() OVER (
               PARTITION BY period_number
               ORDER BY active_users * 100.0 / cohort_size DESC
           ) AS cohort_rank
    FROM period_agg
)
SELECT * FROM retention_matrix ORDER BY cohort_month, period_number
"""

AVERAGE_RETENTION_SQL = """
SELECT period_number, ROUND(AVG(retention_rate), 2) AS avg_retention_rate,
       ROUND(AVG(revenue_retention_rate), 2) AS avg_revenue_retention_rate,
       ROUND(STDDEV(retention_rate), 2) AS retention_std,
       COUNT(*) AS cohort_count
FROM retention_matrix
GROUP BY period_number ORDER BY period_number
"""

COHORT_SUMMARY_SQL = """
SELECT cohort_month, cohort_size,
       ROUND(MAX(cumulative_revenue), 2) AS observed_revenue,
       ROUND(MAX(cumulative_revenue) / NULLIF(cohort_size, 0), 2)
         AS observed_revenue_per_customer,
       MAX(CASE WHEN period_number = 1 THEN retention_rate END) AS m1_retention,
       MAX(CASE WHEN period_number = 3 THEN retention_rate END) AS m3_retention,
       MAX(CASE WHEN period_number = 6 THEN retention_rate END) AS m6_retention,
       MAX(CASE WHEN period_number = 12 THEN retention_rate END) AS m12_retention,
       ROUND(MAX(CASE WHEN period_number = 6 THEN cumulative_revenue END)
         / NULLIF(cohort_size, 0), 2) AS m6_revenue_per_customer,
       ROUND(MAX(CASE WHEN period_number = 12 THEN cumulative_revenue END)
         / NULLIF(cohort_size, 0), 2) AS m12_revenue_per_customer,
       MAX(period_number) AS observed_periods
FROM retention_matrix
GROUP BY cohort_month, cohort_size ORDER BY cohort_month
"""
