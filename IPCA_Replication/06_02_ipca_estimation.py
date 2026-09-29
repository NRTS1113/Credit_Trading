# =============================================================================
# 06_02_ipca_estimation.py
#
# In-sample IPCA estimation via Alternating Least Squares (ALS)
# Replicates Kelly, Palhares & Pruitt (2021) Table III
#
# Model:  r_{i,t+1} = beta_{i,t}' f_{t+1} + eps_{i,t+1}
#         beta_{i,t} = z_{i,t}' Gamma_beta          (L x K)
#
# ALS alternates between:
#   Step A (factors):  f_{t+1} = (Gamma' Z_t' Z_t Gamma)^{-1} Gamma' Z_t' r_{t+1}
#   Step B (Gamma):    vec(Gamma') = [sum_t Z_t'Z_t ⊗ f f'] ^{-1} [sum_t (Z_t ⊗ f')' r_{t+1}]
#
# Identification (KPP):
#   - Gamma'Gamma = I_K   (orthonormal columns)
#   - E[f f'] diagonal with descending entries
#   - mean(f_k) >= 0 for all k
#
# Performance metrics (KPP Section 2.3):
#   Total R²          : 1 - SS_resid / SS_total   (panel, demeaned by zero)
#   Time Series R²    : weighted avg of asset-level R²
#   Cross Section R²  : time-avg of period-by-period cross-section R²
#   Relative Pricing Error : sum(alpha_i²) / sum(r_bar_i²)
# =============================================================================

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.linalg import svd
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
repo_root = Path(__file__).resolve().parents[1]
out_dir   = Path(__file__).resolve().parent / "outputs"

panel_path = out_dir / "ipca_panel_input.parquet"
results_dir = out_dir / "ipca_insample"
results_dir.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Load panel
# ---------------------------------------------------------------------------
print("Loading panel...")
df = pd.read_parquet(panel_path).reset_index()

CHAR_COLS = [c for c in df.columns
             if c not in ("RIC", "month_end", "ret_scaled", "ret_raw",
                          "DtS", "n_imputed")]

L = len(CHAR_COLS)        # number of instruments (incl. constant)
months = sorted(df["month_end"].unique())
T = len(months)
month_idx = {m: i for i, m in enumerate(months)}

print(f"  Panel : {len(df):,} obs, {df['RIC'].nunique():,} RICs, "
      f"{T} months, L={L} instruments")

# ---------------------------------------------------------------------------
# Build stacked arrays
#   Z[t] : N_t x L  instrument matrix
#   r[t] : N_t      return vector
# ---------------------------------------------------------------------------
print("Building per-period arrays...")

Z_list = []   # list of (N_t x L) arrays
r_list = []   # list of (N_t,) arrays

for m in months:
    sub = df[df["month_end"] == m]
    Z_list.append(sub[CHAR_COLS].values.astype(np.float64))   # N_t x L
    r_list.append(sub["ret_scaled"].values.astype(np.float64)) # N_t

# Total observations (for R² denominator)
N_total = sum(len(r) for r in r_list)

# ---------------------------------------------------------------------------
# ALS algorithm
# ---------------------------------------------------------------------------
ALS_MAX_ITER = 200
ALS_TOL      = 1e-7

