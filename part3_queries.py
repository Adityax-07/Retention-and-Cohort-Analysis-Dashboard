"""
Part 3 — SQL Prompts: Cohort Assignment · Retention Matrix · Revenue Analysis

Run directly:
    python part3_queries.py

Reads from: data/retail.db  (created by ingest_data.py)
SQL dialect: SQLite ≥ 3.25  (window functions supported)
DuckDB differences noted inline where syntax diverges.
"""

import os
import sqlite3
import textwrap

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "retail.db")

pd.set_option("display.max_columns", 20)
pd.set_option("display.width",        120)
pd.set_option("display.float_format", "{:,.2f}".format)


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 1 — COHORT ASSIGNMENT
#
# Steps:
#   1. Find each customer's first purchase month (cohort_month)
#   2. Join back to ALL their transactions
#   3. Compute cohort_index = integer months since cohort_month
#   4. Output: customer_id, cohort_month, cohort_index, revenue
#
# Note — InvoiceMonth is already stored as 'YYYY-MM' text, so we skip
# strftime() and instead do integer arithmetic on year × 12 + month.
# DuckDB equivalent: datediff('month', cohort_month::DATE, activity_month::DATE)
# ─────────────────────────────────────────────────────────────────────────────
PROMPT1_COHORT_ASSIGNMENT_SQL = """
WITH

-- Step 1: First purchase month per customer = acquisition cohort
cohort_base AS (
    SELECT
        CustomerID        AS customer_id,
        MIN(InvoiceMonth) AS cohort_month        -- e.g. '2009-12'
    FROM transactions
    GROUP BY CustomerID
),

-- Step 2 + 3: Join every transaction back to its cohort; derive cohort_index
customer_cohort_activity AS (
    SELECT
        t.CustomerID                                              AS customer_id,
        cb.cohort_month,
        t.InvoiceMonth                                            AS activity_month,
        t.Revenue                                                 AS revenue,

        -- cohort_index = integer months elapsed since first purchase
        -- SQLite has no datediff(); we convert YYYY-MM to a month-number
        -- and subtract.  Result is 0 in the acquisition month, 1 the next, etc.
        (
              CAST(substr(t.InvoiceMonth, 1, 4) AS INTEGER) * 12
            + CAST(substr(t.InvoiceMonth, 6, 2) AS INTEGER)
        ) - (
              CAST(substr(cb.cohort_month, 1, 4) AS INTEGER) * 12
            + CAST(substr(cb.cohort_month, 6, 2) AS INTEGER)
        )                                                         AS cohort_index

    FROM transactions  t
    JOIN cohort_base   cb ON t.CustomerID = cb.customer_id
)

-- Step 4: Final output
SELECT
    customer_id,
    cohort_month,
    cohort_index,
    ROUND(revenue, 2) AS revenue
FROM customer_cohort_activity
ORDER BY cohort_month, customer_id, cohort_index
"""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 2a — COHORT COUNTS  (wide pivot: rows = cohort_month, cols = M0…M12)
#
# Produces: one row per cohort, columns m0 … m12 = distinct active customers
# at each period.  NULL means the cohort hadn't reached that age yet.
#
# DuckDB alternative: use PIVOT syntax instead of CASE WHEN
# ─────────────────────────────────────────────────────────────────────────────
PROMPT2_COHORT_COUNTS_SQL = """
WITH

cohort_base AS (
    SELECT CustomerID AS customer_id, MIN(InvoiceMonth) AS cohort_month
    FROM transactions
    GROUP BY CustomerID
),

activity AS (
    SELECT
        t.CustomerID AS customer_id,
        cb.cohort_month,
        (
              CAST(substr(t.InvoiceMonth, 1, 4) AS INTEGER) * 12
            + CAST(substr(t.InvoiceMonth, 6, 2) AS INTEGER)
        ) - (
              CAST(substr(cb.cohort_month, 1, 4) AS INTEGER) * 12
            + CAST(substr(cb.cohort_month, 6, 2) AS INTEGER)
        ) AS cohort_index
    FROM transactions t
    JOIN cohort_base  cb ON t.CustomerID = cb.customer_id
),

-- Long-form counts: distinct customers per (cohort, period)
distinct_per_period AS (
    SELECT
        cohort_month,
        cohort_index,
        COUNT(DISTINCT customer_id) AS n
    FROM activity
    WHERE cohort_index BETWEEN 0 AND 12   -- trim to 13-period window
    GROUP BY cohort_month, cohort_index
)

-- Pivot from long to wide: one column per cohort_index 0–12
-- MAX() collapses the GROUP BY without losing the single value per cell
SELECT
    cohort_month,
    MAX(CASE WHEN cohort_index =  0 THEN n END) AS m0,
    MAX(CASE WHEN cohort_index =  1 THEN n END) AS m1,
    MAX(CASE WHEN cohort_index =  2 THEN n END) AS m2,
    MAX(CASE WHEN cohort_index =  3 THEN n END) AS m3,
    MAX(CASE WHEN cohort_index =  4 THEN n END) AS m4,
    MAX(CASE WHEN cohort_index =  5 THEN n END) AS m5,
    MAX(CASE WHEN cohort_index =  6 THEN n END) AS m6,
    MAX(CASE WHEN cohort_index =  7 THEN n END) AS m7,
    MAX(CASE WHEN cohort_index =  8 THEN n END) AS m8,
    MAX(CASE WHEN cohort_index =  9 THEN n END) AS m9,
    MAX(CASE WHEN cohort_index = 10 THEN n END) AS m10,
    MAX(CASE WHEN cohort_index = 11 THEN n END) AS m11,
    MAX(CASE WHEN cohort_index = 12 THEN n END) AS m12
FROM distinct_per_period
GROUP BY cohort_month
ORDER BY cohort_month
"""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 2b — COHORT RETENTION PCT
#
# Same pivot but values = retention_rate (%) = customers_at_period / m0 × 100
# Period-0 is always 100.00.  Periods beyond the observation window are NULL.
# ─────────────────────────────────────────────────────────────────────────────
PROMPT2_COHORT_RETENTION_PCT_SQL = """
WITH

cohort_base AS (
    SELECT CustomerID AS customer_id, MIN(InvoiceMonth) AS cohort_month
    FROM transactions
    GROUP BY CustomerID
),

activity AS (
    SELECT
        t.CustomerID AS customer_id,
        cb.cohort_month,
        (
              CAST(substr(t.InvoiceMonth, 1, 4) AS INTEGER) * 12
            + CAST(substr(t.InvoiceMonth, 6, 2) AS INTEGER)
        ) - (
              CAST(substr(cb.cohort_month, 1, 4) AS INTEGER) * 12
            + CAST(substr(cb.cohort_month, 6, 2) AS INTEGER)
        ) AS cohort_index
    FROM transactions t
    JOIN cohort_base  cb ON t.CustomerID = cb.customer_id
),

distinct_per_period AS (
    SELECT
        cohort_month,
        cohort_index,
        COUNT(DISTINCT customer_id) AS n
    FROM activity
    WHERE cohort_index BETWEEN 0 AND 12
    GROUP BY cohort_month, cohort_index
),

-- Pull m0 size separately so we can divide in the pivot
cohort_m0 AS (
    SELECT cohort_month, n AS m0_size
    FROM distinct_per_period
    WHERE cohort_index = 0
)

SELECT
    dp.cohort_month,
    cm.m0_size                                                                         AS cohort_size,
    ROUND(MAX(CASE WHEN cohort_index =  0 THEN n END) * 100.0 / cm.m0_size, 1)       AS m0_pct,
    ROUND(MAX(CASE WHEN cohort_index =  1 THEN n END) * 100.0 / cm.m0_size, 1)       AS m1_pct,
    ROUND(MAX(CASE WHEN cohort_index =  2 THEN n END) * 100.0 / cm.m0_size, 1)       AS m2_pct,
    ROUND(MAX(CASE WHEN cohort_index =  3 THEN n END) * 100.0 / cm.m0_size, 1)       AS m3_pct,
    ROUND(MAX(CASE WHEN cohort_index =  4 THEN n END) * 100.0 / cm.m0_size, 1)       AS m4_pct,
    ROUND(MAX(CASE WHEN cohort_index =  5 THEN n END) * 100.0 / cm.m0_size, 1)       AS m5_pct,
    ROUND(MAX(CASE WHEN cohort_index =  6 THEN n END) * 100.0 / cm.m0_size, 1)       AS m6_pct,
    ROUND(MAX(CASE WHEN cohort_index =  7 THEN n END) * 100.0 / cm.m0_size, 1)       AS m7_pct,
    ROUND(MAX(CASE WHEN cohort_index =  8 THEN n END) * 100.0 / cm.m0_size, 1)       AS m8_pct,
    ROUND(MAX(CASE WHEN cohort_index =  9 THEN n END) * 100.0 / cm.m0_size, 1)       AS m9_pct,
    ROUND(MAX(CASE WHEN cohort_index = 10 THEN n END) * 100.0 / cm.m0_size, 1)       AS m10_pct,
    ROUND(MAX(CASE WHEN cohort_index = 11 THEN n END) * 100.0 / cm.m0_size, 1)       AS m11_pct,
    ROUND(MAX(CASE WHEN cohort_index = 12 THEN n END) * 100.0 / cm.m0_size, 1)       AS m12_pct
FROM distinct_per_period dp
JOIN cohort_m0            cm USING (cohort_month)
GROUP BY dp.cohort_month, cm.m0_size
ORDER BY dp.cohort_month
"""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 3a — REVENUE PER COHORT: avg revenue / customer / period + LTV build-up
#
# Window function: SUM() OVER (PARTITION BY cohort_month ORDER BY cohort_index
#                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
# = running total of revenue per cohort → LTV at any given period.
#
# SQLite supports window functions since v3.25.0 (2018-09-15).
# ─────────────────────────────────────────────────────────────────────────────
PROMPT3_REVENUE_PER_COHORT_SQL = """
WITH

cohort_base AS (
    SELECT CustomerID AS customer_id, MIN(InvoiceMonth) AS cohort_month
    FROM transactions
    GROUP BY CustomerID
),

activity AS (
    SELECT
        t.CustomerID AS customer_id,
        cb.cohort_month,
        t.Revenue    AS revenue,
        (
              CAST(substr(t.InvoiceMonth, 1, 4) AS INTEGER) * 12
            + CAST(substr(t.InvoiceMonth, 6, 2) AS INTEGER)
        ) - (
              CAST(substr(cb.cohort_month, 1, 4) AS INTEGER) * 12
            + CAST(substr(cb.cohort_month, 6, 2) AS INTEGER)
        ) AS cohort_index
    FROM transactions t
    JOIN cohort_base  cb ON t.CustomerID = cb.customer_id
),

-- Cohort headcount at period 0 (denominator for per-customer metrics)
cohort_sizes AS (
    SELECT
        cohort_month,
        COUNT(DISTINCT customer_id) AS cohort_size
    FROM activity
    WHERE cohort_index = 0
    GROUP BY cohort_month
),

-- Revenue rolled up to (cohort, period) level
period_revenue AS (
    SELECT
        a.cohort_month,
        a.cohort_index,
        cs.cohort_size,
        ROUND(SUM(a.revenue), 2)                               AS period_revenue,
        -- avg revenue per acquisition customer (not just active buyers)
        ROUND(SUM(a.revenue) / cs.cohort_size, 2)             AS avg_rev_per_cohort_customer,
        -- avg revenue per ACTIVE buyer in this period
        ROUND(SUM(a.revenue) / COUNT(DISTINCT a.customer_id), 2)  AS arpu_active
    FROM activity      a
    JOIN cohort_sizes  cs USING (cohort_month)
    WHERE a.cohort_index BETWEEN 0 AND 12
    GROUP BY a.cohort_month, a.cohort_index, cs.cohort_size
)

SELECT
    cohort_month,
    cohort_index,
    cohort_size,
    period_revenue,
    avg_rev_per_cohort_customer,
    arpu_active,

    -- Running cumulative revenue per cohort (LTV build-up)
    ROUND(
        SUM(period_revenue) OVER (
            PARTITION BY cohort_month
            ORDER BY     cohort_index
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ), 2
    ) AS cumulative_revenue,

    -- LTV per customer at each period (cumulative_revenue / cohort_size)
    ROUND(
        SUM(period_revenue) OVER (
            PARTITION BY cohort_month
            ORDER BY     cohort_index
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) / cohort_size, 2
    ) AS ltv_per_customer

FROM period_revenue
ORDER BY cohort_month, cohort_index
"""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 3b — HIGHEST LTV COHORT AT MONTH 6
#
# Identifies which acquisition cohort produced the most revenue per customer
# within the first 6 months (cohort_index 0–6).
# ─────────────────────────────────────────────────────────────────────────────
PROMPT3_TOP_LTV_M6_SQL = """
WITH

cohort_base AS (
    SELECT CustomerID AS customer_id, MIN(InvoiceMonth) AS cohort_month
    FROM transactions
    GROUP BY CustomerID
),

activity AS (
    SELECT
        t.CustomerID AS customer_id,
        cb.cohort_month,
        t.Revenue    AS revenue,
        (
              CAST(substr(t.InvoiceMonth, 1, 4) AS INTEGER) * 12
            + CAST(substr(t.InvoiceMonth, 6, 2) AS INTEGER)
        ) - (
              CAST(substr(cb.cohort_month, 1, 4) AS INTEGER) * 12
            + CAST(substr(cb.cohort_month, 6, 2) AS INTEGER)
        ) AS cohort_index
    FROM transactions t
    JOIN cohort_base  cb ON t.CustomerID = cb.customer_id
),

cohort_sizes AS (
    SELECT cohort_month, COUNT(DISTINCT customer_id) AS cohort_size
    FROM activity WHERE cohort_index = 0 GROUP BY cohort_month
),

-- Sum revenue through month-6 window only
ltv_at_m6 AS (
    SELECT
        a.cohort_month,
        cs.cohort_size,
        ROUND(SUM(a.revenue), 2)                     AS revenue_through_m6,
        ROUND(SUM(a.revenue) / cs.cohort_size, 2)   AS ltv_per_customer_m6
    FROM activity      a
    JOIN cohort_sizes  cs USING (cohort_month)
    WHERE a.cohort_index BETWEEN 0 AND 6
    GROUP BY a.cohort_month, cs.cohort_size
)

SELECT
    cohort_month,
    cohort_size,
    revenue_through_m6,
    ltv_per_customer_m6,
    RANK() OVER (ORDER BY ltv_per_customer_m6 DESC) AS ltv_rank
FROM ltv_at_m6
ORDER BY ltv_per_customer_m6 DESC
"""


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def _run(con: sqlite3.Connection, label: str, sql: str, head: int = 10) -> pd.DataFrame:
    print(f"\n{'-' * 64}")
    print(label)
    print('-' * 64)
    df = pd.read_sql_query(textwrap.dedent(sql), con)
    print(df.head(head).to_string(index=False))
    print(f"  … {len(df):,} rows total")
    return df


