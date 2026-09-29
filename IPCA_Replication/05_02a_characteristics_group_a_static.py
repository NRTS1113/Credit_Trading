"""
Group A: Static / Point-in-Time Bond Characteristics
Characteristics: #1 Bond age, #2 Coupon, #3 Face value,
                 #6 Duration, #18 Spread, #22 Rating
Output: IPCA_Replication/outputs/characteristics_group_a.parquet
        Index: (RIC, month_end)
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root     = Path(__file__).resolve().parent.parent  # CreditTrading/
out_dir       = Path(__file__).resolve().parent / "outputs"
src_data      = repo_root / "src" / "data"
panel_path    = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
output_path   = out_dir / "characteristics_group_a.parquet"

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
panel    = pd.read_parquet(panel_path)
yb_indic = pd.read_parquet(src_data / "yieldbook_indicatives.parquet", engine="fastparquet")

# yieldbook_indicatives has RIC as index — reset for merging
yb_indic = yb_indic.reset_index()  # brings RIC back as a column

# ---------------------------------------------------------------------------
# Select and rename indicatives fields needed for Group A
# ---------------------------------------------------------------------------
indic_cols = {
    "RIC"                     : "RIC",
    "currentCoupon"           : "coupon",
    "indic.issueDate"         : "issue_date",
    "indic.outstandingAmount" : "face_value",
    "indic.indexRating"       : "rating_raw",
}
indic = yb_indic[list(indic_cols.keys())].rename(columns=indic_cols).copy()

# ---------------------------------------------------------------------------
# Rating: convert to numeric 1–22
# Most bonds already store indexRating as a numeric or short string.
# The paper defines 1 = AAA, 22 = default (S&P scale).
# ---------------------------------------------------------------------------
RATING_MAP = {
    "AAA": 1,  "AA+": 2,  "AA": 3,   "AA-": 4,
    "A+":  5,  "A":   6,  "A-":  7,
    "BBB+": 8, "BBB": 9,  "BBB-": 10,
    "BB+": 11, "BB": 12,  "BB-": 13,
    "B+":  14, "B":  15,  "B-":  16,
    "CCC+":17, "CCC":18,  "CCC-":19,
    "CC":  20, "C":  21,  "D":   22,
}

def parse_rating(val):
    if pd.isna(val):
        return np.nan
    if isinstance(val, (int, float)):
        return float(val)
    return float(RATING_MAP.get(str(val).strip().upper(), np.nan))

indic["rating"] = indic["rating_raw"].apply(parse_rating)

# ---------------------------------------------------------------------------
# Merge indicatives (static) onto panel
# ---------------------------------------------------------------------------
panel["month_end"] = pd.to_datetime(panel["month_end"])
indic["issue_date"] = pd.to_datetime(indic["issue_date"])

df = panel[["RIC", "month_end", "OAS", "Duration"]].merge(
    indic[["RIC", "coupon", "issue_date", "face_value", "rating"]],
    on="RIC",
    how="left",
)

# ---------------------------------------------------------------------------
# Characteristic #1: Bond age (years from issue date to month_end)
# ---------------------------------------------------------------------------
df["bond_age"] = (df["month_end"] - df["issue_date"]).dt.days / 365.25

# ---------------------------------------------------------------------------
# Characteristic #2: Coupon (already in indic as currentCoupon, in %)
# ---------------------------------------------------------------------------
# coupon column already attached — no further transformation needed

# ---------------------------------------------------------------------------
# Characteristic #3: Face value (outstanding amount, in millions)
# ---------------------------------------------------------------------------
# face_value column already attached — log-transform common in literature
# but paper uses raw value before cross-sectional rank-standardisation
# leave as-is; standardisation happens in build_all

# ---------------------------------------------------------------------------
# Characteristic #6: Duration (from base panel)
# ---------------------------------------------------------------------------
# Duration column already in df

# ---------------------------------------------------------------------------
# Characteristic #18: Spread = OAS (from base panel, in basis points)
# ---------------------------------------------------------------------------
# OAS column already in df

# ---------------------------------------------------------------------------
# Characteristic #22: Rating (numeric 1–22, from indicatives)
# ---------------------------------------------------------------------------
# rating column already attached

# ---------------------------------------------------------------------------
# Final output: keep only characteristic columns
# ---------------------------------------------------------------------------
out = df[["RIC", "month_end",
          "bond_age",    # #1
          "coupon",      # #2
          "face_value",  # #3
          "Duration",    # #6
          "OAS",         # #18
          "rating",      # #22
         ]].copy()

out = out.rename(columns={
    "Duration" : "duration",
    "OAS"      : "spread",
})

out = out.set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
print("=== Group A output shape ===")
print(out.shape)
print("\n=== NaN counts ===")
print(out.isna().sum())
print("\n=== Sample ===")
print(out.head(5))

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
output_path.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(output_path)
print(f"\nSaved to {output_path}")
