"""
Synthetic e-commerce order data generator.

Produces ~22k orders for 3,000 customers across 18 months with:
- Growing acquisition (business growth trend + Q4 seasonality spike)
- Realistic retention decay: ~40% M1, ~25% M3, ~15% M6, floor ~8%
- Q4 cohorts retain ~15% better (high-intent holiday buyers)
- Early cohorts (Jan–Mar 2023) retain ~12% worse (product maturity)
- LogNormal revenue distribution ($10–$600 per order)
"""

import os
import pandas as pd
import numpy as np


def generate_orders(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    COHORT_MONTHS = pd.date_range("2023-01", "2024-06", freq="MS")
    N_CUSTOMERS   = 3_000
    CATEGORIES    = ["Electronics", "Clothing", "Home & Garden", "Beauty", "Sports"]
    CAT_PROBS     = [0.20, 0.30, 0.20, 0.15, 0.15]
    REGIONS       = ["North", "South", "East", "West"]

    # ── Acquisition weights: growth trend + Q4 spike ──────────────────────────
    weights = np.array([
        (1.0 + i * 0.06) * (1.9 if m.month in (10, 11, 12) else 1.0)
        for i, m in enumerate(COHORT_MONTHS)
    ])
    weights /= weights.sum()
    cohort_indices = rng.choice(len(COHORT_MONTHS), size=N_CUSTOMERS, p=weights)

    def retention_prob(period: int, cohort_idx: int) -> float:
        """Probability a customer is active in `period` months after acquisition."""
        if period == 0:
            return 1.0
        month = COHORT_MONTHS[cohort_idx].month
        q4_boost      = 1.15 if month in (10, 11, 12) else 1.0
        early_penalty = 0.88 if cohort_idx < 3 else 1.0    # Jan–Mar 2023
        base  = (0.42 * np.exp(-0.32 * period) + 0.07) * q4_boost * early_penalty
        noise = rng.normal(0, 0.025)
        return float(np.clip(base + noise, 0.03, 0.98))

    # ── Generate orders ───────────────────────────────────────────────────────
    rows     = []
    order_id = 1
    obs_end  = pd.Timestamp("2024-07-01")

    for cust_id, cohort_idx in enumerate(cohort_indices, start=1):
        cohort_start = COHORT_MONTHS[cohort_idx]
        max_period   = max(
            0,
            (obs_end.year - cohort_start.year) * 12
            + (obs_end.month - cohort_start.month)
            - 1,
        )

        for period in range(min(max_period + 1, 19)):
            if rng.random() > retention_prob(period, cohort_idx):
                continue

            n_orders    = int(rng.choice([1, 2, 3, 4], p=[0.55, 0.28, 0.12, 0.05]))
            period_start = cohort_start + pd.DateOffset(months=period)
            period_end   = period_start + pd.DateOffset(months=1) - pd.DateOffset(days=1)
            days_in_period = max(1, (period_end - period_start).days)

            for _ in range(n_orders):
                day_offset = int(rng.integers(0, days_in_period))
                order_date = (period_start + pd.DateOffset(days=day_offset)).date()
                revenue    = float(np.clip(rng.lognormal(mean=4.0, sigma=0.75), 8.0, 600.0))

                rows.append({
                    "order_id":         order_id,
                    "customer_id":      cust_id,
                    "order_date":       order_date,
                    "revenue":          round(revenue, 2),
                    "product_category": CATEGORIES[rng.choice(len(CATEGORIES), p=CAT_PROBS)],
                    "region":           REGIONS[int(rng.integers(0, len(REGIONS)))],
                })
                order_id += 1

    df = pd.DataFrame(rows).sort_values("order_date").reset_index(drop=True)
    return df


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    df = generate_orders()
    df.to_csv("data/orders.csv", index=False)
    print(f"Generated {len(df):,} orders | {df['customer_id'].nunique():,} customers")
    print(f"Date range : {df['order_date'].min()} to {df['order_date'].max()}")
    print(f"Avg revenue: ${df['revenue'].mean():.2f} | Total: ${df['revenue'].sum():,.0f}")
