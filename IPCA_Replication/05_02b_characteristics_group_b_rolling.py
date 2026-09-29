"""
Group B: Rolling Time-Series Bond Characteristics
Characteristics:
    #12  Mom. 6m                — cumulative CER t-7 to t-2 (skip t-1)
    #13  Mom. 6m industry       — #12 minus cross-sectional industry mean
    #14  Mom. 6m × ratings      — #12 × numeric rating (from Group A)
    #24  Bond skewness          — rolling skew of CER, 60m window, min 24 obs
    #25  Mom. 6m log(Spread)    — log(OAS_{t-7}) - log(OAS_{t-2})  [NOTE: sign = negative of log-spread momentum]
    #27  Bond volatility        — rolling std of CER, 24m window, min 12 obs
    #28  Value-at-risk          — 2nd-lowest CER in rolling 36m window, min 24 obs

Input:
    IPCA_Replication/outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet
    IPCA_Replication/outputs/characteristics_group_a.parquet   (for rating + industry)
    src/data/yieldbook_indicatives.parquet                      (for industryCode)

Output:
    IPCA_Replication/outputs/characteristics_group_b.parquet
    Index: (RIC, month_end)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import skew as scipy_skew

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root   = Path(__file__).resolve().parent.parent
out_dir     = Path(__file__).resolve().parent / "outputs"
src_data    = repo_root / "src" / "data"

panel_path  = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
group_a_path= out_dir / "characteristics_group_a.parquet"
indic_path  = src_data / "yieldbook_indicatives.parquet"
output_path = out_dir / "characteristics_group_b.parquet"

# ---------------------------------------------------------------------------
# Load base panel  — need: RIC, month_end, credit_excess_return, OAS
# ---------------------------------------------------------------------------
print("Loading panel...")
panel = pd.read_parquet(panel_path, columns=["RIC", "month_end", "credit_excess_return", "OAS"])
panel["month_end"] = pd.to_datetime(panel["month_end"])
panel = panel.sort_values(["RIC", "month_end"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# Load rating from Group A  (needed for #14)
# ---------------------------------------------------------------------------
print("Loading Group A for rating...")
group_a = pd.read_parquet(group_a_path, columns=["rating"])
group_a = group_a.reset_index()   # brings RIC, month_end back as columns

# ---------------------------------------------------------------------------
# Load industry code from yieldbook_indicatives  (needed for #13)
# ---------------------------------------------------------------------------
print("Loading indicatives for industry code...")
yb_indic = pd.read_parquet(indic_path, engine="fastparquet")
yb_indic = yb_indic.reset_index()   # RIC was index

# keep only the columns we need; handle possible column name variants
industry_col = None
for candidate in ["indic.industryCode", "industryCode", "indic_industryCode"]:
    if candidate in yb_indic.columns:
        industry_col = candidate
        break

if industry_col is None:
    print(f"  ⚠ Could not find industry code column. Available: {yb_indic.columns.tolist()}")
    yb_indic["industry_code"] = np.nan
else:
    yb_indic = yb_indic.rename(columns={industry_col: "industry_code"})

# yieldbook RIC index is None in this file — bridge via CUSIP instead.
# Panel RICs are CUSIP + '=' (Refinitiv format), e.g. '205887CE0='.
indic_small = yb_indic[["cusip", "industry_code"]].drop_duplicates("cusip")

# ---------------------------------------------------------------------------
# Merge all onto panel
# ---------------------------------------------------------------------------
df = panel.merge(group_a[["RIC", "month_end", "rating"]], on=["RIC", "month_end"], how="left")
df["_cusip"] = df["RIC"].str.rstrip("=")
df = df.merge(indic_small, left_on="_cusip", right_on="cusip", how="left")
df = df.drop(columns=["_cusip", "cusip"])

# ---------------------------------------------------------------------------
# Helper: rolling function applied per-RIC using groupby + apply
# We pivot to wide (bonds × time), compute rolling, then melt back.
# This is faster than groupby.apply for large panels.
# ---------------------------------------------------------------------------

def _pivot_rolling(series: pd.Series, index: pd.Index, columns: pd.Index,
                   func, window: int, min_periods: int) -> pd.DataFrame:
    """
    Pivot a flat Series (indexed by integer loc) to wide,
    apply a rolling function, return a flat result aligned to original index.
    series   : the values column (already aligned to df)
    index    : month_end values
    columns  : RIC values
    """
    wide = (pd.DataFrame({"val": series.values,
                           "month_end": index.values,
                           "RIC": columns.values})
              .pivot(index="month_end", columns="RIC", values="val")
              .sort_index())
    rolled = wide.rolling(window=window, min_periods=min_periods).apply(func, raw=True)
    long = (rolled.reset_index()
                  .melt(id_vars="month_end", value_name="result")
                  .sort_values(["RIC", "month_end"])
                  .reset_index(drop=True))
    return long

# ---------------------------------------------------------------------------
# #12  Mom. 6m: cumulative CER from t-7 to t-2
#   = sum of CER over 6 months, skipping t-1 (the most recent month)
#   Implemented as: for each row t, sum CER[t-7 .. t-2] = 6 observations
#   We shift CER by 1 first, then do a 6-period rolling sum.
# ---------------------------------------------------------------------------
print("Computing #12 Mom. 6m...")

# sort and build shifted series
df = df.sort_values(["RIC", "month_end"])
# shift(1) within each RIC: at row t, shifted value = CER at t-1
# We need sum from t-7 to t-2, i.e. months with lag 2..7
# Trick: shift the series by 1 (so position t has CER_{t-1}),
# then a 6-period rolling sum gives sum of CER_{t-1}+...+CER_{t-6} — that's lags 1..6
# We want lags 2..7, so shift by 2 first, then 6-period rolling sum.
cer = df.set_index(["RIC", "month_end"])["credit_excess_return"].unstack("RIC")  # wide: time × RIC
cer_shifted2 = cer.shift(2)          # at time t, value = CER_{t-2}
mom6m_wide   = cer_shifted2.rolling(window=6, min_periods=6).sum()  # sum CER_{t-2}...CER_{t-7}
mom6m = mom6m_wide.stack().rename("mom_6m").reset_index()
mom6m.columns = ["month_end", "RIC", "mom_6m"]

df = df.merge(mom6m, on=["RIC", "month_end"], how="left")

# ---------------------------------------------------------------------------
# #13  Mom. 6m industry: #12 minus cross-sectional industry mean at each month_end
# ---------------------------------------------------------------------------
print("Computing #13 Mom. 6m industry...")
df["mom_6m_industry_mean"] = df.groupby(["month_end", "industry_code"])["mom_6m"].transform("mean")
df["mom_6m_industry"] = df["mom_6m"] - df["mom_6m_industry_mean"]

# ---------------------------------------------------------------------------
# #14  Mom. 6m × ratings: element-wise product
# ---------------------------------------------------------------------------
print("Computing #14 Mom. 6m × ratings...")
df["mom_6m_x_rating"] = df["mom_6m"] * df["rating"]

# ---------------------------------------------------------------------------
# #25  Mom. 6m log(Spread): log(OAS_{t-7}) - log(OAS_{t-2})
#   Note: the paper defines this as negative of log-spread momentum
#   i.e. spread FELL → positive value → good signal
# ---------------------------------------------------------------------------
print("Computing #25 Mom. 6m log(Spread)...")
oas = df.set_index(["RIC", "month_end"])["OAS"].unstack("RIC")

# Only take log of positive OAS values; set non-positive to NaN
log_oas = np.log(oas.where(oas > 0))

log_oas_t2 = log_oas.shift(2)   # log(OAS_{t-2})
log_oas_t7 = log_oas.shift(7)   # log(OAS_{t-7})

mom6m_log_spread_wide = log_oas_t7 - log_oas_t2   # positive when spread fell
mom6m_log_spread = (mom6m_log_spread_wide
                    .stack()
                    .rename("mom_6m_log_spread")
                    .reset_index())
mom6m_log_spread.columns = ["month_end", "RIC", "mom_6m_log_spread"]

df = df.merge(mom6m_log_spread, on=["RIC", "month_end"], how="left")

# ---------------------------------------------------------------------------
# #24  Bond skewness: rolling skewness of CER, 60m window, min 24 obs
# ---------------------------------------------------------------------------
print("Computing #24 Bond skewness (rolling 60m)...")

def _skew(x):
    if len(x) < 3:
        return np.nan
    return scipy_skew(x, bias=True)

skew_wide = cer.shift(1).rolling(window=60, min_periods=24).apply(_skew, raw=True)
bond_skew  = (skew_wide.stack()
              .rename("bond_skewness")
              .reset_index())
bond_skew.columns = ["month_end", "RIC", "bond_skewness"]

df = df.merge(bond_skew, on=["RIC", "month_end"], how="left")

# ---------------------------------------------------------------------------
# #27  Bond volatility: rolling std of CER, 24m window, min 12 obs
# ---------------------------------------------------------------------------
print("Computing #27 Bond volatility (rolling 24m)...")
vol_wide = cer.shift(1).rolling(window=24, min_periods=12).std()
bond_vol  = (vol_wide.stack()
             .rename("bond_volatility")
             .reset_index())
bond_vol.columns = ["month_end", "RIC", "bond_volatility"]

df = df.merge(bond_vol, on=["RIC", "month_end"], how="left")

# ---------------------------------------------------------------------------
# #28  Value-at-risk: 2nd-lowest CER over rolling 36m window, min 24 obs
# ---------------------------------------------------------------------------
print("Computing #28 Value-at-Risk (rolling 36m, 2nd lowest)...")

def _var(x):
    valid = x[~np.isnan(x)]
    if len(valid) < 24:
        return np.nan
    return np.sort(valid)[1]   # 2nd-lowest (index 1)

var_wide = cer.shift(1).rolling(window=36, min_periods=24).apply(_var, raw=True)
bond_var  = (var_wide.stack()
             .rename("value_at_risk")
             .reset_index())
bond_var.columns = ["month_end", "RIC", "value_at_risk"]

df = df.merge(bond_var, on=["RIC", "month_end"], how="left")

# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------
out_cols = ["RIC", "month_end",
            "mom_6m",           # #12
            "mom_6m_industry",  # #13
            "mom_6m_x_rating",  # #14
            "bond_skewness",    # #24
            "mom_6m_log_spread",# #25
            "bond_volatility",  # #27
            "value_at_risk",    # #28
           ]

out = df[out_cols].copy()
out = out.set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
print("\n=== Group B output shape ===")
print(out.shape)
print("\n=== NaN counts ===")
print(out.isna().sum())
print(f"\n=== NaN % ===")
print((out.isna().mean() * 100).round(2))
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