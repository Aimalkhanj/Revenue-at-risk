"""
Step 2 - Business analysis: KPIs, cohorts, RFM, Pareto, returns, CLV,
seasonality, market basket and revenue-at-risk.

Runs the SQL models in sql/kpis_and_cohorts.sql on DuckDB, then does the
customer-level modelling in pandas. Writes every result to data/outputs/*.csv
and one compact data/dashboard_data.json used by the dashboard.
"""
import json, re, sys
from itertools import combinations
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTD = DATA / "outputs"; OUTD.mkdir(parents=True, exist_ok=True)

sales = pd.read_parquet(DATA / "sales_clean.parquet")
returns = pd.read_parquet(DATA / "returns_clean.parquet")

con = duckdb.connect()
con.register("sales", sales)
con.register("returns", returns)

# ---------- run the SQL models ----------
sql_text = (ROOT / "sql" / "kpis_and_cohorts.sql").read_text()
blocks = re.split(r"--\s*name:\s*(\w+)", sql_text)[1:]
results = {}
for name, body in zip(blocks[0::2], blocks[1::2]):
    stmt = "\n".join(l for l in body.splitlines() if not l.strip().startswith("--")).strip().rstrip(";")
    if stmt.upper().startswith("CREATE"):
        con.execute(stmt)
    else:
        results[name] = con.execute(stmt).df()
        results[name].to_csv(OUTD / f"{name}.csv", index=False)

orders = con.execute("SELECT * FROM fact_orders ORDER BY Invoice").df()
cust = con.execute("SELECT * FROM dim_customer ORDER BY CustomerID").df()

out = {}
FY = ["FY2010", "FY2011"]
kpi = results["kpi_by_year"].set_index("fiscal_year")
ret_y = results["returns_by_year"].set_index("fiscal_year")
print(kpi, "\n", ret_y)

# ---------- 1. Headline KPIs (FY2011 vs FY2010) ----------
def yoy(a, b): return round((a - b) / b * 100, 1)
cur, prev = kpi.loc["FY2011"], kpi.loc["FY2010"]

known = orders[orders.CustomerID.notna()]
def repeat_rate(fy):
    o = known[known.fiscal_year == fy].groupby("CustomerID").size()
    return round((o >= 2).mean() * 100, 1)

ret_rate = {fy: round(ret_y.loc[fy, "returned_value"] /
                      (kpi.loc[fy, "net_sales"] + ret_y.loc[fy, "returned_value"]) * 100, 2) for fy in FY}

guest_share = round(orders.loc[orders.CustomerID.isna() & (orders.fiscal_year == "FY2011"), "order_value"].sum()
                    / cur.net_sales * 100, 1)

out["kpis"] = {
    "net_sales": float(cur.net_sales), "net_sales_prev": float(prev.net_sales),
    "net_sales_yoy": yoy(cur.net_sales, prev.net_sales),
    "orders": int(cur.orders), "orders_yoy": yoy(cur.orders, prev.orders),
    "aov": float(cur.avg_order_value), "aov_yoy": yoy(cur.avg_order_value, prev.avg_order_value),
    "customers": int(cur.active_customers), "customers_yoy": yoy(cur.active_customers, prev.active_customers),
    "repeat_rate": repeat_rate("FY2011"), "repeat_rate_prev": repeat_rate("FY2010"),
    "returns_value": float(ret_y.loc["FY2011", "returned_value"]),
    "return_rate": ret_rate["FY2011"], "return_rate_prev": ret_rate["FY2010"],
    "guest_share": guest_share,
}

# ---------- 2. Monthly trend (24 full months, FY overlay) ----------
m = results["monthly_revenue"].copy()
m["month"] = pd.to_datetime(m["month"])
m = m[m.month < "2011-12-01"]
m["fy"] = np.where(m.month < "2010-12-01", "FY2010", "FY2011")
m["label"] = m.month.dt.strftime("%b")
out["monthly"] = {
    "labels": m[m.fy == "FY2011"].label.tolist(),
    "fy2010": m[m.fy == "FY2010"].revenue.round(0).tolist(),
    "fy2011": m[m.fy == "FY2011"].revenue.round(0).tolist(),
    "orders2011": m[m.fy == "FY2011"].orders.tolist(),
    "customers2011": m[m.fy == "FY2011"].customers.tolist(),
}
q4 = m[(m.fy == "FY2011") & m.month.dt.month.isin([9, 10, 11])].revenue.sum()
out["kpis"]["q4_share"] = round(q4 / m[m.fy == "FY2011"].revenue.sum() * 100, 1)

