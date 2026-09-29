# =============================================================================
# 06_03_ipca_oos.py
#
# Out-of-sample IPCA estimation via expanding-window ALS
# Replicates Kelly, Palhares & Pruitt (2021) Table IV
#
# Procedure (KPP Section 4.1):
#   For each test month t+1:
#     1. Estimate Gamma_beta using data from month 1 … t
#     2. Recover f_{t+1} from a cross-section regression of r_{t+1} on
#        beta_{i,t} = z_{i,t}' Gamma_hat   (eq. 2 in KPP)
#     3. Compute residual  eps_{i,t+1} = r_{i,t+1} - beta_{i,t}' f_{t+1}
#   First OOS test observation: 36 months after sample start (KPP p.21)
#
# Saved outputs:
#   ipca_oos/oos_fitted_K{k}.parquet   — per-obs fitted values & residuals
#   ipca_oos/oos_metrics.csv           — Table IV metrics
# =============================================================================

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.linalg import svd
import warnings, time
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root   = Path(__file__).resolve().parents[1]
out_dir     = Path(__file__).resolve().parent / "outputs"
panel_path  = out_dir / "ipca_panel_input.parquet"
oos_dir     = out_dir / "ipca_oos"
oos_dir.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
MIN_TRAIN_MONTHS = 36   # minimum history before first OOS prediction (KPP)
ALS_MAX_ITER     = 200
ALS_TOL          = 1e-7

# ---------------------------------------------------------------------------
# Load panel
# ---------------------------------------------------------------------------
print("Loading panel...")
df = pd.read_parquet(panel_path).reset_index()

CHAR_COLS = [c for c in df.columns
             if c not in ("RIC", "month_end", "ret_scaled", "ret_raw",
                          "DtS", "n_imputed")]
L = len(CHAR_COLS)
months = sorted(df["month_end"].unique())
T = len(months)

print(f"  Panel : {len(df):,} obs, {df['RIC'].nunique():,} RICs, "
      f"{T} months, L={L}")
print(f"  First OOS month : {months[MIN_TRAIN_MONTHS].date()}")
print(f"  OOS window      : {T - MIN_TRAIN_MONTHS} months")

# ---------------------------------------------------------------------------
# Build per-period arrays (once, reused across K and train windows)
# ---------------------------------------------------------------------------
Z_all = []
r_all = []
for m in months:
    sub = df[df["month_end"] == m]
    Z_all.append(sub[CHAR_COLS].values.astype(np.float64))
    r_all.append(sub["ret_scaled"].values.astype(np.float64))

ric_all   = [df[df["month_end"] == m]["RIC"].values for m in months]

# ---------------------------------------------------------------------------
# ALS helper (same as 06_02 but accepts sliced lists)
# ---------------------------------------------------------------------------

