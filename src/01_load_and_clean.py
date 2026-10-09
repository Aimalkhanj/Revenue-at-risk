"""
Step 1 - Load, validate and clean the UCI Online Retail II dataset.

Input : data_raw/online_retail_II.xlsx  (two sheets: 2009-2010, 2010-2011)
Output: data/transactions_raw.parquet   (all rows, both sheets, untouched)
        data/sales_clean.parquet        (valid product sales lines)
        data/returns_clean.parquet      (cancellations / returns lines)
        data/cleaning_log.csv           (every rule applied and rows affected)
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw" / "online_retail_II.xlsx"
OUT = ROOT / "data"
OUT.mkdir(exist_ok=True)

# Stock codes that are not products (postage, fees, manual adjustments, samples)
NON_PRODUCT = {"POST", "DOT", "M", "C2", "BANK CHARGES", "AMAZONFEE", "CRUK",
               "D", "S", "PADS", "B", "ADJUST", "ADJUST2", "TEST001", "TEST002"}

log = []
def note(rule, before, after):
    log.append({"rule": rule, "rows_before": before, "rows_after": after,
                "rows_removed": before - after})

# ---------- Load ----------
raw_path = OUT / "transactions_raw.parquet"
if raw_path.exists():
    df = pd.read_parquet(raw_path)
else:
    sheets = pd.read_excel(RAW, sheet_name=None, dtype={"Invoice": str, "StockCode": str})
    df = pd.concat(sheets.values(), ignore_index=True)
    for c in ["Invoice", "StockCode", "Description", "Country"]:
        df[c] = df[c].astype("string")
    df.to_parquet(raw_path, index=False)

df = df.rename(columns={"Customer ID": "CustomerID"})
print("Raw rows:", len(df))

# ---------- Standardise types ----------
df["Invoice"] = df["Invoice"].astype(str).str.strip()
df["StockCode"] = df["StockCode"].astype(str).str.strip().str.upper()
df["Description"] = df["Description"].astype(str).str.strip().str.upper()
df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])

n = len(df); df = df.drop_duplicates(); note("Drop exact duplicate rows", n, len(df))

df["is_cancel"] = df["Invoice"].str.startswith("C")
df["is_product"] = ~df["StockCode"].isin(NON_PRODUCT) & ~df["StockCode"].str.startswith("GIFT")
df["Revenue"] = df["Quantity"] * df["Price"]

# ---------- Returns / cancellations ----------
ret = df[df["is_cancel"] & df["is_product"]].copy()
ret["Revenue"] = ret["Revenue"].abs()
ret["Quantity"] = ret["Quantity"].abs()
# the two giant test orders (74,215 and 80,995 units) were cancelled within minutes - drop both sides
n = len(ret); ret = ret[ret["Quantity"] < 20000]; note("Returns: drop cancellations of the giant outlier orders", n, len(ret))

# ---------- Sales ----------
n = len(df); s = df[~df["is_cancel"]]; note("Remove cancellation invoices (prefix C)", n, len(s))
n = len(s); s = s[~s["Invoice"].str.startswith("A")]; note("Remove bad-debt adjustments (prefix A)", n, len(s))
n = len(s); s = s[s["is_product"]]; note("Remove non-product codes (postage, fees, samples)", n, len(s))
n = len(s); s = s[(s["Quantity"] > 0) & (s["Price"] > 0)]; note("Remove zero/negative quantity or price", n, len(s))

# Extreme single-line outliers that were immediately cancelled (known in this dataset)
n = len(s); s = s[s["Quantity"] < 20000]; note("Remove extreme quantity outliers (>=20,000 units)", n, len(s))

s = s.copy()
s["has_customer"] = s["CustomerID"].notna()
s["CustomerID"] = s["CustomerID"].astype("Int64")
ret["CustomerID"] = ret["CustomerID"].astype("Int64")

cols = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate",
        "Price", "Revenue", "CustomerID", "Country", "has_customer"]
s[cols].to_parquet(OUT / "sales_clean.parquet", index=False)
ret[[c for c in cols if c != "has_customer"]].to_parquet(OUT / "returns_clean.parquet", index=False)

pd.DataFrame(log).to_csv(OUT / "cleaning_log.csv", index=False)
print(pd.DataFrame(log).to_string(index=False))
print("Clean sales rows:", len(s), "| with customer ID:", int(s["has_customer"].sum()))
print("Return rows:", len(ret))
print("Date range:", s["InvoiceDate"].min(), "->", s["InvoiceDate"].max())