# ---------- 3. Cohort retention (first 12 cohorts, months 0..12) ----------
coh = results["cohort_retention"].copy()
coh["cohort_month"] = pd.to_datetime(coh["cohort_month"])
coh = coh[(coh.cohort_month < "2010-12-01") & (coh.month_n <= 12)]
piv = coh.pivot(index="cohort_month", columns="month_n", values="retention")
size = coh[coh.month_n == 0].set_index("cohort_month").customers
out["cohort"] = {
    "rows": [{"cohort": d.strftime("%b %y"), "size": int(size[d]),
              "values": [None if pd.isna(v) else round(float(v) * 100, 1) for v in piv.loc[d].tolist()]}
             for d in piv.index]
}
# average retention curve: Dec-09 cohort is the pre-existing base, so average later cohorts
later = piv.iloc[1:]
out["cohort"]["avg_curve"] = [round(float(later[c].mean()) * 100, 1) for c in piv.columns]
out["cohort"]["dec09_m12"] = round(float(piv.iloc[0][12]) * 100, 1)
out["cohort"]["new_m1"] = out["cohort"]["avg_curve"][1]
out["cohort"]["new_m3"] = out["cohort"]["avg_curve"][3]
piv.to_csv(OUTD / "cohort_retention_matrix.csv")