def als_ipca(K: int, seed: int = 0) -> dict:
    """
    Fit IPCA with K factors via ALS.
    Returns dict with Gamma_beta (L x K), factors (T x K), and fit metrics.
    """
    rng = np.random.default_rng(seed)

    # ── Initialise Gamma_beta with first K left singular vectors of
    #    the stacked characteristic-managed portfolio matrix X (T x L)
    #    x_t = Z_t' r_{t+1} / N_t  (KPP eq. 4)
    X = np.vstack([(Z.T @ r) / len(r) for Z, r in zip(Z_list, r_list)])  # T x L
    U, _, _ = svd(X, full_matrices=False)
    # X = U S V' → managed-portfolio PCA gives V as initial Gamma
    _, S_xz, Vt = svd(X, full_matrices=False)
    Gamma = Vt[:K].T   # L x K  (first K right singular vectors of X)
    # Orthonormalise
    Gamma, _ = np.linalg.qr(Gamma)
    Gamma = Gamma[:, :K]

    obj_prev = np.inf

    for it in range(ALS_MAX_ITER):

        # ── Step A: estimate factors given Gamma ──────────────────────────
        # f_{t+1} = (Gamma' Z_t' Z_t Gamma)^{-1} Gamma' Z_t' r_{t+1}
        F = np.zeros((T, K))
        for t, (Z, r) in enumerate(zip(Z_list, r_list)):
            B   = Z @ Gamma          # N_t x K  (betas)
            BtB = B.T @ B            # K x K
            Btr = B.T @ r            # K
            try:
                F[t] = np.linalg.solve(BtB, Btr)
            except np.linalg.LinAlgError:
                F[t] = np.linalg.lstsq(BtB, Btr, rcond=None)[0]

        # ── Step B: estimate Gamma given F ────────────────────────────────
        # Normal equations: [sum_t Z_t'Z_t ⊗ f_t f_t'] vec(Gamma') = [sum_t (Z_t ⊗ f_t')' r_{t+1}]
        # Equivalent compact form:
        #   A_mat (LK x LK) = sum_t (f_t f_t') ⊗ (Z_t' Z_t)
        #   b_vec (LK,)     = sum_t vec(Z_t' r_{t+1} f_t')
        A_mat = np.zeros((L * K, L * K))
        b_vec = np.zeros(L * K)
        for t, (Z, r) in enumerate(zip(Z_list, r_list)):
            ft    = F[t]                     # K
            ZtZ   = Z.T @ Z                  # L x L
            ZtZkron = np.kron(np.outer(ft, ft), ZtZ)   # LK x LK
            A_mat += ZtZkron
            Ztr   = Z.T @ r                  # L
            b_vec += np.kron(ft, Ztr)        # LK

        try:
            gamma_vec = np.linalg.solve(A_mat, b_vec)
        except np.linalg.LinAlgError:
            gamma_vec = np.linalg.lstsq(A_mat, b_vec, rcond=None)[0]

        Gamma_new = gamma_vec.reshape(K, L).T   # L x K

        # ── Identification: QR orthonormalisation of Gamma ────────────────
        Gamma_new, R = np.linalg.qr(Gamma_new)
        Gamma_new = Gamma_new[:, :K]
        # Align sign of R diagonal so Gamma columns are consistent
        signs = np.sign(np.diag(R[:K, :K]))
        signs[signs == 0] = 1
        Gamma_new = Gamma_new * signs[np.newaxis, :]

        # ── Convergence check ─────────────────────────────────────────────
        obj = sum(
            np.sum((r - (Z @ Gamma_new) @ F[t]) ** 2)
            for t, (Z, r) in enumerate(zip(Z_list, r_list))
        )
        delta = abs(obj_prev - obj) / max(abs(obj_prev), 1e-10)
        obj_prev = obj
        Gamma = Gamma_new

        if delta < ALS_TOL and it >= 3:
            print(f"    K={K}: converged at iter {it+1}  (obj={obj:.6f})")
            break
    else:
        print(f"    K={K}: reached max iter {ALS_MAX_ITER}  (obj={obj:.6f})")

    # ── Re-estimate F one final time with converged Gamma ─────────────────
    for t, (Z, r) in enumerate(zip(Z_list, r_list)):
        B   = Z @ Gamma
        BtB = B.T @ B
        Btr = B.T @ r
        try:
            F[t] = np.linalg.solve(BtB, Btr)
        except np.linalg.LinAlgError:
            F[t] = np.linalg.lstsq(BtB, Btr, rcond=None)[0]

    # ── Identification: order factors by descending variance ──────────────
    factor_vars = np.var(F, axis=0)
    order = np.argsort(-factor_vars)
    F     = F[:, order]
    Gamma = Gamma[:, order]

    # Ensure mean of each factor is non-negative
    for k in range(K):
        if np.mean(F[:, k]) < 0:
            F[:, k]     = -F[:, k]
            Gamma[:, k] = -Gamma[:, k]

    return {"Gamma": Gamma, "F": F, "K": K}


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

