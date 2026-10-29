"""Small, deterministic checks for the cohort SQL's observation semantics."""

import unittest

import duckdb

from cohort_queries import COHORT_RETENTION_SQL, COHORT_SUMMARY_SQL


class CohortQueryTests(unittest.TestCase):
    def test_zero_months_and_future_months(self):
        con = duckdb.connect()
        try:
            con.execute(
                "CREATE TABLE orders (order_id INTEGER, customer_id INTEGER, "
                "order_date DATE, revenue DOUBLE)"
            )
            con.execute(
                "INSERT INTO orders VALUES "
                "(1, 10, '2020-01-05', 10), "
                "(2, 10, '2020-03-05', 20), "
                "(3, 20, '2020-02-05', 30)"
            )
            con.execute("CREATE TABLE analysis_window (last_complete_month DATE)")
            con.execute("INSERT INTO analysis_window VALUES ('2020-04-01')")
            con.execute(f"CREATE TABLE retention_matrix AS ({COHORT_RETENTION_SQL})")
            rows = con.execute(
                "SELECT period_number, active_users, retention_rate, "
                "period_revenue, cumulative_revenue "
                "FROM retention_matrix WHERE cohort_month = '2020-01-01' "
                "ORDER BY period_number"
            ).fetchall()
            self.assertEqual([row[0] for row in rows], [0, 1, 2, 3])
            self.assertEqual([row[1] for row in rows], [1, 0, 1, 0])
            self.assertEqual([row[2] for row in rows], [100, 0, 100, 0])
            self.assertEqual([row[3] for row in rows], [10, 0, 20, 0])
            self.assertEqual([row[4] for row in rows], [10, 10, 30, 30])

            summary = con.execute(COHORT_SUMMARY_SQL).df()
            self.assertTrue(summary["m6_revenue_per_customer"].isna().all())
            self.assertEqual(
                con.execute("SELECT MAX(cohort_month + period_number * "
                            "INTERVAL '1 month') FROM retention_matrix").fetchone()[0].date().isoformat(),
                "2020-04-01",
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