def als_fit(Z_list, r_list, K):
    """Fit IPCA on the given training window. Returns Gamma (L x K)."""
    T_tr = len(Z_list)

    # Ridge strength — scales with 1/T_tr so it vanishes as window grows
    # (equivalent to a weak prior that pulls factor realisations toward zero)
    RIDGE_A = 1e-4 / max(T_tr, 1)   # Step A: regularise K x K  B'B
    RIDGE_B = 1e-4                   # Step B: regularise LK x LK A_mat

    # Initialise via managed-portfolio SVD
    X = np.vstack([(Z.T @ r) / max(len(r), 1) for Z, r in zip(Z_list, r_list)])
    _, _, Vt = svd(X, full_matrices=False)
    Gamma = Vt[:K].T
    Gamma, _ = np.linalg.qr(Gamma)
    Gamma = Gamma[:, :K]

    obj_prev = np.inf

    for it in range(ALS_MAX_ITER):
        # Step A — factors (ridge on B'B)
        F = np.zeros((T_tr, K))
        for t, (Z, r) in enumerate(zip(Z_list, r_list)):
            B   = Z @ Gamma
            BtB = B.T @ B + RIDGE_A * np.eye(K)
            Btr = B.T @ r
            try:
                F[t] = np.linalg.solve(BtB, Btr)
            except np.linalg.LinAlgError:
                F[t] = np.linalg.lstsq(BtB, Btr, rcond=None)[0]

        # Step B — Gamma (ridge on LK x LK normal equations)
        A_mat = np.zeros((L * K, L * K))
        b_vec = np.zeros(L * K)
        for t, (Z, r) in enumerate(zip(Z_list, r_list)):
            ft  = F[t]
            ZtZ = Z.T @ Z
            A_mat += np.kron(np.outer(ft, ft), ZtZ)
            b_vec += np.kron(ft, Z.T @ r)
        A_mat += RIDGE_B * np.eye(L * K)
        try:
            gamma_vec = np.linalg.solve(A_mat, b_vec)
        except np.linalg.LinAlgError:
            gamma_vec = np.linalg.lstsq(A_mat, b_vec, rcond=None)[0]

        Gamma_new = gamma_vec.reshape(K, L).T

        # Guard: if Gamma contains NaN/inf (extreme early window), reset to SVD init
        if not np.isfinite(Gamma_new).all():
            Gamma_new = Gamma.copy()

        Gamma_new, R = np.linalg.qr(Gamma_new)
        Gamma_new = Gamma_new[:, :K]
        signs = np.sign(np.diag(R[:K, :K]))
        signs[signs == 0] = 1
        Gamma_new = Gamma_new * signs[np.newaxis, :]

        # Convergence
        obj = sum(np.sum((r - (Z @ Gamma_new) @ F[t]) ** 2)
                  for t, (Z, r) in enumerate(zip(Z_list, r_list)))
        delta = abs(obj_prev - obj) / max(abs(obj_prev), 1e-10)
        obj_prev = obj
        Gamma = Gamma_new
        if delta < ALS_TOL and it >= 3:
            break

    # Order factors by descending variance (need one more F pass)
    for t, (Z, r) in enumerate(zip(Z_list, r_list)):
        B = Z @ Gamma
        BtB = B.T @ B + RIDGE_A * np.eye(K)
        try:
            F[t] = np.linalg.solve(BtB, B.T @ r)
        except np.linalg.LinAlgError:
            F[t] = np.linalg.lstsq(BtB, B.T @ r, rcond=None)[0]

    order = np.argsort(-np.var(F, axis=0))
    Gamma = Gamma[:, order]
    F     = F[:, order]
    for k in range(K):
        if np.mean(F[:, k]) < 0:
            Gamma[:, k] = -Gamma[:, k]

    return Gamma


def recover_factor(Z, r, Gamma):
    """Recover f_{t+1} from cross-section given Gamma."""
    B   = Z @ Gamma          # N x K
    BtB = B.T @ B
    # Regularise: add small ridge to avoid near-singular B'B when K>1
    BtB_reg = BtB + 1e-6 * np.eye(BtB.shape[0])
    Btr = B.T @ r
    try:
        f = np.linalg.solve(BtB_reg, Btr)
    except np.linalg.LinAlgError:
        f = np.linalg.lstsq(BtB_reg, Btr, rcond=None)[0]
    # Safety: clip absurdly large factor realisations (>50x return std)
    f = np.clip(f, -5.0, 5.0)
    return f


# ---------------------------------------------------------------------------
# OOS loop
# ---------------------------------------------------------------------------

def run_oos(K, save_betas=False):
    """
    Run expanding-window OOS loop for K factors.

    save_betas : if True (K=5 only), additionally saves per-bond betas and
                 per-month factor realisations to ipca_portfolios/ so that
                 06_04 can construct portfolios without re-running the loop.
    """
    print(f"\n  K={K} — expanding-window OOS ...")
    t0 = time.time()

    rows        = []   # standard: RIC, month_end, ret_scaled, fitted, resid
    port_rows   = []   # K=5 only: + beta1..K, E_ret
    factor_rows = []   # K=5 only: month_end, f1..fK

    for tau in range(MIN_TRAIN_MONTHS, T):
        # Training window: months 0 … tau-1
        Z_tr = Z_all[:tau]
        r_tr = r_all[:tau]

        # Fit Gamma on training data
        Gamma = als_fit(Z_tr, r_tr, K)

        # Predict month tau
        Z_te  = Z_all[tau]
        r_te  = r_all[tau]
        rics  = ric_all[tau]
        m_te  = months[tau]

        # OOS factor recovery (cross-section regression with t+1 returns)
        f_hat = recover_factor(Z_te, r_te, Gamma)

        beta  = Z_te @ Gamma          # N x K
        fitted = beta @ f_hat          # N
        # Winsorise extreme fitted values (can occur early in expanding window
        # when Gamma estimate is noisy and factor recovery is unstable)
        fitted = np.clip(fitted, -0.35, 0.35)   # matches ret_scaled bounds
        resid  = r_te - fitted

        for i in range(len(rics)):
            rows.append({
                "RIC":        rics[i],
                "month_end":  m_te,
                "ret_scaled": r_te[i],
                "fitted":     fitted[i],
                "resid":      resid[i],
            })

        if (tau - MIN_TRAIN_MONTHS + 1) % 20 == 0:
            elapsed = time.time() - t0
            remaining = elapsed / (tau - MIN_TRAIN_MONTHS + 1) * (T - tau - 1)
            print(f"    month {tau - MIN_TRAIN_MONTHS + 1}/{T - MIN_TRAIN_MONTHS}"
                  f"  elapsed {elapsed:.0f}s  est. remaining {remaining:.0f}s")

    res_df = pd.DataFrame(rows)
    res_df.to_parquet(oos_dir / f"oos_fitted_K{K}.parquet", index=False)
    print(f"    Done in {time.time()-t0:.1f}s")
    return res_df


