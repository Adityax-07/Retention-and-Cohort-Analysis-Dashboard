"""
Retention & Cohort Analysis Dashboard — Online Retail II (UCI)
Three-tab Streamlit app with country filtering and complete-month cohorts

Run once:  python ingest_data.py
Launch:    streamlit run app.py
"""

import os
import sqlite3
import sys

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cohort_queries import (
    AVERAGE_RETENTION_SQL,
    COHORT_RETENTION_SQL,
    COHORT_SUMMARY_SQL,
)

# ── Constants ──────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "retail.db")

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cohort Retention Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark theme + blue accent CSS ───────────────────────────────────────────────
st.markdown("""
<style>
  /* Main background */
  .stApp { background-color: #0d1117; color: #e6edf3; }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background-color: #161b22;
    border-right: 1px solid #30363d;
  }

  /* Metric cards */
  [data-testid="metric-container"] {
    background-color: #1c2333;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 16px 20px;
  }
  [data-testid="stMetricLabel"]  { color: #8b949e !important; font-size: 13px; }
  [data-testid="stMetricValue"]  { color: #4285f4 !important; font-size: 22px; font-weight: 700; }

  /* Active tab — blue underline */
  .stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid #30363d; gap: 4px; }
  .stTabs [data-baseweb="tab-list"] button            { color: #8b949e; font-weight: 500; }
  .stTabs [data-baseweb="tab-list"] button:hover      { color: #e6edf3; }
  .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
    color: #4285f4;
    border-bottom: 2px solid #4285f4;
  }

  /* Dividers */
  hr { border-color: #30363d !important; }

  /* Headings */
  h1, h2, h3 { color: #e6edf3; }
  h1 { color: #4285f4; }

  /* Code blocks */
  .stCodeBlock code { background-color: #161b22 !important; }

  /* Dataframe */
  [data-testid="stDataFrame"] { background-color: #161b22; }
</style>
""", unsafe_allow_html=True)

# ── Auto-ingest on first run (Hugging Face Spaces / fresh clone) ───────────────
if not os.path.exists(DB_PATH):
    import subprocess
    with st.spinner("First run — downloading & processing UCI dataset (~2–3 min)..."):
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest_data.py")],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    if result.returncode != 0:
        st.error(f"Data ingestion failed:\n\n```\n{result.stderr[-2000:]}\n```")
        st.stop()
    st.rerun()


# ── Cached data loaders ────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def get_countries(db_path: str) -> list[str]:
    con = sqlite3.connect(db_path)
    df  = pd.read_sql_query(
        "SELECT DISTINCT Country FROM transactions WHERE Country IS NOT NULL ORDER BY Country",
        con,
    )
    con.close()
    return df["Country"].tolist()


@st.cache_data(show_spinner=False)
def get_db_stats(db_path: str, country: str) -> dict:
    con   = sqlite3.connect(db_path)
    where = "" if country == "All Countries" else "WHERE Country = ?"
    params = () if country == "All Countries" else (country,)
    row   = con.execute(f"""
        SELECT
            COUNT(*)                        AS n_rows,
            COUNT(DISTINCT CustomerID)      AS n_customers,
            COUNT(DISTINCT InvoiceNo)       AS n_invoices,
            ROUND(SUM(Revenue),    2)       AS total_revenue,
            MIN(SUBSTR(InvoiceDate, 1, 7))  AS min_month,
            MAX(SUBSTR(InvoiceDate, 1, 7))  AS max_month
        FROM transactions {where}
    """, params).fetchone()
    con.close()
    return dict(zip(["n_rows", "n_customers", "n_invoices", "total_revenue", "min_month", "max_month"], row))


@st.cache_data(show_spinner=False)
def get_analysis_cutoff(db_path: str) -> str:
    """First day of the last complete month in the source dataset."""
    with sqlite3.connect(db_path) as con:
        last_date = pd.Timestamp(con.execute(
            "SELECT MAX(InvoiceDate) FROM transactions"
        ).fetchone()[0])
    last_month = last_date.to_period("M")
    if last_date.normalize() != last_month.end_time.normalize():
        last_month -= 1
    return str(last_month.start_time.date())


