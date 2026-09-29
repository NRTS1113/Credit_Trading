# =============================================================================
# 06_04b_portfolios_only.py
#
# Reads saved OOS data from 06_04 and reconstructs portfolios.
# Run this instead of full 06_04 to avoid re-running the OOS loop.
# =============================================================================

import numpy as np
import pandas as pd
from pathlib import Path

out_dir  = Path(__file__).resolve().parent / "outputs"
port_dir = out_dir / "ipca_portfolios"

K      = 5
TC_BPS = 19e-4
GAMMAS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

# ---------------------------------------------------------------------------
# Load saved OOS data
# ---------------------------------------------------------------------------
print("Loading saved OOS data...")
port_df   = pd.read_parquet(port_dir / "oos_port_data_K5.parquet")
factor_df = pd.read_parquet(port_dir / "oos_factors_K5.parquet")

print(f"  port_df  : {len(port_df):,} rows, "
      f"{port_df['month_end'].nunique()} months")
print(f"  factor_df: {len(factor_df)} months")

beta_cols = [f"beta{k+1}" for k in range(K)]
fac_cols  = [f"f{k+1}"   for k in range(K)]

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def sharpe(r_series):
    r = np.array(r_series)
    r = r[np.isfinite(r)]
    if len(r) < 2 or r.std() == 0:
        return np.nan
    return r.mean() / r.std() * np.sqrt(12)

# ---------------------------------------------------------------------------
# STRATEGY 1 — Quintile spread  (sort on fitted = beta @ f_hat)
# ---------------------------------------------------------------------------
print("\nConstructing quintile spread strategy ...")

port_df2 = port_df.merge(
    factor_df.reset_index()[["month_end"] + fac_cols],
    on="month_end", how="left"
)
port_df2["fitted"] = (
    port_df2[beta_cols].values * port_df2[fac_cols].values
).sum(axis=1)

months_oos  = sorted(port_df2["month_end"].unique())
spread_rets = []

for m in months_oos:
    sub = port_df2[port_df2["month_end"] == m].copy()
    if len(sub) < 10:
        continue
    sub["quintile"] = pd.qcut(sub["fitted"], 5, labels=False)
    q1 = sub[sub["quintile"] == 0]
    q5 = sub[sub["quintile"] == 4]
    if len(q1) == 0 or len(q5) == 0:
        continue
    spread_rets.append({
        "month_end": m,
        "ret": q5["ret_scaled"].mean() - q1["ret_scaled"].mean()
    })

spread_df = pd.DataFrame(spread_rets).set_index("month_end")
spread_sr  = sharpe(spread_df["ret"])

# Diagnostics
print(f"  Months in spread strategy : {len(spread_df)}")
print(f"  Mean monthly ret          : {spread_df['ret'].mean():.5f}")
print(f"  Std monthly ret           : {spread_df['ret'].std():.5f}")
print(f"  Gross Sharpe              : {spread_sr:.2f}")
print(f"  KPP Table VII K=5 ref     : 3.53")

spread_df.to_csv(port_dir / "spread_returns.csv")

# Quick check: fitted value cross-sectional std per month
cs_std = port_df2.groupby("month_end")["fitted"].std().mean()
print(f"\n  [Diag] Mean cross-sect std of fitted : {cs_std:.5f}")
print(f"  [Diag] Factor means:\n{factor_df.mean().round(5)}")

# ---------------------------------------------------------------------------
# STRATEGY 2 — Factor tangency portfolio
# ---------------------------------------------------------------------------
print("\nConstructing factor tangency portfolio ...")

tangency_rows = []

for gamma in GAMMAS:
    w_smooth   = None
    w_prev     = None
    rets_gross = []
    rets_net   = []
    turnovers  = []

    for m in months_oos:
        if m not in factor_df.index:
            continue
        f_row = factor_df.loc[m].values   # K

        # Expanding history up to and including this month
        hist = factor_df.loc[factor_df.index <= m].values
        if len(hist) < K + 2:
            w_prev = np.zeros(K)
            continue

        mu  = hist.mean(axis=0)
        cov = np.cov(hist.T) + 1e-6 * np.eye(K)

        try:    w_raw = np.linalg.solve(cov, mu)
        except: w_raw = np.linalg.lstsq(cov, mu, rcond=None)[0]

        l1 = np.sum(np.abs(w_raw))
        w_norm = w_raw / (l1 + 1e-10)

        if w_smooth is None:
            w_smooth = w_norm.copy()
        else:
            w_smooth = (1 - gamma) * w_norm + gamma * w_smooth

        r_gross = np.dot(w_smooth, f_row)
        rets_gross.append(r_gross)

        if w_prev is None or np.sum(np.abs(w_prev)) < 1e-8:
            w_prev = w_smooth.copy()
            rets_net.append(r_gross)
            continue

        trade   = np.sum(np.abs(w_smooth - w_prev))
        to      = trade / np.sum(np.abs(w_prev))
        r_net   = r_gross - TC_BPS * trade
        rets_net.append(r_net)
        turnovers.append(to)
        w_prev  = w_smooth.copy()

    tangency_rows.append({
        "gamma":        gamma,
        "Turnover":     round(np.mean(turnovers) if turnovers else np.nan, 2),
        "Gross_Sharpe": round(sharpe(rets_gross), 2),
        "Net_Sharpe":   round(sharpe(rets_net),   2),
    })
    print(f"  gamma={gamma:.1f}  TO={tangency_rows[-1]['Turnover']:.2f}"
          f"  Gross={tangency_rows[-1]['Gross_Sharpe']:.2f}"
          f"  Net={tangency_rows[-1]['Net_Sharpe']:.2f}")

tangency_df = pd.DataFrame(tangency_rows).set_index("gamma")
tangency_df.to_csv(port_dir / "tangency_sharpe.csv")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("TANGENCY PORTFOLIO  (K=5, 19bps one-way)")
print("KPP Table VIII ref (gamma=0): Gross=6.23  Net=2.48")
print("=" * 60)
print(tangency_df.to_string())
print("=" * 60)
print(f"\nSpread gross Sharpe = {spread_sr:.2f}")
print(f"KPP Table VII ref   = 3.53")
print(f"\n✓ Saved to {port_dir}/")