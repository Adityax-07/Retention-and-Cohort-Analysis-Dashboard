"""
Part 4 - Python Visualization Prompts
Three Plotly charts from the UCI Online Retail II cohort data.

Run:
    python part4_visualizations.py          # saves HTML + opens browser tabs
    python part4_visualizations.py --save   # saves HTML only, no browser

Output: data/charts/cohort_heatmap.html
        data/charts/retention_curves.html
        data/charts/business_insight.html
"""

import os
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from part3_queries import (
    DB_PATH,
    PROMPT2_COHORT_RETENTION_PCT_SQL,
    PROMPT3_REVENUE_PER_COHORT_SQL,
)
import sqlite3

CHARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)


# -----------------------------------------------------------------------------
# Data loader
# -----------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(DB_PATH)
    retention_wide = pd.read_sql_query(PROMPT2_COHORT_RETENTION_PCT_SQL, con)
    revenue_df     = pd.read_sql_query(PROMPT3_REVENUE_PER_COHORT_SQL, con)
    con.close()
    return retention_wide, revenue_df


# -----------------------------------------------------------------------------
# PROMPT 1 — Cohort Heatmap
#
# go.Heatmap on a 25x13 matrix (cohort_month x M0-M12).
# colorscale="Reds": light = low retention, dark red = high retention.
# Every non-null cell is annotated with the percentage.
# -----------------------------------------------------------------------------

def plot_cohort_heatmap(retention_wide: pd.DataFrame) -> go.Figure:
    period_cols = [f"m{i}_pct" for i in range(13)]
    x_labels    = [f"M{i}" for i in range(13)]
    y_labels    = retention_wide["cohort_month"].tolist()

    # 2-D matrix for go.Heatmap; keep NaN as NaN (Plotly renders gaps)
    z = retention_wide[period_cols].values

    # Build per-cell text annotations
    annotations = []
    for row_i, cohort in enumerate(y_labels):
        for col_j, period in enumerate(x_labels):
            val = z[row_i, col_j]
            if pd.notna(val):
                # White text on dark cells, dark text on pale cells
                font_color = "white" if val >= 55 else "#222222"
                annotations.append(dict(
                    text=f"{val:.1f}",
                    x=period,
                    y=cohort,
                    xref="x",
                    yref="y",
                    showarrow=False,
                    font=dict(size=8, color=font_color, family="monospace"),
                ))

    fig = go.Figure(go.Heatmap(
        z=z,
        x=x_labels,
        y=y_labels,
        colorscale="Reds",
        zmin=0,
        zmax=100,
        colorbar=dict(
            title=dict(text="Retention %", side="right"),
            ticksuffix="%",
            len=0.85,
        ),
        hoverongaps=False,
        hovertemplate=(
            "Cohort: %{y}<br>"
            "Period: %{x}<br>"
            "Retention: %{z:.1f}%"
            "<extra></extra>"
        ),
    ))

    fig.update_layout(
        title=dict(
            text="Monthly Cohort Retention — Online Retail",
            font=dict(size=20, color="#1a1a2e"),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="Months Since First Purchase",
            side="bottom",
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            title="Cohort (Acquisition Month)",
            autorange="reversed",
            tickfont=dict(size=10),
        ),
        annotations=annotations,
        height=700,
        width=1050,
        plot_bgcolor="#f8f9fa",
        paper_bgcolor="white",
        margin=dict(l=110, r=110, t=90, b=70),
    )

    return fig


# -----------------------------------------------------------------------------
# PROMPT 2 — Retention Curves
#
# One scatter line per cohort. Best/worst cohort highlighted; all others muted.
# Horizontal dashed benchmark line at 20%.
# -----------------------------------------------------------------------------

