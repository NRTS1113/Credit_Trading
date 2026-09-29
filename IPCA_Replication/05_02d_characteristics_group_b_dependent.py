"""
Group D: Dependent Characteristics (require outputs from other groups)
Characteristics:
    #26  Spread-to-D2D  — OAS / (1 - Phi(D2D))
                          where Phi is the standard normal CDF
                          and D2D is distance_to_default from Group C

        Interpretation: a bond "value" measure — spread per unit of default probability.
        High spread-to-D2D → high spread relative to credit risk → bond looks cheap.
        Reference: Correia et al. (2012), also Table IX of KPP (2021).

Input:
    IPCA_Replication/outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet
    IPCA_Replication/outputs/characteristics_group_c.parquet   (for distance_to_default)

Output:
    IPCA_Replication/outputs/characteristics_group_d.parquet
    Index: (RIC, month_end)
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root   = Path(__file__).resolve().parent.parent
out_dir     = Path(__file__).resolve().parent / "outputs"

panel_path   = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
group_c_path = out_dir / "characteristics_group_c.parquet"
output_path  = out_dir / "characteristics_group_d.parquet"

# ---------------------------------------------------------------------------
# Load base panel — need OAS (= spread)
# ---------------------------------------------------------------------------
print("Loading panel...")
panel = pd.read_parquet(panel_path, columns=["RIC", "month_end", "OAS"])
panel["month_end"] = pd.to_datetime(panel["month_end"])
panel = panel.sort_values(["RIC", "month_end"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# Load distance_to_default from Group C
# ---------------------------------------------------------------------------
print("Loading Group C for distance_to_default...")
group_c = pd.read_parquet(group_c_path, columns=["distance_to_default"])
group_c = group_c.reset_index()   # brings RIC, month_end back as columns
group_c["month_end"] = pd.to_datetime(group_c["month_end"])

# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------
df = panel.merge(group_c[["RIC", "month_end", "distance_to_default"]],
                 on=["RIC", "month_end"], how="left")

# ---------------------------------------------------------------------------
# #26  Spread-to-D2D
#
#   spread_to_d2d = OAS / D2D
#
#   Following Table A.I of KPP (2021): "the spread divided by distance-to-
#   default."  This is a bond "value" measure — high spread relative to
#   credit risk implies the bond looks cheap.
#   Reference: Correia et al. (2012).
#
#   Implementation notes:
#     - OAS must be positive; zero/negative OAS → NaN
#     - D2D must be positive; zero/negative D2D → NaN  (negative D2D means
#       firm value already below debt face value — extremely distressed)
#     - Cross-sectional winsorise at 1%/99% each month to dampen outliers
#       from near-zero D2D values that survived the positivity filter
# ---------------------------------------------------------------------------
print("Computing #26 Spread-to-D2D...")

# OAS must be positive (occasionally negative OAS occurs for very safe bonds)
oas_valid = df["OAS"].where(df["OAS"] > 0)

# D2D must be positive (clip to small positive to avoid div-by-zero;
# negative D2D is economically meaningless for this ratio)
d2d_valid = df["distance_to_default"].where(df["distance_to_default"] > 0)

raw = oas_valid / d2d_valid

df["spread_to_d2d"] = raw

# Global winsorise at 1st/99th percentile (ignoring NaN)
# Bounds are computed cross-sectionally each month, then applied to that month's values.
df["spread_to_d2d"] = df.groupby("month_end")["spread_to_d2d"].transform(
    lambda x: x.clip(lower=x.quantile(0.01), upper=x.quantile(0.99))
)
print("  Done computing spread_to_d2d with winsorisation.")

# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------
out_cols = ["RIC", "month_end", "spread_to_d2d"]   # #26
out = df[out_cols].copy()
out = out.set_index(["RIC", "month_end"]).sort_index()

# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
print("\n=== Group D output shape ===")
print(out.shape)
print("\n=== NaN counts ===")
print(out.isna().sum())
print(f"\n=== NaN % ===")
print((out.isna().mean() * 100).round(2))
print("\n=== Describe ===")
print(out.describe())
print("\n=== Sample (first 5) ===")
print(out.head())

# Sanity: spread_to_d2d should be positive and not absurdly large
n_neg = (out["spread_to_d2d"] < 0).sum()
n_large = (out["spread_to_d2d"] > 1e4).sum()
print(f"\n  Negative values  : {n_neg}")
print(f"  Values > 10,000  : {n_large}  (should be 0 after winsorisation)")

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
output_path.parent.mkdir(parents=True, exist_ok=True)
out.to_parquet(output_path)
print(f"\nSaved to {output_path}")