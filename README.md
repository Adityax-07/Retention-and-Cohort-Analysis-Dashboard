---
title: Retention and Cohort Analysis Dashboard
emoji: 📊
colorFrom: blue
colorTo: red
sdk: streamlit
sdk_version: "1.32.0"
app_file: app.py
pinned: false
---

# Retention & Cohort Analysis Dashboard

Interactive cohort retention analysis on the **UCI Online Retail II** dataset (1.07M transactions, 5,878 customers, 25 monthly cohorts).

## Features

- **Cohort Heatmap** — 25×13 retention matrix (Reds colorscale, per-cell annotations)
- **Retention Curves** — best/worst cohort highlighted, 20% e-commerce benchmark line
- **Business Insights** — LTV comparison, revenue per cohort, quantified recommendations
- **Country filter** — sidebar selectbox (default: United Kingdom, 41 countries)
- **Dark theme** — GitHub-style dark UI (#0d1117 background, #4285f4 accent)

## Stack

| Layer | Tool |
|---|---|
| Data pipeline | `pandas`, `openpyxl`, `SQLite` |
| Analytics SQL | `DuckDB` (6 CTEs + 4 window functions) |
| Visualisation | `Plotly` |
| Dashboard | `Streamlit` |
| Dataset | [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii) |

## First Run

On first load the app downloads the UCI dataset (~7 MB zip), processes it, and writes `data/retail.db`. This takes **2–3 minutes**. Subsequent loads are instant (cached).

To run locally:

```bash
pip install -r requirements.txt
python ingest_data.py   # one-time
streamlit run app.py
```