def plot_retention_curves(retention_wide: pd.DataFrame) -> go.Figure:
    period_cols = [f"m{i}_pct" for i in range(13)]

    # Wide -> long
    long_df = retention_wide.melt(
        id_vars=["cohort_month", "cohort_size"],
        value_vars=period_cols,
        var_name="period_col",
        value_name="retention_pct",
    )
    long_df["cohort_index"] = (
        long_df["period_col"].str.extract(r"m(\d+)_pct").astype(int)
    )

    # Best/worst: average M1-M12 retention (exclude M0 which is always 100)
    avg_ret = (
        long_df[long_df["cohort_index"] >= 1]
        .groupby("cohort_month")["retention_pct"]
        .mean()
        .dropna()
    )
    best_cohort  = avg_ret.idxmax()
    worst_cohort = avg_ret.idxmin()

    fig = go.Figure()

    # Background cohorts — drawn first so highlights sit on top
    for cohort in retention_wide["cohort_month"]:
        if cohort in (best_cohort, worst_cohort):
            continue
        row = long_df[long_df["cohort_month"] == cohort].sort_values("cohort_index")
        fig.add_trace(go.Scatter(
            x=row["cohort_index"],
            y=row["retention_pct"],
            mode="lines",
            line=dict(color="rgba(140, 140, 170, 0.30)", width=1.2),
            name=cohort,
            showlegend=False,
            hovertemplate=(
                f"Cohort {cohort}<br>"
                "M%{x}: %{y:.1f}%"
                "<extra></extra>"
            ),
        ))

    # Best cohort — bright green, markers
    best_row = long_df[long_df["cohort_month"] == best_cohort].sort_values("cohort_index")
    fig.add_trace(go.Scatter(
        x=best_row["cohort_index"],
        y=best_row["retention_pct"],
        mode="lines+markers",
        line=dict(color="#2ca02c", width=2.8),
        marker=dict(size=7, symbol="circle"),
        name=f"Best: {best_cohort} (avg {avg_ret[best_cohort]:.1f}%)",
        hovertemplate=(
            f"Best cohort {best_cohort}<br>"
            "M%{x}: %{y:.1f}%"
            "<extra></extra>"
        ),
    ))

    # Worst cohort — red, markers
    worst_row = long_df[long_df["cohort_month"] == worst_cohort].sort_values("cohort_index")
    fig.add_trace(go.Scatter(
        x=worst_row["cohort_index"],
        y=worst_row["retention_pct"],
        mode="lines+markers",
        line=dict(color="#d62728", width=2.8),
        marker=dict(size=7, symbol="circle"),
        name=f"Worst: {worst_cohort} (avg {avg_ret[worst_cohort]:.1f}%)",
        hovertemplate=(
            f"Worst cohort {worst_cohort}<br>"
            "M%{x}: %{y:.1f}%"
            "<extra></extra>"
        ),
    ))

    # 20% industry benchmark
    fig.add_hline(
        y=20,
        line_dash="dash",
        line_color="#ff7f0e",
        line_width=1.8,
        annotation_text="  e-commerce benchmark (20%)",
        annotation_position="bottom right",
        annotation_font=dict(size=11, color="#ff7f0e"),
    )

    fig.update_layout(
        title=dict(
            text="Cohort Retention Curves — Online Retail II (UCI)",
            font=dict(size=20, color="#1a1a2e"),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="Months Since First Purchase",
            tickmode="linear",
            tick0=0,
            dtick=1,
            range=[-0.3, 12.5],
        ),
        yaxis=dict(
            title="Retention Rate (%)",
            ticksuffix="%",
            range=[0, 115],
            gridcolor="#e8e8e8",
        ),
        legend=dict(
            title=dict(text="Cohort"),
            orientation="v",
            x=1.02,
            y=1.0,
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#cccccc",
            borderwidth=1,
        ),
        height=560,
        width=1050,
        plot_bgcolor="#f8f9fa",
        paper_bgcolor="white",
        margin=dict(l=80, r=200, t=90, b=70),
    )

    return fig


# -----------------------------------------------------------------------------
# PROMPT 3 — Business Insight Chart
#
# Grouped bar chart: avg revenue per cohort customer at M0, M1, M3, M6
# for the top-5 cohorts by total customer count.
# Annotation arrow points to the highest-revenue cohort (at M0).
# Title deliberately frames the business insight, not the data mechanics.
# -----------------------------------------------------------------------------