@st.cache_data(show_spinner=False)
def run_cohort_analysis(
    db_path: str, country: str, cutoff: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Analyze purchases in the selected country through the last full month."""
    con_sq = sqlite3.connect(db_path)
    if country == "All Countries":
        orders_df = pd.read_sql_query(
            "SELECT * FROM orders WHERE order_date < DATE(?, '+1 month')",
            con_sq, params=[cutoff],
        )
    else:
        orders_df = pd.read_sql_query(
            """
            SELECT InvoiceNo AS order_id, CustomerID AS customer_id,
                   DATE(InvoiceDate) AS order_date, SUM(Revenue) AS revenue
            FROM transactions
            WHERE Country = ? AND InvoiceDate < DATE(?, '+1 month')
            GROUP BY InvoiceNo, CustomerID, DATE(InvoiceDate)
            """,
            con_sq, params=[country, cutoff],
        )
    con_sq.close()

    if orders_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    con = duckdb.connect()
    con.register("orders_raw", orders_df)
    con.execute("CREATE TABLE analysis_window (last_complete_month DATE)")
    con.execute("INSERT INTO analysis_window VALUES (?)", [cutoff])
    con.execute("""
        CREATE TABLE orders AS
        SELECT order_id, customer_id,
               CAST(order_date AS DATE)   AS order_date,
               CAST(revenue    AS DOUBLE) AS revenue
        FROM orders_raw
    """)
    con.execute(f"CREATE TABLE retention_matrix AS ({COHORT_RETENTION_SQL})")

    retention_df = con.execute(
        "SELECT * FROM retention_matrix ORDER BY cohort_month, period_number"
    ).df()
    avg_df     = con.execute(AVERAGE_RETENTION_SQL).df()
    summary_df = con.execute(COHORT_SUMMARY_SQL).df()
    con.close()

    # Normalise date columns to YYYY-MM strings for display + lookup
    for frame in (retention_df, summary_df):
        frame["cohort_month"] = (
            pd.to_datetime(frame["cohort_month"]).dt.strftime("%Y-%m")
        )
    retention_df["period_number"] = retention_df["period_number"].astype(int)

    return retention_df, avg_df, summary_df


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Filters")

    countries   = ["All Countries"] + get_countries(DB_PATH)
    default_idx = countries.index("United Kingdom") if "United Kingdom" in countries else 0
    country     = st.selectbox("Country", options=countries, index=default_idx)

    st.divider()
    st.markdown("### Dataset")

    stats = get_db_stats(DB_PATH, country)
    st.metric("Cleaned line items",  f"{stats['n_rows']:,}")
    st.metric("Customers",     f"{stats['n_customers']:,}")
    st.metric("Invoices",      f"{stats['n_invoices']:,}")
    st.metric("Revenue",       f"£{stats['total_revenue']:,.0f}")
    st.caption(f"Source period: {stats['min_month']} to {stats['max_month']}")

    st.divider()
    st.caption("UCI Online Retail II  ·  DuckDB + Streamlit")


# ── Load cohort data ───────────────────────────────────────────────────────────
analysis_cutoff = get_analysis_cutoff(DB_PATH)
with st.spinner(f"Running cohort analysis for {country} ..."):
    retention_df, avg_df, summary_df = run_cohort_analysis(DB_PATH, country, analysis_cutoff)

if retention_df.empty:
    st.warning(f"No cohort data for **{country}**. Choose a different country.")
    st.stop()

cohort_months = sorted(retention_df["cohort_month"].unique().tolist())
n_cohorts     = len(cohort_months)


# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("# Retention & Cohort Analysis Dashboard")
st.caption(
    f"Online Retail II (UCI)  ·  {country}  ·  "
    f"{n_cohorts} cohorts  ·  "
    f"Complete months through {analysis_cutoff[:7]}  ·  "
    f"{stats['n_customers']:,} customers"
)
st.divider()


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "  📊  Cohort Heatmap  ",
    "  📈  Retention Curves  ",
    "  💡  Business Insights  ",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — COHORT HEATMAP
# Slider controls max cohort_index displayed (0 – 12).
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.markdown("### Monthly Cohort Retention Heatmap")
    st.caption(
        "Each cell = % of the acquisition cohort still purchasing in that month.  "
        "Color: dark red = high retention, pale = low."
    )

    max_period = st.slider(
        "Show periods up to  M__",
        min_value=1, max_value=12, value=12, step=1,
        help="Drag left to focus on early-period retention behaviour.",
    )

    # Build pivot
    pivot    = (
        retention_df[retention_df["period_number"] <= max_period]
        .pivot_table(
            index="cohort_month",
            columns="period_number",
            values="retention_rate",
            aggfunc="first",
        )
    )
    z        = pivot.values
    x_labels = [f"M{int(c)}" for c in pivot.columns]
    y_labels = pivot.index.tolist()

    # Per-cell annotations
    annotations = []
    for ri in range(len(y_labels)):
        for ci in range(len(x_labels)):
            val = z[ri, ci]
            if not pd.isna(val):
                annotations.append(dict(
                    text=f"{val:.1f}",
                    x=x_labels[ci], y=y_labels[ri],
                    xref="x", yref="y",
                    showarrow=False,
                    font=dict(size=8, color="white" if val >= 55 else "#cccccc", family="monospace"),
                ))

    fig_heat = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=y_labels,
        colorscale="Reds",
        zmin=0, zmax=100,
        colorbar=dict(title=dict(text="Retention %", side="right"), ticksuffix="%", len=0.85),
        hoverongaps=False,
        hovertemplate="Cohort: %{y}<br>Period: %{x}<br>Retention: %{z:.1f}%<extra></extra>",
    ))
    fig_heat.update_layout(
        title=dict(text="Monthly Cohort Retention — Online Retail", font=dict(size=17, color="#e6edf3"), x=0.5, xanchor="center"),
        xaxis=dict(title="Months Since First Purchase", tickfont=dict(color="#8b949e", size=10)),
        yaxis=dict(title="Cohort (Acquisition Month)", autorange="reversed", tickfont=dict(color="#8b949e", size=10)),
        annotations=annotations,
        height=660,
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#e6edf3"),
        margin=dict(l=110, r=110, t=70, b=60),
    )
    st.plotly_chart(fig_heat, width="stretch")

    with st.expander("Raw data table"):
        raw_pivot = pivot.copy().round(1)
        raw_pivot.columns = [f"M{int(c)}" for c in raw_pivot.columns]
        st.dataframe(
            raw_pivot.style.background_gradient(cmap="Reds", axis=None).format("{:.1f}", na_rep="—"),
            width="stretch",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — RETENTION CURVES
# Multiselect controls which cohort months are drawn.
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("### Retention Curves by Cohort")
    st.caption(
        "Compare acquisition cohorts side-by-side. "
        "The dashed line shows the average of cohorts observed at each month."
    )

    default_selection = cohort_months[:10] if n_cohorts >= 10 else cohort_months
    selected = st.multiselect(
        "Select cohort months to compare",
        options=cohort_months,
        default=default_selection,
        placeholder="Type a year-month, e.g. 2010-03 ...",
    )

    if not selected:
        st.info("Select at least one cohort month above.")
    else:
        # Compare cohorts at the same observed age (M3).
        avg_m1plus = (
            retention_df[retention_df["period_number"] == 3]
            .set_index("cohort_month")["retention_rate"]
            .dropna()
        )
        best_cohort  = avg_m1plus.idxmax() if not avg_m1plus.empty else None
        worst_cohort = avg_m1plus.idxmin() if not avg_m1plus.empty else None

        PALETTE = [
            "#4285f4","#ea4335","#fbbc04","#34a853","#ff6d00",
            "#46bdc6","#ff4081","#7c4dff","#00bcd4","#8bc34a",
            "#f06292","#aed581","#4dd0e1","#ffb74d","#ce93d8",
        ]

        fig_curves = go.Figure()
        for idx, cohort in enumerate(sorted(selected)):
            cdf    = retention_df[retention_df["cohort_month"] == cohort].sort_values("period_number")
            color  = PALETTE[idx % len(PALETTE)]
            label  = cohort
            if cohort == best_cohort:
                label += " (best)"
            elif cohort == worst_cohort:
                label += " (worst)"
            width = 3.0 if cohort in (best_cohort, worst_cohort) else 1.8

            fig_curves.add_trace(go.Scatter(
                x=cdf["period_number"],
                y=cdf["retention_rate"],
                mode="lines+markers",
                line=dict(color=color, width=width),
                marker=dict(size=5),
                name=label,
                hovertemplate=f"Cohort {cohort}<br>M%{{x}}: %{{y:.1f}}%<extra></extra>",
            ))

        fig_curves.add_trace(go.Scatter(
            x=avg_df["period_number"], y=avg_df["avg_retention_rate"],
            mode="lines", name="Observed cohort average",
            line=dict(color="#f0883e", width=2, dash="dash"),
            hovertemplate="M%{x}: %{y:.1f}%<extra></extra>",
        ))

        fig_curves.update_layout(
            title=dict(text="Cohort Retention Curves", font=dict(size=17, color="#e6edf3"), x=0.5, xanchor="center"),
            xaxis=dict(title="Months Since First Purchase", tickmode="linear", tick0=0, dtick=1,
                       gridcolor="#21262d", tickfont=dict(color="#8b949e")),
            yaxis=dict(title="Retention Rate (%)", ticksuffix="%", range=[0, 115],
                       gridcolor="#21262d", tickfont=dict(color="#8b949e")),
            legend=dict(
                orientation="v", x=1.02, y=1.0,
                bgcolor="#1c2333", bordercolor="#30363d", borderwidth=1,
                font=dict(size=10),
            ),
            height=530,
            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            font=dict(color="#e6edf3"),
            margin=dict(l=75, r=200, t=70, b=70),
        )
        st.plotly_chart(fig_curves, width="stretch")

        # Quick-reference table for the selected cohorts
        if not summary_df.empty:
            sel_summary = (
                summary_df[summary_df["cohort_month"].isin(selected)]
                [["cohort_month","cohort_size","m1_retention","m3_retention","m6_retention","m6_revenue_per_customer"]]
                .sort_values("cohort_month")
                .rename(columns={
                    "cohort_month":   "Cohort",
                    "cohort_size":    "Size",
                    "m1_retention":   "M1 %",
                    "m3_retention":   "M3 %",
                    "m6_retention":   "M6 %",
                    "m6_revenue_per_customer": "M0–M6 Revenue / Customer (£)",
                })
            )
            st.dataframe(
                sel_summary.set_index("Cohort").round(1).style.format(
                    {"M0–M6 Revenue / Customer (£)": "£{:,.0f}", "M1 %": "{:.1f}", "M3 %": "{:.1f}", "M6 %": "{:.1f}"},
                    na_rep="—",
                ),
                width="stretch",
            )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — BUSINESS INSIGHTS
# Age-matched cohort metrics and testable business recommendations
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### Business Insights")
    st.caption(
        "Cohorts are compared at the same age. M3 retention needs four complete "
        "months of observation; M0–M6 revenue per customer needs seven."
    )

    m3 = summary_df.dropna(subset=["m3_retention"]).copy()
    m6 = summary_df.dropna(subset=["m6_revenue_per_customer"]).copy()
    m1_rows = retention_df[retention_df["period_number"] == 1].copy()

    if len(m3) < 2:
        st.info(
            "There are fewer than two cohorts with an observed M3 in this selection. "
            "Choose a larger country or All Countries for a reliable comparison."
        )
    else:
        best = m3.loc[m3["m3_retention"].idxmax()]
        worst = m3.loc[m3["m3_retention"].idxmin()]
        avg_m3 = m3["m3_retention"].mean()
        c1, c2, c3 = st.columns(3)
        c1.metric("Highest M3 retention", best["cohort_month"],
                  f"{best['m3_retention']:.1f}%")
        c2.metric("Lowest M3 retention", worst["cohort_month"],
                  f"{worst['m3_retention']:.1f}%")
        c3.metric("Mean M3 retention", f"{avg_m3:.1f}%",
                  f"{len(m3)} observed cohorts")

        st.markdown(
            f"**Finding:** {best['cohort_month']} has the highest M3 retention "
            f"({best['m3_retention']:.1f}%) among {len(m3)} eligible cohorts. "
            "This is an association with acquisition month, not evidence of a "
            "particular marketing channel or customer intent."
        )

    if len(m6) >= 2:
        st.markdown("#### Revenue per acquired customer through M6")
        st.caption(
            "Revenue from acquisition month through month 6, divided by the "
            "original cohort size. Only cohorts with a complete M6 are included."
        )
        chart = m6[["cohort_month", "m6_revenue_per_customer"]].set_index(
            "cohort_month"
        )
        st.bar_chart(chart)
        st.dataframe(
            m6[["cohort_month", "cohort_size", "m3_retention",
                "m6_revenue_per_customer"]].rename(columns={
                    "cohort_month": "Cohort",
                    "cohort_size": "Customers",
                    "m3_retention": "M3 retention %",
                    "m6_revenue_per_customer": "M0–M6 revenue / customer (£)",
                }),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("M6 revenue comparison needs at least two mature cohorts.")

    st.divider()
    st.markdown("#### Testable recommendation: first-month win-back")
    if not m1_rows.empty:
        acquired = m1_rows["cohort_size"].sum()
        returned = m1_rows["active_users"].sum()
        m1_rate = 100 * returned / acquired if acquired else 0
        avg_size = m1_rows["cohort_size"].mean()
        m1_arpu = (
            m1_rows["period_revenue"].sum() / returned if returned else 0
        )
        assumed_recovery = 0.05
        lapsed_per_cohort = avg_size * (1 - m1_rate / 100)
        recovered_per_cohort = lapsed_per_cohort * assumed_recovery
        annual_scenario = recovered_per_cohort * m1_arpu * 12
        st.markdown(
            f"Across {len(m1_rows)} cohorts with an observed M1, "
            f"**{m1_rate:.1f}%** of acquired customers purchased again in M1. "
            "A CRM team could test a post-purchase message sequence against a "
            "holdout group and measure incremental M1 purchases and margin."
        )
        st.markdown(
            f"**Illustrative scenario, not a forecast:** If 5% of customers "
            f"who did not buy in M1 were induced to make one additional "
            f"purchase, that is about {recovered_per_cohort:.1f} buyers per "
            f"average cohort × £{m1_arpu:,.0f} observed revenue per active M1 "
            f"buyer × 12 cohorts = **£{annual_scenario:,.0f} annual gross "
            "revenue**. This assumes one new cohort each month, similar "
            "cohort size and spend, and no cannibalization. It excludes "
            "campaign cost and margin."
        )
    else:
        st.info("This selection has no cohort with a complete M1.")

    st.markdown(
        "**Next analysis:** Link customers to acquisition channel, product "
        "mix, and campaign exposure before recommending a budget shift. "
        "Measure conversion, incremental revenue, and gross margin in an "
        "experiment rather than inferring the cause from cohort month."
    )

    st.divider()
    with st.expander("Method and limitations"):
        st.markdown(
            "- Cohort = first purchase month within the selected country. "
            "All Countries uses first purchase across the dataset.\n"
            "- Retention = customers purchasing in a month divided by "
            "customers in the acquisition cohort. Zero-purchase months are 0%.\n"
            f"- The final source month is partial, so the analysis ends "
            f"with {analysis_cutoff[:7]}. Later months are unobserved, not churn.\n"
            "- Small cohorts are noisy. These data contain no acquisition "
            "channel, campaign cost, or experimental assignment.\n"
            "- M0–M6 revenue per customer is a fixed-window measure, "
            "not lifetime value."
        )

    with st.expander("Resume bullets (tailor to the role)"):
        st.code(
            f"Built a Python, SQL, and Streamlit cohort dashboard on "
            f"{stats['n_rows']:,} cleaned retail line items, with country "
            f"filtering and retention through the last complete month.\n"
            f"Used DuckDB CTEs and window functions to compare M3 retention "
            f"across {len(m3)} eligible cohorts and M0–M6 revenue per "
            f"acquired customer across {len(m6)} mature cohorts.\n"
            "Proposed a first-month win-back experiment with transparent "
            "revenue assumptions and a holdout measurement plan.",
            language="text",
        )

    with st.expander("View cohort SQL (DuckDB)"):
        st.code(COHORT_RETENTION_SQL, language="sql")
    with st.expander("View summary and average queries"):
        st.code(COHORT_SUMMARY_SQL, language="sql")
        st.code(AVERAGE_RETENTION_SQL, language="sql")