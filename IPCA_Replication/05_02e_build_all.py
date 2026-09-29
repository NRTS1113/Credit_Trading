"""
Build All Characteristics — Orchestrator
=========================================
Merges Groups A, B, C, D into a single panel.

NOTE: #29 VIX beta is excluded pending data availability.

Final output columns (29 total = 28 characteristics + constant):
    Group A (6):  bond_age, coupon, face_value, duration, spread, rating
    Group B (7):  mom_6m, mom_6m_industry, mom_6m_x_rating, bond_skewness,
                  mom_6m_log_spread, bond_volatility, value_at_risk
    Group C (14): book_to_price, debt_to_ebitda, mom_6m_equity, earnings_to_price,
                  equity_market_cap, equity_volatility, firm_total_debt,
                  book_leverage, market_leverage, turnover_volatility,
                  operating_leverage, profitability, profitability_change,
                  distance_to_default
    Group D (1):  spread_to_d2d
    Constant (1): always 1.0  (maps to equal-weight bond market factor in IPCA)

Input:
    IPCA_Replication/outputs/characteristics_group_a.parquet
    IPCA_Replication/outputs/characteristics_group_b.parquet
    IPCA_Replication/outputs/characteristics_group_c.parquet
    IPCA_Replication/outputs/characteristics_group_d.parquet
    IPCA_Replication/outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet

Output:
    IPCA_Replication/outputs/characteristics_all.parquet
    Index: (RIC, month_end)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root  = Path(__file__).resolve().parent.parent
out_dir    = Path(__file__).resolve().parent / "outputs"

panel_path  = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
output_path = out_dir / "characteristics_all.parquet"

group_paths = {
    "A": out_dir / "characteristics_group_a.parquet",
    "B": out_dir / "characteristics_group_b.parquet",
    "C": out_dir / "characteristics_group_c.parquet",
    "D": out_dir / "characteristics_group_d.parquet",
}

# ---------------------------------------------------------------------------
# 1. Load base panel (scaffold)
# ---------------------------------------------------------------------------
print("Loading base panel...")
panel = pd.read_parquet(panel_path, columns=["RIC", "month_end"])
panel["month_end"] = pd.to_datetime(panel["month_end"])
panel = panel.sort_values(["RIC", "month_end"]).reset_index(drop=True)
print(f"  Panel: {panel.shape[0]:,} rows, {panel['RIC'].nunique():,} unique RICs")

# ---------------------------------------------------------------------------
# 2. Merge Groups A–D
# ---------------------------------------------------------------------------
print("\nMerging characteristic groups...")
df = panel.copy()

for name, path in group_paths.items():
    if not path.exists():
        print(f"  ⚠  Group {name} not found at {path} — skipping")
        continue
    grp = pd.read_parquet(path).reset_index()
    grp["month_end"] = pd.to_datetime(grp["month_end"])
    n_chars = grp.shape[1] - 2   # subtract RIC + month_end
    df = df.merge(grp, on=["RIC", "month_end"], how="left")
    print(f"  ✓  Group {name}: {n_chars} characteristic(s) merged")

print(f"\n  Combined shape: {df.shape}")

# ---------------------------------------------------------------------------
# 3. Add constant column
# ---------------------------------------------------------------------------
df["constant"] = 1.0

# ---------------------------------------------------------------------------
# 4. Final column order (mirrors Table A.I of KPP 2021, excluding #29 VIX beta)
# ---------------------------------------------------------------------------
CHAR_COLS = [
    # Group A — static bond
    "bond_age",             # #1
    "coupon",               # #2
    "face_value",           # #3
    "duration",             # #6
    "spread",               # #18
    "rating",               # #22
    # Group B — rolling bond time-series
    "mom_6m",               # #12
    "mom_6m_industry",      # #13
    "mom_6m_x_rating",      # #14
    "bond_skewness",        # #24
    "mom_6m_log_spread",    # #25
    "bond_volatility",      # #27
    "value_at_risk",        # #28
    # Group C — firm-level
    "book_to_price",        # #4
    "debt_to_ebitda",       # #5
    "mom_6m_equity",        # #7
    "earnings_to_price",    # #8
    "equity_market_cap",    # #9
    "equity_volatility",    # #10
    "firm_total_debt",      # #11
    "book_leverage",        # #15
    "market_leverage",      # #16
    "turnover_volatility",  # #17
    "operating_leverage",   # #19
    "profitability",        # #20
    "profitability_change", # #21
    "distance_to_default",  # #23
    # Group D — dependent
    "spread_to_d2d",        # #26
    # Constant (always last)
    "constant",
]

missing_cols = [c for c in CHAR_COLS if c not in df.columns]
if missing_cols:
    print(f"\n  ⚠  Missing columns (absent from output): {missing_cols}")

available = ["RIC", "month_end"] + [c for c in CHAR_COLS if c in df.columns]
out = df[available].set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# 5. Diagnostics
# ---------------------------------------------------------------------------
char_only = [c for c in CHAR_COLS if c in out.columns and c != "constant"]

print("\n" + "=" * 60)
print("FINAL PANEL DIAGNOSTICS")
print("=" * 60)
print(f"Shape          : {out.shape}")
print(f"Unique RICs    : {out.index.get_level_values('RIC').nunique():,}")
dates = out.index.get_level_values("month_end")
print(f"Date range     : {dates.min().date()} → {dates.max().date()}")
print(f"Unique months  : {dates.nunique()}")
print(f"Characteristics: {len(char_only)}/28  (+ constant;  #29 vix_beta pending)")

print("\n--- NaN % per characteristic ---")
nan_pct = out[char_only].isna().mean().mul(100)
for col, pct in nan_pct.items():
    filled = int(pct // 5)
    bar = "█" * filled + "░" * (20 - filled)
    flag = " ⚠" if pct > 50 else ""
    print(f"  {col:<25} {pct:5.1f}%  {bar}{flag}")

print("\n--- Annual coverage (% rows with ALL 28 chars non-NaN) ---")
df_diag = out[char_only].copy()
df_diag["year"] = dates.year
df_diag["complete"] = df_diag[char_only].notna().all(axis=1)
cov = df_diag.groupby("year")["complete"].mean().mul(100)
for yr, pct in cov.items():
    filled = int(pct // 5)
    bar = "█" * filled + "░" * (20 - filled)
    print(f"  {yr}  {pct:5.1f}%  {bar}")

# ---------------------------------------------------------------------------
# 6. Save
# ---------------------------------------------------------------------------
output_path.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(output_path)
print(f"\n✓ Saved to {output_path}")
print(f"  Columns ({len(out.columns)}): {list(out.columns)}")