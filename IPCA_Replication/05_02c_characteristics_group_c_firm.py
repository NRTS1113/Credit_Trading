"""
Group C: Firm-Level Characteristics
Characteristics:
    C1 — Financial Statements (fmp_hist_financial_statements):
        #4   Book-to-price
        #5   Debt-to-EBITDA
        #8   Earnings-to-price
        #11  Firm total debt
        #15  Book leverage
        #16  Market leverage
        #17  Turnover volatility
        #19  Operating leverage
        #20  Profitability
        #21  Profitability change

    C2 — Market Cap (fmp_enterprise_valuations_ratings):
        #9   Equity market cap

    C3 — Equity Prices (norgate_eod_stock_prices):
        #7   Mom. 6m equity
        #10  Equity volatility
        #23  Distance-to-default (Shumway 2001)

Join path:
    bond RIC → yieldbook_indicatives.issuerTicker → fmp.symbol → financials
    bond RIC → yieldbook_indicatives.issuerTicker → datascope.Ticker → norgate.Symbol → equity prices

Output:
    IPCA_Replication/outputs/characteristics_group_c.parquet
    Index: (RIC, month_end)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import norm

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root   = Path(__file__).resolve().parent.parent
out_dir     = Path(__file__).resolve().parent / "outputs"
src_data    = repo_root / "src" / "data"

panel_path  = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
output_path = out_dir / "characteristics_group_c.parquet"

# ---------------------------------------------------------------------------
# 0. Load base panel (just RIC + month_end as scaffold)
# ---------------------------------------------------------------------------
print("Loading panel...")
panel = pd.read_parquet(panel_path, columns=["RIC", "month_end"])
panel["month_end"] = pd.to_datetime(panel["month_end"])
panel = panel.sort_values(["RIC", "month_end"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# 1. Build bond RIC → issuerTicker bridge from yieldbook_indicatives
# ---------------------------------------------------------------------------
print("Building bond→issuer ticker bridge...")
yb_indic = pd.read_parquet(src_data / "yieldbook_indicatives.parquet", engine="fastparquet")
yb_indic = yb_indic.reset_index()

# also grab assetClassSubDescription for profitability financials/non-financials split
bridge = yb_indic[["RIC", "issuerTicker", "indic.assetClassSubDescription"]].copy()
bridge = bridge.rename(columns={
    "issuerTicker": "symbol",
    "indic.assetClassSubDescription": "asset_class_sub",
})
bridge = bridge.drop_duplicates("RIC")

# is_financial flag: used for profitability formula (#20)
FINANCIAL_KEYWORDS = ["financial", "bank", "insurance", "reit", "finance"]
bridge["is_financial"] = bridge["asset_class_sub"].str.lower().str.contains(
    "|".join(FINANCIAL_KEYWORDS), na=False
)

print(f"  Bridge: {len(bridge)} bond RICs, "
      f"{bridge['symbol'].nunique()} unique issuer tickers")

# ---------------------------------------------------------------------------
# 2. Load & prepare financial statements
#    - Use filingDate as point-in-time availability date
#    - Forward-fill quarterly to monthly on panel dates
# ---------------------------------------------------------------------------
print("Loading financial statements...")
fmp_fs = pd.read_parquet(src_data / "fmp_hist_financial_statements.parquet",
                          engine="fastparquet")

fs_cols = [
    "symbol", "filingDate",
    "totalStockholdersEquity", "preferredStock",
    "shortTermDebt", "longTermDebt", "totalDebt",
    "minorityInterest", "cashAndCashEquivalents",
    "totalAssets", "revenue", "ebitda",
    "costOfRevenue", "costAndExpenses", "depreciationAndAmortization",
    "eps",
]
# income statement DA is in a suffixed column in this merged file
da_col = "depreciationAndAmortization_income_statement_bulk"
if da_col in fmp_fs.columns:
    fs_cols.append(da_col)

# keep only columns that exist
fs_cols = [c for c in fs_cols if c in fmp_fs.columns]
fmp_fs = fmp_fs[fs_cols].copy()

fmp_fs["filingDate"] = pd.to_datetime(fmp_fs["filingDate"], errors="coerce")
fmp_fs = fmp_fs.dropna(subset=["filingDate", "symbol"])
fmp_fs = fmp_fs.sort_values(["symbol", "filingDate"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# 2a. Market cap from fmp_enterprise_valuations_ratings
#     (needed for #4 book-to-price, #8 E/P, #16 market leverage)
# ---------------------------------------------------------------------------
print("Loading enterprise valuations...")
fmp_ev = pd.read_parquet(src_data / "fmp_enterprise_valuations_ratings.parquet",
                          engine="fastparquet")

ev_cols = ["symbol", "date", "marketCap", "stockPrice"]
ev_cols = [c for c in ev_cols if c in fmp_ev.columns]
fmp_ev = fmp_ev[ev_cols].copy()
fmp_ev["date"] = pd.to_datetime(fmp_ev["date"], errors="coerce")
fmp_ev = fmp_ev.dropna(subset=["date", "symbol"])
fmp_ev = fmp_ev.sort_values(["symbol", "date"]).reset_index(drop=True)

# Keep one row per symbol per month-end (take last observation in month)
fmp_ev["month_end"] = fmp_ev["date"] + pd.offsets.MonthEnd(0)
fmp_ev_monthly = (fmp_ev.sort_values("date")
                         .groupby(["symbol", "month_end"])
                         .last()
                         .reset_index()[["symbol", "month_end", "marketCap", "stockPrice"]])

# ---------------------------------------------------------------------------
# 2b. Forward-fill financial statements to monthly
#     Point-in-time: data available from filingDate onward
# ---------------------------------------------------------------------------
print("Forward-filling financials to monthly...")

# Get all unique month-ends in panel
all_months = pd.DataFrame({"month_end": sorted(panel["month_end"].unique())})

def ffill_to_monthly(fs_df, symbol_col="symbol", date_col="filingDate"):
    """
    For each symbol, forward-fill quarterly filings to monthly panel.
    Uses filingDate as the availability date (strict point-in-time).
    """
    results = []
    for sym, grp in fs_df.groupby(symbol_col):
        grp = grp.sort_values(date_col).copy()
        # snap filingDate to month_end
        grp["month_end"] = grp[date_col] + pd.offsets.MonthEnd(0)
        # keep last filing per month
        grp = grp.sort_values(date_col).groupby("month_end").last().reset_index()
        # merge onto full monthly grid and forward-fill
        merged = all_months.merge(grp, on="month_end", how="left")
        merged[symbol_col] = sym
        # forward fill all numeric columns
        num_cols = merged.select_dtypes(include=[np.number]).columns
        merged[num_cols] = merged[num_cols].fillna(method="ffill")
        results.append(merged)
    return pd.concat(results, ignore_index=True)

fs_monthly = ffill_to_monthly(fmp_fs)
print(f"  fs_monthly shape: {fs_monthly.shape}")

# ---------------------------------------------------------------------------
# 3. Merge financials onto panel via bond→issuer bridge
# ---------------------------------------------------------------------------
print("Merging financials onto panel...")

# panel → symbol
panel_sym = panel.merge(bridge[["RIC", "symbol", "is_financial"]], on="RIC", how="left")

# attach financials (forward-filled monthly)
panel_fs = panel_sym.merge(fs_monthly, on=["symbol", "month_end"], how="left")

# attach market cap / stock price (monthly)
panel_fs = panel_fs.merge(fmp_ev_monthly, on=["symbol", "month_end"], how="left")

print(f"  Panel after merge: {panel_fs.shape}")

# ---------------------------------------------------------------------------
# 4. Compute C1 characteristics
# ---------------------------------------------------------------------------
print("Computing C1 financial characteristics...")

eps = panel_fs.get("eps", np.nan)
sp  = panel_fs.get("stockPrice", np.nan)

# #4 Book-to-price
panel_fs["book_to_price"] = (
    (panel_fs["totalStockholdersEquity"].fillna(0) + panel_fs["preferredStock"].fillna(0))
    / panel_fs["marketCap"].replace(0, np.nan)
)

# #5 Debt-to-EBITDA
panel_fs["debt_to_ebitda"] = (
    panel_fs["totalDebt"] / panel_fs["ebitda"].replace(0, np.nan)
)

# #8 Earnings-to-price
panel_fs["earnings_to_price"] = (
    panel_fs["eps"] / panel_fs["stockPrice"].replace(0, np.nan)
)

# #9 Equity market cap (C2)
panel_fs["equity_market_cap"] = panel_fs["marketCap"]

# #11 Firm total debt
panel_fs["firm_total_debt"] = panel_fs["totalDebt"]

# #15 Book leverage
stD  = panel_fs["shortTermDebt"].fillna(0)
ltD  = panel_fs["longTermDebt"].fillna(0)
eq   = panel_fs["totalStockholdersEquity"].fillna(0)
pref = panel_fs["preferredStock"].fillna(0)
debt = stD + ltD
panel_fs["book_leverage"] = debt / (debt + eq - pref).replace(0, np.nan)

# #16 Market leverage
cash = panel_fs["cashAndCashEquivalents"].fillna(0)
mi   = panel_fs["minorityInterest"].fillna(0)
panel_fs["market_leverage"] = (
    (stD + ltD + mi + pref - cash) / panel_fs["marketCap"].replace(0, np.nan)
)

# #17 Turnover volatility: rolling 8-quarter std of revenue/totalAssets
#     Build quarterly series first then roll, then ffill to monthly
print("  Computing #17 Turnover volatility...")
tv_cols = ["symbol", "filingDate", "revenue", "totalAssets"]
tv_cols = [c for c in tv_cols if c in fmp_fs.columns]
tv_df = fmp_fs[tv_cols].copy()
tv_df["filingDate"] = pd.to_datetime(tv_df["filingDate"])
tv_df["turnover_ratio"] = tv_df["revenue"] / tv_df["totalAssets"].replace(0, np.nan)
tv_df = tv_df.sort_values(["symbol", "filingDate"])
tv_df["turnover_vol_q"] = (tv_df.groupby("symbol")["turnover_ratio"]
                                .transform(lambda x: x.rolling(8, min_periods=4).std()))
# ffill to monthly
tv_monthly = ffill_to_monthly(tv_df[["symbol", "filingDate", "turnover_vol_q"]].rename(
    columns={"turnover_vol_q": "turnover_volatility"}))
panel_fs = panel_fs.merge(tv_monthly[["symbol", "month_end", "turnover_volatility"]],
                           on=["symbol", "month_end"], how="left")

# #19 Operating leverage: (revenue - ebitda) / ebitda
panel_fs["operating_leverage"] = (
    (panel_fs["revenue"] - panel_fs["ebitda"]) / panel_fs["ebitda"].replace(0, np.nan)
)

# #20 Profitability
#   Non-financials: (revenue - costOfRevenue) / totalAssets
#   Financials:     (revenue - costAndExpenses + DA) / totalStockholdersEquity
da_col_use = (da_col if da_col in panel_fs.columns else "depreciationAndAmortization")

prof_nonfin = (
    (panel_fs["revenue"] - panel_fs["costOfRevenue"])
    / panel_fs["totalAssets"].replace(0, np.nan)
)
da_vals = panel_fs.get(da_col_use, pd.Series(np.nan, index=panel_fs.index))
prof_fin = (
    (panel_fs["revenue"] - panel_fs["costAndExpenses"] + da_vals.fillna(0))
    / panel_fs["totalStockholdersEquity"].replace(0, np.nan)
)
panel_fs["profitability"] = np.where(panel_fs["is_financial"], prof_fin, prof_nonfin)

# #21 Profitability change: 5-year (20-quarter) change
print("  Computing #21 Profitability change...")
prof_q_cols = ["symbol", "filingDate", "revenue", "costOfRevenue", "costAndExpenses",
               "totalAssets", "totalStockholdersEquity"]
if da_col in fmp_fs.columns:
    prof_q_cols.append(da_col)
prof_q_cols = [c for c in prof_q_cols if c in fmp_fs.columns]
prof_q = fmp_fs[prof_q_cols].copy()
prof_q["filingDate"] = pd.to_datetime(prof_q["filingDate"])

# need is_financial — join from bridge via symbol
bridge_sym = bridge[["symbol", "is_financial"]].drop_duplicates("symbol")
prof_q = prof_q.merge(bridge_sym, on="symbol", how="left")

da_q = prof_q.get(da_col, pd.Series(0, index=prof_q.index)).fillna(0)
prof_q["prof_nonfin"] = (
    (prof_q["revenue"] - prof_q["costOfRevenue"])
    / prof_q["totalAssets"].replace(0, np.nan)
)
prof_q["prof_fin"] = (
    (prof_q["revenue"] - prof_q["costAndExpenses"] + da_q)
    / prof_q["totalStockholdersEquity"].replace(0, np.nan)
)
prof_q["profitability_q"] = np.where(
    prof_q["is_financial"].fillna(False), prof_q["prof_fin"], prof_q["prof_nonfin"]
)
prof_q = prof_q.sort_values(["symbol", "filingDate"])
prof_q["prof_change_q"] = (prof_q.groupby("symbol")["profitability_q"]
                                  .transform(lambda x: x - x.shift(20)))
prof_change_monthly = ffill_to_monthly(
    prof_q[["symbol", "filingDate", "prof_change_q"]].rename(
        columns={"prof_change_q": "profitability_change"}))
panel_fs = panel_fs.merge(
    prof_change_monthly[["symbol", "month_end", "profitability_change"]],
    on=["symbol", "month_end"], how="left")

# ---------------------------------------------------------------------------
# 5. C3 — Equity price characteristics from Norgate
#    bridge: bond RIC → issuerTicker → datascope Ticker → norgate Symbol
# ---------------------------------------------------------------------------
print("Loading Norgate equity prices...")
norgate = pd.read_parquet(src_data / "norgate_eod_stock_prices.parquet",
                           engine="fastparquet")
norgate["Date"] = pd.to_datetime(norgate["Date"])

# Build Ticker→Symbol bridge from datascope (time-restricted)
print("Building datascope ticker bridge...")
ds = pd.read_parquet(src_data / "datascope_characteristic_eod.parquet",
                      engine="fastparquet")
ds["Trade Date"] = pd.to_datetime(ds["Trade Date"])

# For each RIC keep the most recent Ticker (handles ticker reuse)
ds_bridge = (ds.sort_values("Trade Date")
               .groupby("RIC")["Ticker"]
               .last()
               .reset_index()
               .rename(columns={"Ticker": "equity_ticker"}))

# bond RIC → equity ticker via datascope
# (datascope RIC = bond RIC; Ticker = equity ticker / norgate Symbol)
# We also have issuerTicker from yieldbook — use datascope as primary,
# fall back to issuerTicker
bond_equity = bridge[["RIC", "symbol"]].merge(ds_bridge, on="RIC", how="left")
# if datascope ticker missing, fall back to issuerTicker (=symbol)
bond_equity["equity_ticker"] = bond_equity["equity_ticker"].fillna(bond_equity["symbol"])

# Month-end equity prices from Norgate
norgate["month_end"] = norgate["Date"] + pd.offsets.MonthEnd(0)
eq_monthly = (norgate.sort_values("Date")
                      .groupby(["Symbol", "month_end"])["Close"]
                      .last()
                      .reset_index()
                      .rename(columns={"Symbol": "equity_ticker", "Close": "eq_close"}))

# Build wide price matrix: month_end × equity_ticker
print("Computing equity momentum and volatility...")
eq_wide = eq_monthly.pivot(index="month_end", columns="equity_ticker", values="eq_close")
eq_wide = eq_wide.sort_index()

# Log returns
log_ret = np.log(eq_wide / eq_wide.shift(1))

# #7 Mom. 6m equity: cumulative log return t-7 to t-2
log_ret_s2  = log_ret.shift(2)
mom6m_eq_wide = log_ret_s2.rolling(window=6, min_periods=6).sum()

# #10 Equity volatility: rolling std of monthly log returns, 12m window
eq_vol_wide = log_ret.rolling(window=12, min_periods=6).std()

# #23 Distance-to-default (Shumway 2001 simplified)
# D2D = (log(V/D) + (mu - 0.5*sigma^2)*T) / (sigma*sqrt(T))
# Approximate: V ≈ market equity value (use eq price as proxy scaled by shares)
# We use the standard simplified version:
#   sigma = equity return vol (annualised)
#   mu    = mean annual equity return (rolling 12m annualised)
#   V/D   = equity_market_cap / totalDebt  (market-to-debt ratio)
# T = 1 year
print("Computing #23 Distance-to-default...")
eq_ann_vol  = eq_vol_wide * np.sqrt(12)   # annualise monthly vol
eq_ann_ret  = log_ret.rolling(window=12, min_periods=6).mean() * 12  # annualise

# We'll compute D2D at the bond level after merging equity prices
# Stack equity characteristics to long format
mom6m_eq_long = (mom6m_eq_wide
                 .stack(dropna=False)
                 .rename("mom_6m_equity")
                 .reset_index()
                 .rename(columns={"equity_ticker": "equity_ticker"}))

eq_vol_long = (eq_ann_vol
               .stack(dropna=False)
               .rename("equity_vol_ann")
               .reset_index())

eq_ret_long = (eq_ann_ret
               .stack(dropna=False)
               .rename("equity_ret_ann")
               .reset_index())

eq_chars = (mom6m_eq_long
            .merge(eq_vol_long,  on=["month_end", "equity_ticker"], how="outer")
            .merge(eq_ret_long,  on=["month_end", "equity_ticker"], how="outer"))

# Attach equity ticker to panel
panel_eq = panel_fs.merge(bond_equity[["RIC", "equity_ticker"]], on="RIC", how="left")
panel_eq = panel_eq.merge(eq_chars, on=["month_end", "equity_ticker"], how="left")

# Distance-to-default
# V/D proxy: use marketCap / totalDebt
vd_ratio = panel_eq["marketCap"] / panel_eq["totalDebt"].replace(0, np.nan)
sigma    = panel_eq["equity_vol_ann"]
mu       = panel_eq["equity_ret_ann"]
T        = 1.0

panel_eq["distance_to_default"] = (
    (np.log(vd_ratio.clip(lower=1e-6)) + (mu - 0.5 * sigma**2) * T)
    / (sigma * np.sqrt(T))
)

# Rename equity vol for output
panel_eq = panel_eq.rename(columns={"equity_vol_ann": "equity_volatility"})

# ---------------------------------------------------------------------------
# 6. Final output
# ---------------------------------------------------------------------------
out_cols = [
    "RIC", "month_end",
    "book_to_price",       # #4
    "debt_to_ebitda",      # #5
    "mom_6m_equity",       # #7
    "earnings_to_price",   # #8
    "equity_market_cap",   # #9
    "equity_volatility",   # #10
    "firm_total_debt",     # #11
    "book_leverage",       # #15
    "market_leverage",     # #16
    "turnover_volatility", # #17
    "operating_leverage",  # #19
    "profitability",       # #20
    "profitability_change",# #21
    "distance_to_default", # #23
]

out = panel_eq[out_cols].copy()
out = out.set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
print("\n=== Group C output shape ===")
print(out.shape)
print("\n=== NaN counts ===")
print(out.isna().sum())
print("\n=== NaN % ===")
print((out.isna().mean() * 100).round(1))
print("\n=== Sample (first 5) ===")
print(out.head())
print("\n=== Describe ===")
print(out.describe())

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
output_path.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(output_path)
print(f"\nSaved to {output_path}")