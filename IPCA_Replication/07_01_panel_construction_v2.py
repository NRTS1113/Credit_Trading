"""
07_01  Panel Construction — 8-Characteristic Replication (2004+)
=================================================================
Mirrors 06_01 but restricts characteristics to the 8 that have full
coverage from 2004 onwards, allowing a longer sample that spans the
2008 financial crisis.

Characteristics used (L=8 + constant):
    bond_age, coupon, face_value, duration, spread, rating,
    mom_6m_equity, equity_volatility

Sample: 2004-07 → 2025-09  (~253 months vs. 166 in v1)
OOS burn-in: 36 months → first OOS prediction ≈ 2007-07

Steps
-----
1–6.  Identical to 06_01 (load, merge, filter, DtS-scale, rank-std)
7.    Imputation (same two-pass approach)
8.    MIN_BONDS filter (floor = 30, lower than v1 to preserve early months)
9.    Save to outputs_v2/

Output
------
    IPCA_Replication/outputs_v2/ipca_panel_input_v2.parquet
    IPCA_Replication/outputs_v2/ipca_monthly_counts_v2.parquet
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
out_dir_v1  = Path(__file__).resolve().parent / "outputs"
out_dir_v2  = Path(__file__).resolve().parent / "outputs_v2"
out_dir_v2.mkdir(exist_ok=True)

panel_path  = out_dir_v1 / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
chars_path  = out_dir_v1 / "characteristics_all.parquet"
output_path = out_dir_v2 / "ipca_panel_input_v2.parquet"

# ---------------------------------------------------------------------------
# Characteristic columns — 8 with full 2004+ coverage
# ---------------------------------------------------------------------------
CHAR_COLS = [
    "bond_age",        # Group A — static bond attributes
    "coupon",
    "face_value",
    "duration",
    "spread",
    "rating",
    "mom_6m_equity",   # Group C — equity data (Norgate from 2004)
    "equity_volatility",
]

print(f"Characteristics : {len(CHAR_COLS)} + constant  (L={len(CHAR_COLS)+1})")
print(f"  {CHAR_COLS}")

# ---------------------------------------------------------------------------
# 1. Load base panel
# ---------------------------------------------------------------------------
print("\nLoading base panel...")
panel = pd.read_parquet(
    panel_path,
    columns=["RIC", "month_end", "credit_excess_return", "OAS", "Duration"]
)
panel["month_end"] = pd.to_datetime(panel["month_end"])
panel = panel.sort_values(["RIC", "month_end"]).reset_index(drop=True)
print(f"  Raw panel : {panel.shape[0]:,} rows, {panel['RIC'].nunique():,} RICs")

# ---------------------------------------------------------------------------
# 2. Load characteristics (only the 8 we need + constant)
# ---------------------------------------------------------------------------
print("Loading characteristics...")
chars = pd.read_parquet(chars_path).reset_index()
chars["month_end"] = pd.to_datetime(chars["month_end"])
cols_to_load = ["RIC", "month_end"] + CHAR_COLS + ["constant"]
cols_to_load = [c for c in cols_to_load if c in chars.columns]
chars = chars[cols_to_load]

# ---------------------------------------------------------------------------
# 3. Merge
# ---------------------------------------------------------------------------
df = panel.merge(chars, on=["RIC", "month_end"], how="inner")
print(f"  After merge : {df.shape[0]:,} rows")

# ---------------------------------------------------------------------------
# 4. Bond-level filters  [KPP Section 3.2]
# ---------------------------------------------------------------------------
print("Applying bond filters...")
n_before = len(df)
df = df[(df["OAS"] >= 50) & (df["OAS"] <= 2000)]
df = df[df["Duration"] >= 0.25]
print(f"  Dropped {n_before - len(df):,} rows  →  {len(df):,} remaining")

# ---------------------------------------------------------------------------
# 5. DtS scaling  [KPP eq. 10]
# ---------------------------------------------------------------------------
print("Computing DtS scaling...")
DTS_BAR       = 0.25
df["DtS"]     = df["Duration"] * (df["OAS"] / 10_000)
df["ret_raw"] = df["credit_excess_return"]
df["ret_scaled"] = df["ret_raw"] / df["DtS"].clip(lower=DTS_BAR)

print(f"  DtS — mean {df['DtS'].mean():.3f}, median {df['DtS'].median():.3f}, "
      f"min {df['DtS'].min():.4f}, max {df['DtS'].max():.3f}")
print(f"  Bonds with DtS < DtS_bar: {(df['DtS'] < DTS_BAR).mean()*100:.1f}%")

# ---------------------------------------------------------------------------
# 6. Cross-sectional rank-standardise  [KPP Section 3.2]
# ---------------------------------------------------------------------------
print("Rank-standardising characteristics...")

def _rank_std(s: pd.Series) -> pd.Series:
    n = s.notna().sum()
    if n <= 1:
        return s * 0.0
    r = s.rank(method="average", na_option="keep")
    return (r - 1) / (n - 1) - 0.5

for col in CHAR_COLS:
    if col not in df.columns:
        print(f"  ⚠  {col} missing — zero-filled")
        df[col] = np.nan
        continue
    df[col] = df.groupby("month_end")[col].transform(_rank_std)

print("  ✓  Done")

# ---------------------------------------------------------------------------
# 7. Missing value imputation — two-pass (cross-sectional then global)
# ---------------------------------------------------------------------------
print("Imputing missing values...")

df["n_imputed"]  = df[CHAR_COLS].isna().sum(axis=1)
n_total_missing  = df[CHAR_COLS].isna().sum().sum()

for col in CHAR_COLS:
    df[col] = df.groupby("month_end")[col].transform(
        lambda x: x.fillna(x.median())
    )

n_remaining = df[CHAR_COLS].isna().sum().sum()
print(f"  Filled (cross-sectional) : {n_total_missing - n_remaining:,}")
print(f"  Still NaN after CS fill  : {n_remaining:,}")

if n_remaining > 0:
    print("  Running global median fill...")
    df[CHAR_COLS] = df[CHAR_COLS].fillna(df[CHAR_COLS].median())
    n_remaining2  = df[CHAR_COLS].isna().sum().sum()
    print(f"  Still NaN after global fill: {n_remaining2:,}")

# ---------------------------------------------------------------------------
# 8. Final assembly
# ---------------------------------------------------------------------------
keep = (["RIC", "month_end", "ret_scaled", "ret_raw", "DtS", "n_imputed"]
        + CHAR_COLS + ["constant"])
keep = [c for c in keep if c in df.columns]
out  = df[keep].set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# 9. MIN_BONDS filter
#    Lower floor (30) than v1 (50) to preserve early 2004-2007 months
#    where the universe is smaller but still meaningful for IPCA.
# ---------------------------------------------------------------------------
MIN_BONDS_PER_MONTH = 30

monthly_counts = (out.reset_index()
                     .groupby("month_end")["RIC"]
                     .count()
                     .rename("n_bonds"))

thin_months = monthly_counts[monthly_counts < MIN_BONDS_PER_MONTH].index
if len(thin_months) > 0:
    print(f"\nDropping {len(thin_months)} month(s) with < {MIN_BONDS_PER_MONTH} bonds:")
    for m in thin_months:
        print(f"  {m.date()}  ({monthly_counts[m]} bonds)")
    out            = out[~out.index.get_level_values("month_end").isin(thin_months)]
    monthly_counts = monthly_counts[monthly_counts >= MIN_BONDS_PER_MONTH]

monthly_counts.to_frame().to_parquet(out_dir_v2 / "ipca_monthly_counts_v2.parquet")

# ---------------------------------------------------------------------------
# 10. Diagnostics
# ---------------------------------------------------------------------------
dates = out.index.get_level_values("month_end")

print("\n" + "=" * 60)
print("PANEL v2 DIAGNOSTICS  (8 characteristics, 2004+)")
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
for lo, hi, label in [(0, 0, "0 imputed"), (1, 3, "1–3 imputed"),
                       (4, 6, "4–6 imputed"), (7, 8, ">6 imputed")]:
    n = ((imp >= lo) & (imp <= hi)).sum()
    print(f"  {label:<15}: {n:,}  ({n/len(out)*100:.1f}%)")

print("\n--- Characteristic ranges (all should be in [-0.5, 0.5]) ---")
ranges = out[CHAR_COLS].agg(["min", "max"]).round(4).T
bad = ranges[(ranges["min"] < -0.51) | (ranges["max"] > 0.51)]
if len(bad):
    print(f"  ⚠  Out-of-range: {bad.index.tolist()}")
else:
    print("  ✓  All in [-0.5, 0.5]")

print(f"\n--- Coverage check (2004-2007 early period) ---")
early = out[dates < "2008-01-01"]
if len(early) > 0:
    early_months = early.index.get_level_values("month_end")
    print(f"  Months in 2004-2007 : {early_months.nunique()}")
    print(f"  Avg bonds/month     : {early_months.value_counts().mean():.0f}")
    print(f"  NaN rate (any char) : {(early[CHAR_COLS].isna().any(axis=1)).mean()*100:.1f}%")

# ---------------------------------------------------------------------------
# 11. Save
# ---------------------------------------------------------------------------
out.to_parquet(output_path)
print(f"\n✓ Saved to {output_path}")
print(f"  Columns ({len(out.columns)}): {list(out.columns)}")
print(f"\n  v1 comparison: 28 chars, 166 months, starts 2011-12")
print(f"  v2 this file : {len(CHAR_COLS)} chars, "
      f"{dates.nunique()} months, starts {dates.min().date()}")