# ---------- 4. RFM segmentation ----------
snap = pd.Timestamp("2011-12-10")
rfm = cust.assign(
    recency=(snap - cust.last_order_ts).dt.days,
    frequency=cust.orders,
    monetary=cust.lifetime_revenue,
)
rfm["R"] = pd.qcut(rfm.recency, 5, labels=[5, 4, 3, 2, 1]).astype(int)
rfm["F"] = pd.qcut(rfm.frequency.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
rfm["M"] = pd.qcut(rfm.monetary.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
rfm["FM"] = ((rfm.F + rfm.M) / 2).round().astype(int)

def segment(r):
    R, FM = r.R, r.FM
    if R >= 4 and FM >= 4: return "Champions"
    if R >= 3 and FM >= 3: return "Loyal"
    if R >= 4 and FM <= 2: return "New & Promising"
    if R == 3 and FM <= 2: return "Need Attention"
    if R <= 2 and FM >= 4: return "At Risk – High Value"
    if R <= 2 and FM == 3: return "At Risk"
    if R == 2: return "Hibernating"
    return "Lost"
rfm["segment"] = rfm.apply(segment, axis=1)

# trailing-12-month revenue (Dec-10..Nov-11 + Dec-11) per customer = what is at stake next year
t12 = known[known.order_ts >= "2010-12-10"].groupby("CustomerID").order_value.sum()
rfm["t12_revenue"] = rfm.CustomerID.map(t12).fillna(0)
rfm.to_csv(OUTD / "rfm_customers.csv", index=False)

order_seg = ["Champions", "Loyal", "New & Promising", "Need Attention",
             "At Risk – High Value", "At Risk", "Hibernating", "Lost"]
seg = (rfm.groupby("segment")
          .agg(customers=("CustomerID", "count"), revenue=("monetary", "sum"),
               t12=("t12_revenue", "sum"), recency=("recency", "median"),
               orders=("frequency", "median"), aov=("monetary", "median"))
          .reindex(order_seg))
seg["cust_share"] = seg.customers / seg.customers.sum() * 100
seg["rev_share"] = seg.revenue / seg.revenue.sum() * 100
seg.to_csv(OUTD / "rfm_segments.csv")
out["segments"] = [{"name": k, "customers": int(v.customers), "cust_share": round(v.cust_share, 1),
                    "rev_share": round(v.rev_share, 1), "revenue": round(v.revenue),
                    "t12": round(v.t12), "recency": int(v.recency), "orders": int(v.orders)}
                   for k, v in seg.iterrows()]
print(seg.round(1))

# ---------- 5. Revenue at risk ----------
risk = rfm[rfm.segment.isin(["At Risk – High Value", "At Risk"])]
at_risk_rev = float(risk.t12_revenue.sum())
out["risk"] = {
    "customers": int(len(risk)),
    "t12_revenue": round(at_risk_rev),
    "share_of_t12": round(at_risk_rev / t12.sum() * 100, 1),
    "high_value_customers": int((rfm.segment == "At Risk – High Value").sum()),
    "high_value_t12": round(float(rfm.loc[rfm.segment == "At Risk – High Value", "t12_revenue"].sum())),
    "median_days_silent": int(risk.recency.median()),
    "win_back": {p: round(at_risk_rev * p / 100) for p in (10, 20, 30)},
}
# "Overdue" model: a repeat customer is at risk when their silence is more than twice
# their own usual gap between orders (min 60 days) but under a year (after a year = lost).
ko = known.sort_values("order_ts")
gaps = ko.groupby("CustomerID").order_ts.apply(lambda s: s.diff().dt.days.median())
rfm["usual_gap"] = rfm.CustomerID.map(gaps)
ann = known[(known.order_ts >= "2010-12-10")].groupby("CustomerID").order_value.sum()
rfm["annual_value"] = rfm.CustomerID.map(ann).fillna(0)
od = rfm[(rfm.frequency >= 2) & (rfm.recency > np.maximum(2 * rfm.usual_gap, 60)) & (rfm.recency <= 365)]
od = od[od.annual_value > 0]
od.sort_values("annual_value", ascending=False).to_csv(OUTD / "overdue_customers.csv", index=False)
od_val = float(od.annual_value.sum())
out["risk"].update({
    "overdue_customers": int(len(od)),
    "overdue_value": round(od_val),
    "overdue_share": round(od_val / float(ann.sum()) * 100, 1),
    "overdue_top100_value": round(float(od.nlargest(100, "annual_value").annual_value.sum())),
    "overdue_median_gap": int(od.usual_gap.median()),
    "overdue_median_silence": int(od.recency.median()),
    "save": {p: round(od_val * p / 100) for p in (10, 25, 50)},
})
bands = pd.cut(od.recency, [60, 120, 180, 270, 365], labels=["60–120d", "120–180d", "180–270d", "270–365d"])
out["risk"]["overdue_bands"] = [{"band": str(b), "customers": int(len(g)), "value": round(float(g.annual_value.sum()))}
                                for b, g in od.groupby(bands, observed=False)]
od_seg = od.segment.value_counts()
out["risk"]["overdue_by_segment"] = {k: int(v) for k, v in od_seg.items()}

# Year-on-year customer churn: active FY2010, not seen in FY2011/Dec-11
c10 = set(known[known.fiscal_year == "FY2010"].CustomerID)
c11 = set(known[known.fiscal_year != "FY2010"].CustomerID)
churned = c10 - c11
fy10_rev = known[known.fiscal_year == "FY2010"].groupby("CustomerID").order_value.sum()
out["risk"]["churned_customers"] = len(churned)
out["risk"]["churn_rate"] = round(len(churned) / len(c10) * 100, 1)
out["risk"]["churned_fy10_revenue"] = round(float(fy10_rev[list(churned)].sum()))
out["risk"]["new_customers_fy11"] = int((cust.first_order_ts >= "2010-12-01").sum() -
                                        (cust.first_order_ts >= "2011-12-01").sum())

# ---------- 6. Pareto / concentration ----------
cr = known[known.fiscal_year == "FY2011"].groupby("CustomerID").order_value.sum().sort_values(ascending=False)
cum = cr.cumsum() / cr.sum() * 100
pct = np.arange(1, len(cr) + 1) / len(cr) * 100
pts = [0, 1, 2, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100]
out["pareto"] = {"x": pts, "y": [0] + [round(float(np.interp(p, pct, cum.values)), 1) for p in pts[1:]],
                 "top20": round(float(np.interp(20, pct, cum.values)), 1),
                 "top1": round(float(np.interp(1, pct, cum.values)), 1),
                 "top10_customers_share": round(float(cr.head(10).sum() / cr.sum() * 100), 1)}

# ---------- 7. Returns ----------
r11 = returns[(returns.InvoiceDate >= "2010-12-01") & (returns.InvoiceDate < "2011-12-01")]
s11 = sales[(sales.InvoiceDate >= "2010-12-01") & (sales.InvoiceDate < "2011-12-01")]
prod_s = s11.groupby("StockCode").agg(sales=("Revenue", "sum"), desc=("Description", "first"))
prod_r = r11.groupby("StockCode").Revenue.sum().rename("returned")
pr = prod_s.join(prod_r, how="inner")
pr["ret_rate"] = pr.returned / (pr.sales + pr.returned) * 100
top_ret = pr.sort_values("returned", ascending=False).head(8)
out["returns"] = {
    "top_products": [{"name": d.title()[:30], "returned": round(r), "rate": round(rt, 1)}
                     for d, r, rt in zip(top_ret.desc, top_ret.returned, top_ret.ret_rate)],
    "monthly": r11.groupby(r11.InvoiceDate.dt.to_period("M")).Revenue.sum().round(0).tolist(),
    "top8_share": round(float(top_ret.returned.sum() / r11.Revenue.sum() * 100), 1),
    "customers_returning": int(r11.CustomerID.nunique()),
}
pr.sort_values("returned", ascending=False).to_csv(OUTD / "returns_by_product.csv")

# ---------- 8. Countries ----------
cty = s11.groupby("Country").Revenue.sum().sort_values(ascending=False)
cty_prev = sales[sales.InvoiceDate < "2010-12-01"].groupby("Country").Revenue.sum()
intl = cty.drop("United Kingdom").head(8)
out["countries"] = {
    "uk_share": round(float(cty["United Kingdom"] / cty.sum() * 100), 1),
    "intl_share": round(float(100 - cty["United Kingdom"] / cty.sum() * 100), 1),
    "top": [{"name": c, "revenue": round(v), "yoy": round(float((v - cty_prev.get(c, np.nan)) / cty_prev.get(c, np.nan) * 100), 1)}
            for c, v in intl.items()],
}

# ---------- 9. When do orders happen? weekday x hour heatmap ----------
o11 = orders[orders.fiscal_year == "FY2011"].copy()
o11["dow"] = o11.order_ts.dt.dayofweek
o11["hour"] = o11.order_ts.dt.hour
hm = o11.pivot_table(index="dow", columns="hour", values="order_value", aggfunc="sum").reindex(columns=range(7, 21)).fillna(0)
out["heatmap"] = {"days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                  "present_days": [int(d) for d in hm.index],
                  "hours": list(range(7, 21)),
                  "values": hm.round(0).values.tolist()}
peak = hm.stack().idxmax()
out["heatmap"]["peak"] = {"day": out["heatmap"]["days"][int(peak[0])], "hour": int(peak[1])}

# ---------- 10. CLV and first-order effect ----------
first = (known.sort_values("order_ts").groupby("CustomerID").first()
              [["order_ts", "order_value", "distinct_items"]])
first = first[first.order_ts < "2010-12-10"]  # need a full 12 months of follow-up
k12 = known.merge(first[["order_ts"]].rename(columns={"order_ts": "first_ts"}), left_on="CustomerID", right_index=True)
k12 = k12[k12.order_ts <= k12.first_ts + pd.Timedelta(days=365)]
clv12 = k12.groupby("CustomerID").order_value.sum()
reorders = k12.groupby("CustomerID").size() - 1
first["clv12"] = clv12
first["repeat"] = (reorders.reindex(first.index).fillna(0) > 0).astype(int)
first["fo_band"] = pd.qcut(first.order_value, 4, labels=["Q1 small", "Q2", "Q3", "Q4 large"])
fo = first.groupby("fo_band", observed=True).agg(repeat=("repeat", "mean"), clv=("clv12", "median"),
                                                 first=("order_value", "median"), n=("repeat", "size"))
chi2, pval, *_ = stats.chi2_contingency(pd.crosstab(first.fo_band, first.repeat))
out["clv"] = {
    "median_clv12": round(float(first.clv12.median())),
    "mean_clv12": round(float(first.clv12.mean())),
    "repeat_12m": round(float(first.repeat.mean() * 100), 1),
    "by_first_order": [{"band": str(b), "repeat": round(r["repeat"] * 100, 1), "clv": round(r["clv"]),
                        "first": round(r["first"])} for b, r in fo.iterrows()],
    "chi2_p": float(pval), "n": int(len(first)),
    "repeaters_clv": round(float(first.loc[first.repeat == 1, "clv12"].median())),
    "one_timers_clv": round(float(first.loc[first.repeat == 0, "clv12"].median())),
}
fo.to_csv(OUTD / "first_order_vs_repeat.csv")

# ---------- 11. Market basket (FY2011, product pairs, lift) ----------
bk = s11[s11.has_customer].groupby("Invoice").StockCode.apply(lambda x: sorted(set(x)))
bk = bk[bk.str.len().between(2, 60)]
n_b = len(bk)
item_cnt = Counter(i for b in bk for i in b)
keep = {i for i, c in item_cnt.items() if c / n_b >= 0.015}
pair_cnt = Counter(p for b in bk for p in combinations([i for i in b if i in keep], 2))
desc = s11.groupby("StockCode").Description.first()
rows = []
for (a, b), c in pair_cnt.items():
    sup = c / n_b
    if sup < 0.01: continue
    conf = c / item_cnt[a]
    lift = sup / ((item_cnt[a] / n_b) * (item_cnt[b] / n_b))
    rows.append((a, b, sup, max(conf, c / item_cnt[b]), lift))
mb = pd.DataFrame(rows, columns=["a", "b", "support", "confidence", "lift"])
mb["a_desc"] = mb.a.map(desc); mb["b_desc"] = mb.b.map(desc)
mb = mb.sort_values("lift", ascending=False)
mb.to_csv(OUTD / "market_basket_pairs.csv", index=False)
# drop near-duplicate colour variants of the same product to show genuinely different pairs
def stem(s): return " ".join(s.split()[-2:])
mb_show = mb[mb.a_desc.map(stem) != mb.b_desc.map(stem)].head(6)
out["basket"] = {"baskets": n_b,
                 "pairs": [{"a": a.title()[:28], "b": b.title()[:28], "lift": round(l, 1),
                            "conf": round(c * 100), "support": round(s * 100, 1)}
                           for a, b, l, c, s in zip(mb_show.a_desc, mb_show.b_desc, mb_show.lift,
                                                    mb_show.confidence, mb_show.support)]}

out["meta"] = {"rows_raw": 1067371, "rows_clean": int(len(sales)), "customers": int(len(cust)),
               "products": int(sales.StockCode.nunique()), "countries": int(sales.Country.nunique()),
               "period": "Dec 2009 – Dec 2011"}

(DATA / "dashboard_data.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps({k: out[k] for k in ["kpis", "risk", "pareto", "clv", "countries"]}, indent=1, default=float))
print(json.dumps(out["basket"], indent=1)); print(json.dumps(out["returns"], indent=1))
print("cohort avg", out["cohort"]["avg_curve"], "peak", out["heatmap"]["peak"])

# ---------- 12. Action plan with money impact (assumptions stated) ----------
k, r, c = out["kpis"], out["risk"], out["clv"]
growth = k["net_sales"] - k["net_sales_prev"]
act_winback = r["save"][25]                                   # win back 25% of overdue annual value
uplift_pp = 5                                                  # +5 points of new customers making a 2nd order
act_second = round(r["new_customers_fy11"] * uplift_pp / 100 * (c["repeaters_clv"] - c["one_timers_clv"]))
top8_returns = k["returns_value"] * out["returns"]["top8_share"] / 100
act_returns = round(top8_returns / 2)                          # halve returns on the 8 worst products
out["actions"] = {
    "yoy_growth_value": round(growth),
    "items": [
        {"title": "Win back overdue repeat customers", "value": act_winback,
         "assumption": "Recover 25% of the £{:,} annual value held by {} overdue customers".format(r["overdue_value"], r["overdue_customers"])},
        {"title": "Engineer the second order", "value": act_second,
         "assumption": "+{} pts of FY2011's {:,} new customers reorder; each repeater is worth £{:,} more in year one".format(
             uplift_pp, r["new_customers_fy11"], c["repeaters_clv"] - c["one_timers_clv"])},
        {"title": "Fix the most-returned products", "value": act_returns,
         "assumption": "Halve returns on the 8 products behind {}% of returned value".format(out["returns"]["top8_share"])},
    ],
}
out["actions"]["total"] = sum(i["value"] for i in out["actions"]["items"])
out["actions"]["vs_growth"] = round(out["actions"]["total"] / growth, 2)
(DATA / "dashboard_data.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps(out["actions"], indent=1))