def run_all() -> dict[str, pd.DataFrame]:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"retail.db not found at {DB_PATH}\n"
            "Run:  python ingest_data.py"
        )

    con = sqlite3.connect(DB_PATH)
    results = {}

    results["cohort_assignment"]  = _run(
        con,
        "PROMPT 1 — Cohort Assignment (sample: first 10 rows)",
        PROMPT1_COHORT_ASSIGNMENT_SQL,
        head=10,
    )

    results["cohort_counts"]      = _run(
        con,
        "PROMPT 2a — Cohort Counts  (distinct customers at each period, wide pivot)",
        PROMPT2_COHORT_COUNTS_SQL,
        head=25,
    )

    results["cohort_retention_pct"] = _run(
        con,
        "PROMPT 2b — Cohort Retention %  (retention_rate = n / m0 × 100)",
        PROMPT2_COHORT_RETENTION_PCT_SQL,
        head=25,
    )

    results["revenue_per_cohort"] = _run(
        con,
        "PROMPT 3a — Revenue per Cohort  (avg rev / customer / period + LTV build-up)",
        PROMPT3_REVENUE_PER_COHORT_SQL,
        head=15,
    )

    results["top_ltv_m6"]         = _run(
        con,
        "PROMPT 3b — Highest LTV Cohort at Month 6  (all cohorts ranked)",
        PROMPT3_TOP_LTV_M6_SQL,
        head=25,
    )

    con.close()

    print(f"\n{'=' * 64}")
    print("All 5 queries executed successfully.")
    print("=" * 64)
    return results


if __name__ == "__main__":
    run_all()