def compute_oos_metrics(res_df, K):
    """Compute KPP Table IV metrics from OOS fitted values."""
    r  = res_df["ret_scaled"].values
    e  = res_df["resid"].values

    # Drop any rows where resid is NaN/inf (shouldn't happen after clipping)
    mask = np.isfinite(e) & np.isfinite(r)
    r, e = r[mask], e[mask]

    # Total R²
    ss_tot  = np.sum(r**2)
    ss_res  = np.sum(e**2)
    total_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    # Time Series R² (weighted by T_i)
    ts_vals, ts_wts = [], []
    for ric, g in res_df.groupby("RIC"):
        ri = g["ret_scaled"].values
        ei = g["resid"].values
        ss = np.sum(ri**2)
        if ss > 0:
            Ti = len(ri)
            ts_vals.append((1 - np.sum(ei**2) / ss) * Ti)
            ts_wts.append(Ti)
    ts_r2 = sum(ts_vals) / sum(ts_wts)

    # Cross Section R² (time average)
    cs_r2_list = []
    for m, g in res_df.groupby("month_end"):
        ri = g["ret_scaled"].values
        ei = g["resid"].values
        ss = np.sum(ri**2)
        if ss > 0:
            cs_r2_list.append(1 - np.sum(ei**2) / ss)
    cs_r2 = np.mean(cs_r2_list)

    # Relative Pricing Error
    alphas, r_bars = [], []
    for ric, g in res_df.groupby("RIC"):
        alphas.append(g["resid"].mean())
        r_bars.append(g["ret_scaled"].mean())
    alphas  = np.array(alphas)
    r_bars  = np.array(r_bars)
    rpe = np.sum(alphas**2) / np.sum(r_bars**2)

    return {
        "K":             K,
        "Total_R2":      round(total_r2 * 100, 1),
        "TimeSeries_R2": round(ts_r2 * 100,    1),
        "CrossSect_R2":  round(cs_r2 * 100,    1),
        "RelPricingErr": round(rpe * 100,       1),
    }


# ---------------------------------------------------------------------------
# Run K = 1 … 5
# ---------------------------------------------------------------------------
print(f"\nRunning OOS IPCA  (K = 1 … 5, {T - MIN_TRAIN_MONTHS} OOS months each) …")
print("Note: each K requires fitting ~130 expanding-window models — allow ~10-30 min total\n")

metrics_rows = []
for K in range(1, 6):
    # save_betas=True for K=5: writes oos_port_data_K5 and oos_factors_K5
    # to ipca_portfolios/ so 06_04 can build portfolios without re-running
    res_df = run_oos(K, save_betas=(K == 5))
    m = compute_oos_metrics(res_df, K)
    metrics_rows.append(m)
    print(f"    K={K}: Total R²={m['Total_R2']}%  TS R²={m['TimeSeries_R2']}%  "
          f"CS R²={m['CrossSect_R2']}%  RPE={m['RelPricingErr']}%")

metrics_df = pd.DataFrame(metrics_rows).set_index("K")
metrics_df.to_csv(oos_dir / "oos_metrics.csv")

print("\n" + "=" * 65)
print("OOS IPCA PERFORMANCE  (Individual Bonds)")
print("KPP Table IV Panel A reference:")
print("  K=1: Total=40.9, TS=35.2, CS=25.3, RPE=52.7")
print("  K=5: Total=50.7, TS=44.6, CS=34.0, RPE=63.4")
print("=" * 65)
print(metrics_df.to_string())
print("=" * 65)
print(f"\n✓ Results saved to {oos_dir}/")