def compute_metrics(result: dict) -> dict:
    """Compute KPP Table III metrics from ALS result."""
    Gamma = result["Gamma"]
    F     = result["F"]
    K     = result["K"]

    SS_total = sum(np.sum(r ** 2) for r in r_list)

    resid_list    = []
    fitted_list   = []
    ts_r2_list    = []
    ts_weights    = []
    cs_r2_list    = []

    # Build per-RIC containers for pricing error
    ric_resid  = {}   # RIC → list of residuals
    ric_ret    = {}   # RIC → list of returns

    ric_col = df["RIC"].values
    month_col = df["month_end"].values

    for t, (Z, r, m) in enumerate(zip(Z_list, r_list, months)):
        ft     = F[t]                   # K
        fitted = (Z @ Gamma) @ ft       # N_t
        resid  = r - fitted

        # Which RICs are in this period
        mask   = month_col == m
        rics_t = ric_col[mask]

        resid_list.append(resid)
        fitted_list.append(fitted)

        # Time series R² contribution
        ss_r = np.sum(r ** 2)
        ss_e = np.sum(resid ** 2)
        # (stored per-obs, aggregated per RIC below)

        # Cross-section R²_t  (KPP eq. 8)
        ss_r_t = np.sum(r ** 2)
        if ss_r_t > 0:
            cs_r2_list.append(1 - np.sum(resid ** 2) / ss_r_t)

        for i, ric in enumerate(rics_t):
            if ric not in ric_resid:
                ric_resid[ric] = []
                ric_ret[ric]   = []
            ric_resid[ric].append(resid[i])
            ric_ret[ric].append(r[i])

    # Total R²
    SS_resid = sum(np.sum(e ** 2) for e in resid_list)
    total_r2 = 1 - SS_resid / SS_total

    # Time Series R² (weighted by T_i)
    ts_r2_vals = []
    ts_r2_wts  = []
    for ric in ric_resid:
        ri  = np.array(ric_ret[ric])
        ei  = np.array(ric_resid[ric])
        Ti  = len(ri)
        ss  = np.sum(ri ** 2)
        if ss > 0:
            ts_r2_vals.append((1 - np.sum(ei ** 2) / ss) * Ti)
            ts_r2_wts.append(Ti)
    ts_r2 = sum(ts_r2_vals) / sum(ts_r2_wts) if ts_r2_wts else np.nan

    # Cross Section R²
    cs_r2 = np.mean(cs_r2_list) if cs_r2_list else np.nan

    # Relative Pricing Error  (KPP eq. 9)
    alphas  = []
    r_bars  = []
    for ric in ric_resid:
        alphas.append(np.mean(ric_resid[ric]))
        r_bars.append(np.mean(ric_ret[ric]))
    alphas  = np.array(alphas)
    r_bars  = np.array(r_bars)
    rpe = np.sum(alphas ** 2) / np.sum(r_bars ** 2) if np.sum(r_bars ** 2) > 0 else np.nan

    return {
        "K":             K,
        "Total_R2":      round(total_r2 * 100, 1),
        "TimeSeries_R2": round(ts_r2 * 100,    1),
        "CrossSect_R2":  round(cs_r2 * 100,    1),
        "RelPricingErr": round(rpe * 100,       1),
    }


# ---------------------------------------------------------------------------
# Run for K = 1 .. 5
# ---------------------------------------------------------------------------
print("\nRunning ALS IPCA  (K = 1 … 5) …")
all_results = {}
metrics_rows = []

for K in range(1, 6):
    print(f"\n  Fitting K={K}...")
    res = als_ipca(K)
    all_results[K] = res

    m = compute_metrics(res)
    metrics_rows.append(m)
    print(f"    Total R²={m['Total_R2']}%  TS R²={m['TimeSeries_R2']}%  "
          f"CS R²={m['CrossSect_R2']}%  RPE={m['RelPricingErr']}%")

    # Save Gamma and F
    Gamma_df = pd.DataFrame(
        res["Gamma"],
        index=CHAR_COLS,
        columns=[f"f{k+1}" for k in range(K)]
    )
    F_df = pd.DataFrame(
        res["F"],
        index=months,
        columns=[f"f{k+1}" for k in range(K)]
    )
    F_df.index.name = "month_end"
    Gamma_df.to_parquet(results_dir / f"gamma_beta_K{K}.parquet")
    F_df.to_parquet(results_dir / f"factors_K{K}.parquet")

# ---------------------------------------------------------------------------
# Summary table (mirrors KPP Table III Panel A — individual bonds)
# ---------------------------------------------------------------------------
metrics_df = pd.DataFrame(metrics_rows).set_index("K")

print("\n" + "=" * 65)
print("IN-SAMPLE IPCA PERFORMANCE  (Individual Bonds)")
print("KPP Table III Panel A reference:")
print("  K=1: Total=41.6, TS=33.4, CS=23.1, RPE=53.6")
print("  K=5: Total=49.7, TS=43.1, CS=33.3, RPE=60.4")
print("=" * 65)
print(metrics_df.to_string())
print("=" * 65)

metrics_df.to_csv(results_dir / "insample_metrics.csv")
print(f"\n✓ Results saved to {results_dir}/")
print("  gamma_beta_K1..K5.parquet  — Gamma_beta matrices")
print("  factors_K1..K5.parquet     — Factor time series")
print("  insample_metrics.csv       — Summary table")