def plot_business_insight(revenue_df: pd.DataFrame) -> go.Figure:
    TARGET_PERIODS = [0, 1, 3, 6]
    PERIOD_LABELS  = {0: "M0 — Acquisition", 1: "M1", 3: "M3", 6: "M6"}
    BAR_COLORS     = ["#4c72b0", "#55a868", "#c44e52", "#8172b2"]

    # Top 5 cohorts by cohort_size
    top5 = (
        revenue_df[revenue_df["cohort_index"] == 0]
        .nlargest(5, "cohort_size")
        ["cohort_month"]
        .tolist()
    )
    top5_sorted = sorted(top5)    # chronological order on x-axis

    df = revenue_df[
        (revenue_df["cohort_month"].isin(top5)) &
        (revenue_df["cohort_index"].isin(TARGET_PERIODS))
    ].copy()

    fig = go.Figure()

    for idx, period in enumerate(TARGET_PERIODS):
        period_df = (
            df[df["cohort_index"] == period]
            .set_index("cohort_month")
            .reindex(top5_sorted)
            .reset_index()
        )
        fig.add_trace(go.Bar(
            name=PERIOD_LABELS[period],
            x=period_df["cohort_month"],
            y=period_df["avg_rev_per_cohort_customer"],
            marker_color=BAR_COLORS[idx],
            text=[
                f"£{v:,.0f}" if pd.notna(v) else ""
                for v in period_df["avg_rev_per_cohort_customer"]
            ],
            textposition="outside",
            textfont=dict(size=8),
            hovertemplate=(
                "Cohort: %{x}<br>"
                f"Period: {PERIOD_LABELS[period]}<br>"
                "Avg Rev/Customer: £%{y:,.2f}"
                "<extra></extra>"
            ),
        ))

    # Find the top-5 cohort with the highest M0 revenue for the annotation
    m0_df      = df[df["cohort_index"] == 0]
    best_idx   = m0_df["avg_rev_per_cohort_customer"].idxmax()
    top_cohort = m0_df.loc[best_idx, "cohort_month"]
    top_val    = m0_df.loc[best_idx, "avg_rev_per_cohort_customer"]

    # Annotation: arrowhead at the bar top, text sits above
    fig.add_annotation(
        x=top_cohort,
        y=top_val,                          # arrow tip = bar top (data coords)
        text=f"<b>Highest M0 revenue</b><br>£{top_val:,.0f} / customer",
        showarrow=True,
        arrowhead=2,
        arrowsize=1.3,
        arrowwidth=2,
        arrowcolor="#d62728",
        ax=80,                              # shift annotation text right
        ay=-70,                             # shift annotation text upward
        font=dict(size=11, color="#d62728"),
        bgcolor="rgba(255,255,255,0.88)",
        bordercolor="#d62728",
        borderwidth=1.5,
        borderpad=5,
    )

    fig.update_layout(
        title=dict(
            text="Early Revenue Predicts Long-term LTV",
            font=dict(size=20, color="#1a1a2e"),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="Cohort (Acquisition Month)",
            categoryorder="array",
            categoryarray=top5_sorted,
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="Avg Revenue per Cohort Customer (GBP)",
            tickprefix="£",
            gridcolor="#e8e8e8",
        ),
        barmode="group",
        bargap=0.20,
        bargroupgap=0.05,
        legend=dict(
            title=dict(text="Period"),
            orientation="h",
            x=0.5,
            xanchor="center",
            y=1.10,
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#cccccc",
            borderwidth=1,
        ),
        height=600,
        width=1050,
        plot_bgcolor="#f8f9fa",
        paper_bgcolor="white",
        margin=dict(l=90, r=60, t=110, b=80),
    )

    return fig


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

def run_all(open_browser: bool = True) -> None:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"retail.db not found at {DB_PATH}\n"
            "Run:  python ingest_data.py"
        )

    print("Loading data from retail.db ...")
    retention_wide, revenue_df = load_data()
    print(f"  Retention matrix : {retention_wide.shape[0]} cohorts")
    print(f"  Revenue rows     : {len(revenue_df):,}")

    charts = [
        ("cohort_heatmap",   plot_cohort_heatmap(retention_wide),  "Prompt 1 - Cohort Heatmap"),
        ("retention_curves", plot_retention_curves(retention_wide), "Prompt 2 - Retention Curves"),
        ("business_insight", plot_business_insight(revenue_df),    "Prompt 3 - Business Insight"),
    ]

    for name, fig, label in charts:
        out = os.path.join(CHARTS_DIR, f"{name}.html")
        fig.write_html(out, include_plotlyjs="cdn")
        print(f"  Saved  [{label}]  ->  {out}")
        if open_browser:
            fig.show()

    print(f"\nAll 3 charts written to  {CHARTS_DIR}")


if __name__ == "__main__":
    open_browser = "--save" not in sys.argv
    run_all(open_browser=open_browser)
