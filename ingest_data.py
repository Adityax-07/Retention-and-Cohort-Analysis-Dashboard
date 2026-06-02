"""
Download, clean, and persist Online Retail II — UCI ML Repository.

Run once before launching the Streamlit dashboard:
    python ingest_data.py

Output: data/retail.db
  - Table 'transactions' : cleaned line items  (~450 k rows)
  - Table 'orders'       : invoice-level aggregates (feeds cohort SQL)

Cleaning rules applied
  1. Drop rows where Customer ID is null
  2. Remove rows with Quantity <= 0  (returns / cancellations)
  3. Remove rows with Price <= 0
  4. Derive InvoiceMonth (YYYY-MM) and Revenue (Quantity * Price)
"""

import io
import os
import sqlite3
import zipfile

import pandas as pd
import requests
from tqdm import tqdm

DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
DATA_DIR    = "data"
DB_PATH     = os.path.join(DATA_DIR, "retail.db")
XLSX_CACHE  = os.path.join(DATA_DIR, "online_retail_II.xlsx")

SHEETS = ["Year 2009-2010", "Year 2010-2011"]


# ── Download ──────────────────────────────────────────────────────────────────

def download_xlsx() -> str:
    """Download the UCI zip and extract the Excel file. Returns local path."""
    if os.path.exists(XLSX_CACHE):
        print(f"  Cached file found: {XLSX_CACHE}  (skipping download)")
        return XLSX_CACHE

    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Downloading from UCI ML Repository …")
    print(f"  URL : {DATASET_URL}")

    resp = requests.get(DATASET_URL, stream=True, timeout=180)
    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0))
    buf   = io.BytesIO()

    with tqdm(total=total, unit="B", unit_scale=True, desc="  Progress") as bar:
        for chunk in resp.iter_content(chunk_size=8_192):
            buf.write(chunk)
            bar.update(len(chunk))

    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        xlsx_names = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if not xlsx_names:
            raise FileNotFoundError(
                f"No .xlsx found inside ZIP. Contents: {zf.namelist()}"
            )
        target = xlsx_names[0]
        print(f"  Extracting: {target}")
        with zf.open(target) as src, open(XLSX_CACHE, "wb") as dst:
            dst.write(src.read())

    print(f"  Saved to : {XLSX_CACHE}")
    return XLSX_CACHE


# ── Load & clean ──────────────────────────────────────────────────────────────

def load_and_clean(xlsx_path: str) -> pd.DataFrame:
    """Read both year-sheets, concatenate, apply cleaning rules."""
    frames = []
    for sheet in SHEETS:
        print(f"  Reading '{sheet}' …", end="", flush=True)
        df = pd.read_excel(
            xlsx_path,
            sheet_name=sheet,
            dtype={"Customer ID": str, "Invoice": str, "StockCode": str},
        )
        print(f"  {len(df):>9,} rows")
        frames.append(df)

    raw = pd.concat(frames, ignore_index=True)
    n0  = len(raw)
    print(f"\nRaw combined          : {n0:>9,} rows")

    # ── Rule 1: drop null CustomerID ──────────────────────────────────────────
    clean = raw.dropna(subset=["Customer ID"])
    removed = n0 - len(clean)
    print(f"Drop null CustomerID  : -{removed:>8,}    ({len(clean):,} remain)")
    n0 = len(clean)

    # ── Rule 2: remove returns / cancellations (Quantity <= 0) ───────────────
    clean = clean[clean["Quantity"] > 0]
    removed = n0 - len(clean)
    print(f"Remove Quantity <= 0  : -{removed:>8,}    ({len(clean):,} remain)")
    n0 = len(clean)

    # ── Rule 3: remove zero / negative prices ────────────────────────────────
    clean = clean[clean["Price"] > 0]
    removed = n0 - len(clean)
    print(f"Remove Price <= 0     : -{removed:>8,}    ({len(clean):,} remain)")

    # ── Derived columns ───────────────────────────────────────────────────────
    clean = clean.copy()
    clean["InvoiceDate"]  = pd.to_datetime(clean["InvoiceDate"])
    clean["InvoiceMonth"] = clean["InvoiceDate"].dt.strftime("%Y-%m")
    clean["Revenue"]      = (clean["Quantity"] * clean["Price"]).round(2)

    # ── Standardise column names to match user spec ───────────────────────────
    clean = clean.rename(columns={
        "Invoice":     "InvoiceNo",
        "Price":       "UnitPrice",
        "Customer ID": "CustomerID",
    })

    clean = clean[[
        "InvoiceNo", "StockCode", "Description",
        "Quantity", "InvoiceDate", "InvoiceMonth",
        "UnitPrice", "Revenue",
        "CustomerID", "Country",
    ]].reset_index(drop=True)

    return clean


# ── Persist to SQLite ─────────────────────────────────────────────────────────

def save_to_sqlite(df: pd.DataFrame) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"  Removed stale {DB_PATH}")

    con = sqlite3.connect(DB_PATH)

    # ── transactions: cleaned line-item data (as requested) ──────────────────
    print(f"\nWriting {len(df):,} rows to transactions ...")
    df.to_sql("transactions", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS idx_tx_cust    ON transactions (CustomerID)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tx_month   ON transactions (InvoiceMonth)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tx_invoice ON transactions (InvoiceNo)")

    # ── orders: invoice-level aggregates (feeds the cohort SQL) ──────────────
    # One row per invoice: customer_id, order_date, total revenue.
    print("Building invoice-level  orders  table …")
    con.execute("""
        CREATE TABLE orders AS
        SELECT
            InvoiceNo               AS order_id,
            CustomerID              AS customer_id,
            DATE(InvoiceDate)       AS order_date,
            SUM(Revenue)            AS revenue
        FROM transactions
        GROUP BY InvoiceNo, CustomerID, DATE(InvoiceDate)
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_ord_cust ON orders (customer_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ord_date ON orders (order_date)")
    con.commit()

    # ── Verify ────────────────────────────────────────────────────────────────
    tx_cnt  = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    ord_cnt = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    con.close()

    print(f"  transactions : {tx_cnt:,} rows")
    print(f"  orders       : {ord_cnt:,} unique invoices")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> pd.DataFrame:
    print("=" * 64)
    print("Online Retail II — UCI ML Repository")
    print("Ingest · Clean · Load Pipeline")
    print("=" * 64)

    xlsx = download_xlsx()

    print("\nLoading and cleaning …")
    df = load_and_clean(xlsx)

    print(f"\nClean dataset summary")
    print(f"  Rows        : {len(df):,}")
    print(f"  Columns     : {df.shape[1]}")
    print(f"  Customers   : {df['CustomerID'].nunique():,}")
    print(f"  Invoices    : {df['InvoiceNo'].nunique():,}")
    print(f"  Date range  : {df['InvoiceDate'].min().date()}  to  {df['InvoiceDate'].max().date()}")
    print(f"  Revenue     : GBP {df['Revenue'].sum():>12,.2f}")
    print(f"  Countries   : {df['Country'].nunique()}")

    save_to_sqlite(df)

    print(f"\nDone.  {DB_PATH}  is ready.")
    print("Next step:  streamlit run app.py")
    return df


if __name__ == "__main__":
    main()
