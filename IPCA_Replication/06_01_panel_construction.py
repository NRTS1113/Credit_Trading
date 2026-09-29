"""
06_01  Panel Construction for IPCA
====================================
Takes the raw characteristics panel and bond returns, applies all pre-processing
steps described in Kelly, Palhares & Pruitt (2021) Section 3, and outputs a
clean (RIC, month_end) panel ready for IPCA estimation.

Steps
-----
1. Load characteristics_all + base panel (returns + OAS + Duration)
2. Compute DtS (Duration × Spread) and scale returns          [KPP eq. 10]
3. Apply bond-level filters (spread, duration)                 [KPP Section 3.2]
4. Cross-sectional rank-standardise each characteristic        [KPP Section 3.2]
5. Handle missing characteristics via cross-sectional median   [standard practice]
6. Record valid observation counts per month

Input
-----
    IPCA_Replication/outputs/characteristics_all.parquet
    IPCA_Replication/outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet

Output
------
    IPCA_Replication/outputs/ipca_panel_input.parquet
    Index : (RIC, month_end)
    Columns:
        ret_scaled        — DtS-scaled credit excess return  (the y in IPCA)
        ret_raw           — unscaled credit excess return    (for reference)
        DtS               — Duration × Spread (decimal)
        n_imputed         — number of characteristics filled by median
        <28 char cols>    — rank-standardised to [-0.5, 0.5], NaN filled
        constant          — 1.0

    IPCA_Replication/outputs/ipca_monthly_counts.parquet
        Index : month_end
        Column: n_bonds
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root   = Path(__file__).resolve().parent.parent
out_dir     = Path(__file__).resolve().parent / "outputs"

panel_path  = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
chars_path  = out_dir / "characteristics_all.parquet"
output_path = out_dir / "ipca_panel_input.parquet"

# ---------------------------------------------------------------------------
# Characteristic columns (28; constant handled separately)
# ---------------------------------------------------------------------------
CHAR_COLS = [
    "bond_age", "coupon", "face_value", "duration", "spread", "rating",
    "mom_6m", "mom_6m_industry", "mom_6m_x_rating", "bond_skewness",
    "mom_6m_log_spread", "bond_volatility", "value_at_risk",
    "book_to_price", "debt_to_ebitda", "mom_6m_equity", "earnings_to_price",
    "equity_market_cap", "equity_volatility", "firm_total_debt",
    "book_leverage", "market_leverage", "turnover_volatility",
    "operating_leverage", "profitability", "profitability_change",
    "distance_to_default", "spread_to_d2d",
]

# ---------------------------------------------------------------------------
# 1. Load base panel
# ---------------------------------------------------------------------------
print("Loading base panel...")
panel = pd.read_parquet(
    panel_path,
    columns=["RIC", "month_end", "credit_excess_return", "OAS", "Duration"]
)
panel["month_end"] = pd.to_datetime(panel["month_end"])
panel = panel.sort_values(["RIC", "month_end"]).reset_index(drop=True)
print(f"  Raw panel : {panel.shape[0]:,} rows, {panel['RIC'].nunique():,} RICs")

# ---------------------------------------------------------------------------
# 2. Load characteristics
# ---------------------------------------------------------------------------
print("Loading characteristics...")
chars = pd.read_parquet(chars_path).reset_index()
chars["month_end"] = pd.to_datetime(chars["month_end"])

# ---------------------------------------------------------------------------
# 3. Merge
# ---------------------------------------------------------------------------
df = panel.merge(chars, on=["RIC", "month_end"], how="inner")
print(f"  After merge : {df.shape[0]:,} rows")

# ---------------------------------------------------------------------------
# 4. Bond-level filters  [KPP Section 3.2]
#    - OAS between 50 bps and 2000 bps
#    - Duration >= 0.25 years
# ---------------------------------------------------------------------------
print("Applying bond filters...")
n_before = len(df)
df = df[(df["OAS"] >= 50) & (df["OAS"] <= 2000)]
df = df[df["Duration"] >= 0.25]
print(f"  Dropped {n_before - len(df):,} rows  →  {len(df):,} remaining")

# IPCA requires z_{i,t} to predict ret_{i,t+1}
# Shift return forward by one month so the row at (RIC, month_end) contains the characteristics at month_end and the return in the following month.
df = df.sort_values(["RIC", "month_end"])
df["credit_excess_return"] = df.groupby("RIC")["credit_excess_return"].shift(-1)
df = df.dropna(subset=["credit_excess_return"])
print(f"  After shifting returns: {len(df):,} rows")

# ---------------------------------------------------------------------------
# 5. DtS scaling  [KPP eq. 10]
#
#    DtS_i,t = Duration_i,t × (OAS_i,t / 10,000)   [OAS in bps → decimal]
#
#    ret_scaled = ret_raw / max(DtS, DtS_bar)
#    DtS_bar = 0.25  (KPP: "set at 0.25"; ≈ 40th percentile of DtS)
#    Bonds with DtS < DtS_bar are essentially unscaled (all divided by same
#    constant), so low-vol bonds are not artificially upweighted.
# ---------------------------------------------------------------------------
print("Computing DtS scaling...")
DTS_BAR = 0.25
df["DtS"]       = df["Duration"] * (df["OAS"] / 10_000)
df["ret_raw"]   = df["credit_excess_return"]
df["ret_scaled"] = df["ret_raw"] / df["DtS"].clip(lower=DTS_BAR)

print(f"  DtS — mean {df['DtS'].mean():.3f}, median {df['DtS'].median():.3f}, "
      f"min {df['DtS'].min():.4f}, max {df['DtS'].max():.3f}")
print(f"  Bonds with DtS < DtS_bar (unscaled): {(df['DtS'] < DTS_BAR).mean()*100:.1f}%")

# ---------------------------------------------------------------------------
# 6. Cross-sectional rank-standardise  [KPP Section 3.2]
#
#    For each month t and characteristic l:
#      ranked  = rank(z_{i,l,t})  among all bonds with non-NaN z
#      z_std   = (ranked - 1) / (N - 1) - 0.5   →  lives in [-0.5, 0.5]
#
#    The constant column (=1) is NOT standardised.
#    NaN values stay NaN here; they are filled in step 7.
# ---------------------------------------------------------------------------
print("Rank-standardising characteristics (cross-sectional)...")

def _rank_std(s: pd.Series) -> pd.Series:
    """Map a cross-section to [-0.5, 0.5] using fractional ranks."""
    n = s.notna().sum()
    if n <= 1:
        return s * 0.0          # single/no obs → zero
    r = s.rank(method="average", na_option="keep")
    return (r - 1) / (n - 1) - 0.5

for col in CHAR_COLS:
    if col not in df.columns:
        print(f"  ⚠  {col} missing — will be zero-filled")
        df[col] = np.nan
        continue
    df[col] = df.groupby("month_end")[col].transform(_rank_std)

print("  ✓  Done")

# ---------------------------------------------------------------------------
# 7. Missing value imputation — cross-sectional median
#
#    After rank-standardisation the median is ≈ 0 for most characteristics.
#    Filling with the cross-sectional median is therefore equivalent to
#    assigning the "average" bond exposure, which is the least informative
#    but least distorting imputation for a rank-based instrument.
#
#    We record n_imputed per row so downstream code can filter on it.
# ---------------------------------------------------------------------------
print("Imputing missing values (cross-sectional median)...")

df["n_imputed"] = df[CHAR_COLS].isna().sum(axis=1)
n_total_missing = df[CHAR_COLS].isna().sum().sum()

for col in CHAR_COLS:
    df[col] = df.groupby("month_end")[col].transform(
        lambda x: x.fillna(x.median())
    )

n_remaining = df[CHAR_COLS].isna().sum().sum()
print(f"  Filled  : {n_total_missing:,} values")
print(f"  Still NaN after cross-sectional fill: {n_remaining:,}")

# Second pass: global median fill for columns that are entirely NaN in some
# months (e.g. early period where a whole characteristic group is missing).
# Global median of rank-standardised values is ≈ 0, same economic meaning.
if n_remaining > 0:
    print("  Running second-pass global median fill...")
    global_medians = df[CHAR_COLS].median()
    df[CHAR_COLS] = df[CHAR_COLS].fillna(global_medians)
    n_remaining2 = df[CHAR_COLS].isna().sum().sum()
    print(f"  Still NaN after global fill: {n_remaining2:,}")

    # Third pass: zero-fill for entirely-missing characteristics (e.g. a
    # characteristic that is 100% NaN has no valid global median to fill with).
    # Zero is the neutral value in [-0.5, 0.5] rank-standardised space.
    if n_remaining2 > 0:
        all_nan_cols = [c for c in CHAR_COLS if df[c].isna().all()]
        if all_nan_cols:
            print(f"  Zero-filling entirely-missing characteristics: {all_nan_cols}")
        df[CHAR_COLS] = df[CHAR_COLS].fillna(0)

# ---------------------------------------------------------------------------
# 8. Final assembly
# ---------------------------------------------------------------------------
keep = (["RIC", "month_end", "ret_scaled", "ret_raw", "DtS", "n_imputed"]
        + CHAR_COLS + ["constant"])
keep = [c for c in keep if c in df.columns]

out = df[keep].set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# 9. Monthly observation counts + MIN_BONDS filter
#
#    IPCA cross-section regression requires enough bonds per month to
#    identify K factors.  Months with fewer than MIN_BONDS bonds are
#    dropped — they are typically early-sample months with sparse data.
#    KPP use a sample starting Dec 1999 with ~300+ bonds/month throughout;
#    we apply a conservative floor of 50.
# ---------------------------------------------------------------------------
MIN_BONDS_PER_MONTH = 50

monthly_counts = (out.reset_index()
                     .groupby("month_end")["RIC"]
                     .count()
                     .rename("n_bonds"))

thin_months = monthly_counts[monthly_counts < MIN_BONDS_PER_MONTH].index
if len(thin_months) > 0:
    print(f"\nDropping {len(thin_months)} month(s) with < {MIN_BONDS_PER_MONTH} bonds:")
    for m in thin_months:
        print(f"  {m.date()}  ({monthly_counts[m]} bonds)")
    out = out[~out.index.get_level_values("month_end").isin(thin_months)]
    monthly_counts = monthly_counts[monthly_counts >= MIN_BONDS_PER_MONTH]

monthly_counts.to_frame().to_parquet(out_dir / "ipca_monthly_counts.parquet")

# ---------------------------------------------------------------------------
# 10. Diagnostics
# ---------------------------------------------------------------------------
dates = out.index.get_level_values("month_end")

print("\n" + "=" * 60)
print("IPCA PANEL INPUT — DIAGNOSTICS")
print("=" * 60)
print(f"Shape           : {out.shape}")
print(f"Unique RICs     : {out.index.get_level_values('RIC').nunique():,}")
print(f"Date range      : {dates.min().date()} → {dates.max().date()}")
print(f"Unique months   : {dates.nunique()}")
print(f"Avg bonds/month : {monthly_counts.mean():.0f}")
print(f"Min bonds/month : {monthly_counts.min()}  ({monthly_counts.idxmin().date()})")
print(f"Max bonds/month : {monthly_counts.max()}  ({monthly_counts.idxmax().date()})")

print("\n--- ret_scaled statistics ---")
print(out["ret_scaled"].describe().round(5))

print("\n--- Imputation summary ---")
imp = out["n_imputed"]
for lo, hi, label in [(0, 0, "0 imputed"),
                       (1, 5, "1–5 imputed"),
                       (6, 10, "6–10 imputed"),
                       (11, 28, ">10 imputed")]:
    n = ((imp >= lo) & (imp <= hi)).sum()
    print(f"  {label:<15}: {n:,}  ({n/len(out)*100:.1f}%)")

print("\n--- Characteristic ranges (all should be in [-0.5, 0.5]) ---")
ranges = out[CHAR_COLS].agg(["min", "max"]).round(4).T
bad = ranges[(ranges["min"] < -0.51) | (ranges["max"] > 0.51)]
if len(bad):
    print(f"  ⚠  Out-of-range: {bad.index.tolist()}")
else:
    print("  ✓  All in [-0.5, 0.5]")

# ---------------------------------------------------------------------------
# 11. Save
# ---------------------------------------------------------------------------
output_path.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(output_path)
print(f"\n✓ Saved to {output_path}")
print(f"  Columns ({len(out.columns)}): {list(out.columns)}")