"""
Retention & Cohort Analysis Dashboard — Online Retail II (UCI)
Three-tab Streamlit app with country filtering and complete-month cohorts

Run once:  python ingest_data.py
Launch:    streamlit run app.py
"""

import os
import sqlite3

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cohort_queries import (
    AVERAGE_RETENTION_SQL,
    COHORT_RETENTION_SQL,
    COHORT_SUMMARY_SQL,
)
from snapshot import restore_database

# ── Constants ──────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "retail.db")

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cohort Retention Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dashboard theme ────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp {
    background: radial-gradient(circle at 72% -10%, #173542 0, #0b1220 34%);
    color: #edf4f7;
  }
  .block-container { max-width: 1480px; padding-top: 1.7rem; padding-bottom: 3rem; }
  [data-testid="stSidebar"] {
    background: #101b29;
    border-right: 1px solid #253648;
  }
  [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
  .eyebrow {
    color: #65ded0; font-size: .72rem; font-weight: 750;
    letter-spacing: .19em; text-transform: uppercase; margin-bottom: .65rem;
  }
  .hero {
    padding: 1.65rem 2rem; border: 1px solid #294458; border-radius: 18px;
    background: linear-gradient(110deg, #142b38 0%, #112231 55%, #152b35 100%);
    box-shadow: 0 12px 36px rgba(0,0,0,.14); margin-bottom: 1.15rem;
  }
  .hero h1 {
    color: #f2fafb; font-size: clamp(1.75rem, 3vw, 2.55rem);
    line-height: 1.12; letter-spacing: -.035em; margin: 0 0 .45rem;
  }
  .hero p { color: #abc0ca; margin: 0; font-size: .96rem; }
  .section-kicker {
    color: #65ded0; font-size: .72rem; font-weight: 750;
    letter-spacing: .16em; text-transform: uppercase; margin-bottom: .1rem;
  }
  .muted-note { color: #91a7b6; font-size: .87rem; line-height: 1.5; }
  [data-testid="metric-container"] {
    background: #142332; border: 1px solid #294052;
    border-radius: 14px; padding: 1rem 1.1rem; min-height: 110px;
  }
  [data-testid="stMetricLabel"] { color: #9eb1c0 !important; font-size: .82rem; }
  [data-testid="stMetricValue"] { color: #e9fbf7 !important; font-size: 1.52rem; font-weight: 750; }
  [data-testid="stMetricDelta"] { color: #65ded0; }
  .stTabs [data-baseweb="tab-list"] {
    border-bottom: 1px solid #294052; gap: 1rem; margin-top: .4rem;
  }
  .stTabs [data-baseweb="tab-list"] button {
    color: #9eb1c0; font-weight: 650; padding: .8rem .3rem;
  }
  .stTabs [data-baseweb="tab-list"] button:hover { color: #edf4f7; }
  .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
    color: #71e1d2; border-bottom: 2px solid #2dd4bf;
  }
  hr { border-color: #294052 !important; }
  h2, h3 { color: #f0f8fa; letter-spacing: -.02em; }
  [data-testid="stDataFrame"] { border: 1px solid #294052; border-radius: 12px; }
  [data-testid="stExpander"] { border: 1px solid #294052; border-radius: 12px; }
  div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
    background-color: #152635; border-color: #315166;
  }
  @media (max-width: 700px) {
    .block-container { padding: 1rem .8rem 2rem; }
    .hero { padding: 1.3rem; }
    [data-testid="metric-container"] { min-height: 90px; }
  }
</style>
""", unsafe_allow_html=True)

# ── Restore the prepared snapshot on first run ────────────────────────────────
if not os.path.exists(DB_PATH):
    snapshot_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "assets", "retail.db.gz"
    )
    try:
        with st.spinner("Preparing dashboard data..."):
            restore_database(snapshot_path, DB_PATH)
    except (OSError, ValueError) as error:
        st.error(f"Could not prepare dashboard data: {error}")
        st.caption("For a local rebuild, run python ingest_data.py.")
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
    st.markdown('<div class="eyebrow">Explore the data</div>', unsafe_allow_html=True)
    st.markdown("### Market")

    countries   = ["All Countries"] + get_countries(DB_PATH)
    default_idx = countries.index("United Kingdom") if "United Kingdom" in countries else 0
    country     = st.selectbox(
        "Country", options=countries, index=default_idx,
        help="Cohorts begin with a customer's first purchase in the selected country.",
    )
    st.caption("Choose a country to recalculate every cohort and chart.")

    st.divider()
    st.markdown("### Source snapshot")

    stats = get_db_stats(DB_PATH, country)
    st.markdown(
        f"**{stats['n_rows']:,}** cleaned line items  \n"
        f"**{stats['n_invoices']:,}** invoices  \n"
        f"**£{stats['total_revenue']:,.0f}** gross positive-line revenue"
    )
    st.caption(f"Source: {stats['min_month']} to {stats['max_month']}")

    st.divider()
    st.caption("UCI Online Retail II · Python, DuckDB, Streamlit")


# ── Load cohort data ───────────────────────────────────────────────────────────
analysis_cutoff = get_analysis_cutoff(DB_PATH)
with st.spinner(f"Running cohort analysis for {country} ..."):
    retention_df, avg_df, summary_df = run_cohort_analysis(DB_PATH, country, analysis_cutoff)

if retention_df.empty:
    st.warning(f"No cohort data for **{country}**. Choose a different country.")
    st.stop()

cohort_months = sorted(retention_df["cohort_month"].unique().tolist())
n_cohorts     = len(cohort_months)
analyzed_customers = int(summary_df["cohort_size"].sum())


# ── Header and key measures ────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
  <div class="eyebrow">Customer analytics / Online Retail II</div>
  <h1>Retention &amp; cohort analysis</h1>
  <p>Explore repeat purchasing, compare acquisition cohorts, and frame a testable retention opportunity.</p>
</div>
""", unsafe_allow_html=True)
st.caption(
    f"{country}  ·  {n_cohorts} acquisition cohorts  ·  "
    f"{analyzed_customers:,} customers in complete months  ·  "
    f"Complete months through {analysis_cutoff[:7]}"
)

def weighted_retention(period: int) -> str:
    observed = retention_df[retention_df["period_number"] == period]
    if observed.empty:
        return "—"
    return f"{100 * observed['active_users'].sum() / observed['cohort_size'].sum():.1f}%"

m6_values = summary_df["m6_revenue_per_customer"].dropna()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Acquired customers", f"{analyzed_customers:,}",
          help="Distinct customers acquired through the last complete month.")
k2.metric("Month 1 repeat rate", weighted_retention(1),
          help="Customers purchasing in M1 divided by all cohorts observed through M1.")
k3.metric("Month 3 repeat rate", weighted_retention(3),
          help="Customers purchasing in M3 divided by all cohorts observed through M3.")
k4.metric("Median revenue / customer to M6",
          f"£{m6_values.median():,.0f}" if not m6_values.empty else "—",
          help="Median across cohorts observed through M6; includes revenue from M0 to M6.")


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "Cohort heatmap",
    "Retention curves",
    "Business insights",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — COHORT HEATMAP
# Slider controls max cohort_index displayed (0 – 12).
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    heading, control = st.columns([3, 1], vertical_alignment="bottom")
    with heading:
        st.markdown('<div class="section-kicker">01 / Retention matrix</div>', unsafe_allow_html=True)
        st.markdown("## Where do customers come back?")
        st.caption("Each cell shows the share of an acquisition cohort purchasing in that month.")
    with control:
        max_period = st.slider(
            "Months after first purchase",
            min_value=1, max_value=12, value=12, step=1,
            help="Show M0 through the selected number of months.",
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
    active_pivot = (
        retention_df[retention_df["period_number"] <= max_period]
        .pivot_table(index="cohort_month", columns="period_number",
                     values="active_users", aggfunc="first")
        .reindex(index=pivot.index, columns=pivot.columns)
    )
    x_labels = [f"M{int(c)}" for c in pivot.columns]
    y_labels = pivot.index.tolist()

    # Per-cell annotations
    annotations = []
    for ri in range(len(y_labels)):
        for ci in range(len(x_labels)):
            val = z[ri, ci]
            if not pd.isna(val):
                annotations.append(dict(
                    text=f"{val:.0f}",
                    x=x_labels[ci], y=y_labels[ri],
                    xref="x", yref="y",
                    showarrow=False,
                    font=dict(size=9, color="#0b2330" if val >= 45 else "#f0fffc"),
                ))

    fig_heat = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=y_labels,
        text=active_pivot.values,
        colorscale=[
            [0.00, "#173444"], [0.20, "#1b6c77"],
            [0.40, "#2ab5a8"], [0.65, "#83dfca"], [1.00, "#d9fff0"],
        ],
        zmin=0, zmax=100,
        xgap=2, ygap=2,
        colorbar=dict(title=dict(text="Retention", side="right"),
                      ticksuffix="%", tickvals=[0, 25, 50, 75, 100], len=0.84),
        hoverongaps=False,
        hovertemplate="Cohort %{y}<br>%{x}: %{z:.1f}% retained"
                      "<br>%{text:,.0f} active buyers<extra></extra>",
    ))
    fig_heat.update_layout(
        xaxis=dict(title="Months since first purchase", side="top",
                   tickfont=dict(color="#a9c0ca", size=11), showgrid=False),
        yaxis=dict(title=None, autorange="reversed",
                   tickfont=dict(color="#a9c0ca", size=10), showgrid=False),
        annotations=annotations,
        height=max(450, n_cohorts * 26 + 105),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0b1220",
        font=dict(color="#dbecef"),
        margin=dict(l=85, r=60, t=55, b=20),
    )
    st.plotly_chart(fig_heat, width="stretch")
    st.caption("M0 = first purchase month · Blank = not yet observed · Darker cells = lower retention")

    with st.expander("View retention values"):
        raw_pivot = pivot.copy().round(1)
        raw_pivot.columns = [f"M{int(c)}" for c in raw_pivot.columns]
        st.dataframe(
            raw_pivot,
            width="stretch",
        )
        st.download_button(
            "Download retention table",
            raw_pivot.to_csv().encode("utf-8"),
            file_name=f"retention_{country.lower().replace(' ', '_')}.csv",
            mime="text/csv",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — RETENTION CURVES
# Multiselect controls which cohort months are drawn.
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown('<div class="section-kicker">02 / Cohort comparison</div>', unsafe_allow_html=True)
    st.markdown("## How do cohorts compare over time?")
    st.caption(
        "The dashed line is the average of cohorts observed at each age. "
        "Highest and lowest labels refer to M3 retention among eligible cohorts."
    )

    default_selection = cohort_months[:6] if n_cohorts >= 6 else cohort_months
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
            "#55c8ff", "#ffbd69", "#ba9cff", "#ef7895", "#8dd889",
            "#f38e69", "#7be0d0", "#e2abec", "#f1d675", "#a2b8ff",
        ]

        fig_curves = go.Figure()
        for idx, cohort in enumerate(sorted(selected)):
            cdf    = retention_df[retention_df["cohort_month"] == cohort].sort_values("period_number")
            color  = PALETTE[idx % len(PALETTE)]
            label  = cohort
            if cohort == best_cohort:
                label += " (highest M3)"
            elif cohort == worst_cohort:
                label += " (lowest M3)"
            width = 3.0 if cohort in (best_cohort, worst_cohort) else 1.8

            fig_curves.add_trace(go.Scatter(
                x=cdf["period_number"],
                y=cdf["retention_rate"],
                mode="lines+markers",
                line=dict(color=color, width=width),
                marker=dict(size=5, line=dict(color="#0b1220", width=1)),
                name=label,
                hovertemplate=f"Cohort {cohort}<br>M%{{x}}: %{{y:.1f}}%<extra></extra>",
            ))

        fig_curves.add_trace(go.Scatter(
            x=avg_df["period_number"], y=avg_df["avg_retention_rate"],
            mode="lines", name="Observed cohort average",
            line=dict(color="#e8f5f2", width=3, dash="dash"),
            hovertemplate="M%{x}: %{y:.1f}%<extra></extra>",
        ))

        fig_curves.update_layout(
            xaxis=dict(title="Months since first purchase", tickmode="linear", tick0=0, dtick=1,
                       gridcolor="#233647", tickfont=dict(color="#9eb1c0")),
            yaxis=dict(title="Customers retained", ticksuffix="%", range=[0, 105],
                       gridcolor="#233647", tickfont=dict(color="#9eb1c0")),
            legend=dict(
                orientation="h", x=0, y=-0.20, xanchor="left", yanchor="top",
                bgcolor="rgba(0,0,0,0)", font=dict(size=10, color="#c8d9de"),
            ),
            height=530, hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0b1220",
            font=dict(color="#dbecef"),
            margin=dict(l=65, r=25, t=25, b=120),
        )
        st.plotly_chart(fig_curves, width="stretch")

        # Quick-reference table for the selected cohorts
        if not summary_df.empty:
            st.markdown("#### Selected cohort details")
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
                sel_summary.set_index("Cohort").round(1),
                width="stretch",
            )
            st.caption("Revenue per customer is shown only for cohorts with a complete M6.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — BUSINESS INSIGHTS
# Age-matched cohort metrics and testable business recommendations
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown('<div class="section-kicker">03 / Analyst readout</div>', unsafe_allow_html=True)
    st.markdown("## What should the business test next?")
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

        with st.container(border=True):
            st.markdown("**What the data says**")
            st.markdown(
                f"The **{best['cohort_month']}** cohort has the highest M3 "
                f"retention (**{best['m3_retention']:.1f}%**) among {len(m3)} "
                "eligible cohorts. Acquisition month is associated with the "
                "difference; this dataset does not identify its cause."
            )

    if len(m6) >= 2:
        st.markdown("### Revenue per customer through M6")
        st.caption(
            "Revenue from acquisition month through month 6, divided by the "
            "original cohort size. Only cohorts with a complete M6 are included."
        )
        revenue_chart = m6.sort_values("m6_revenue_per_customer")
        fig_revenue = go.Figure(go.Bar(
            x=revenue_chart["m6_revenue_per_customer"],
            y=revenue_chart["cohort_month"],
            orientation="h",
            marker_color=[
                "#67dfc9" if value == revenue_chart["m6_revenue_per_customer"].max()
                else "#2d8490"
                for value in revenue_chart["m6_revenue_per_customer"]
            ],
            hovertemplate="Cohort %{y}<br>£%{x:,.0f} per acquired customer<extra></extra>",
        ))
        fig_revenue.update_layout(
            xaxis=dict(title="Revenue per acquired customer (£)",
                       gridcolor="#233647", tickprefix="£",
                       tickfont=dict(color="#9eb1c0")),
            yaxis=dict(title=None, tickfont=dict(color="#9eb1c0")),
            height=max(340, len(revenue_chart) * 27 + 95),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0b1220",
            font=dict(color="#dbecef"),
            margin=dict(l=75, r=25, t=20, b=55),
        )
        st.plotly_chart(fig_revenue, width="stretch")
        with st.expander("View M6 cohort data"):
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
    st.markdown("### Test opportunity: first-month win-back")
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
        scenario_col, test_col = st.columns([1, 2])
        with scenario_col:
            with st.container(border=True):
                st.metric("Illustrative annual gross revenue",
                          f"£{annual_scenario:,.0f}")
                st.caption("Scenario only · not a forecast or profit estimate")
        with test_col:
            with st.container(border=True):
                st.markdown("**Proposed experiment**")
                st.markdown(
                    f"Only **{m1_rate:.1f}%** of acquired customers purchased "
                    f"again in M1 across {len(m1_rows)} eligible cohorts. "
                    "Test a post-purchase message sequence against a holdout "
                    "group. Measure incremental purchases, revenue, and margin."
                )
        with st.expander("Show scenario assumptions and calculation"):
            st.markdown(
                f"Assume **5%** of M1 nonbuyers make one additional purchase: "
                f"about **{recovered_per_cohort:.1f}** buyers per average cohort "
                f"× **£{m1_arpu:,.0f}** observed revenue per active M1 buyer "
                f"× **12** cohorts = **£{annual_scenario:,.0f}** annual gross revenue. "
                "This assumes similar cohort size and spend, no cannibalization, "
                "and excludes campaign cost and margin."
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
