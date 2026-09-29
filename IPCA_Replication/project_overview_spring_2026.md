# IPCA Replication — Project Overview

Replication of **Kelly, Palhares & Pruitt (2021)**, "Modeling Corporate Bond Returns,"
using an Instrumented PCA (IPCA) conditional factor model for US corporate bonds.
---

## Data Sources

Raw data live in `src/data/` (not versioned here):

| File | Contents |
|------|----------|
| `datascope_price_eod.parquet` | Daily bond prices and yields (2002–2025) |
| `datascope_yield_eod.parquet` | Daily bond yields |
| `datascope_characteristic_eod.parquet` | Bond–equity ticker bridge and metadata |
| `yieldbook_price_yield.parquet` | YieldBook OAS and duration |
| `yieldbook_indicatives.parquet` | Bond statics: coupon, issue date, rating, CUSIP |
| `fmp_hist_financial_statements.parquet` | Issuer financials |
| `fmp_enterprise_valuations_ratings.parquet` | Market cap, stock price |
| `norgate_eod_stock_prices.parquet` | Equity prices for momentum/volatility |
| `wrds_eod_us_treasury_monthly.parquet` | Treasury returns for credit excess return hedge |

---

## Pipeline

### Stage 03 — Monthly Return Panel

Constructs month-end bond returns from daily prices and optionally hedges against
Treasury returns to produce credit excess returns.

| File | Description |
|------|-------------|
| `03_01a_build_monthly_bond_panel.py` | Aggregates daily prices/yields to month-end; outputs `bond_panel_monthly.parquet` |
| `03_01b_sensecheck_bond_panel.ipynb` | Coverage and distribution checks |
| `03_02a_treasury_hedge.py` | Joins Treasury returns; outputs `bond_panel_monthly_with_treasury.parquet` and `treasury_monthly_return.parquet` |
| `03_02b_sensecheck_hedge_panel.ipynb` | Hedge coverage checks |
| `03_02c_clean_after_hedge.py` | Drops missing `credit_excess_return`; winsorises at 1%/99%; outputs `bond_panel_monthly_clean.parquet` |
| `03_02d_sensecheck_clean_panel.ipynb` | Post-clean distribution checks |

### Stage 04 — Spread and Duration Panel

Extracts OAS and duration from YieldBook and merges onto the return panel.

| File | Description |
|------|-------------|
| `04_01a_build_monthly_spread_duration.py` | Aggregates YieldBook to month-end; outputs `yieldbook_spread_duration_monthly.parquet` |
| `04_02a_merge_spread_duration.py` | Joins spread/duration onto clean return panel |
| `04_02b_sensecheck_merged_spread_duration.ipynb` | Merge coverage checks |
| `04_02c_clean_spread_duration.py` | Drops fully-missing RICs; forward/back-fills OAS and Duration; outputs `bond_panel_monthly_clean_with_spread_duration_filtered.parquet` |
| `04_02d_sensecheck_clean_spread_duration.ipynb` | Post-filter checks |

### Stage 05 — Bond and Firm Characteristics

Builds 28 characteristics across four groups, following KPP's definitions.

| File | Group | Characteristics |
|------|-------|-----------------|
| `05_02a_characteristics_group_a_static.py` | A — Static | `bond_age`, `coupon`, `face_value`, `duration`, `spread`, `rating` |
| `05_02b_characteristics_group_b_rolling.py` | B — Rolling | Bond momentum, volatility, skewness, VaR |
| `05_02c_characteristics_group_c_firm.py` | C — Firm | Financials, equity momentum/volatility, distance-to-default |
| `05_02d_characteristics_group_b_dependent.py` | D — Dependent | `spread_to_d2d` |
| `05_02e_build_all.py` | All | Merges A–D; adds `constant`; outputs `characteristics_all.parquet` |
| `05_01_characteristics_inventory.ipynb` | — | Inventories available columns before build |
| `05_03_characteristics_output_overview.ipynb` | — | Coverage and missingness review after build |

### Stage 06 — IPCA Estimation (28 characteristics)

Panel construction, in-sample ALS estimation, expanding-window OOS evaluation,
and portfolio construction. **This is the primary estimation stage.**

| File | Description |
|------|-------------|
| `06_01_panel_construction.py` | DtS scaling, rank-standardisation to [−0.5, 0.5], cross-sectional median imputation, 50-bond minimum filter; outputs `ipca_panel_input.parquet` |
| `06_02_ipca_estimation.py` | ALS estimation for K=1–5; outputs `gamma_beta_K*.parquet`, `factors_K*.parquet`, `insample_metrics.csv` |
| `06_03_ipca_oos.py` | Expanding-window OOS (36-month burn-in); outputs `oos_fitted_K*.parquet`, `oos_metrics.csv` |
| `06_04_ipca_portfolios.py` | Builds spread and tangency portfolios from saved OOS betas/factors |
| `06_05_results_overview.ipynb` | Summary of in-sample and OOS metrics across K=1–5 |
| `06_06_replication_summary.md` | Written summary of main findings vs. KPP benchmarks |
| `06_07_covariance_analysis.ipynb` | Factor and characteristic structure analysis (see below) |
| `06_08_backtest.ipynb` | End-to-end OOS backtest with corrected signal (see below) |
| `06_09_overview.md` | Detailed write-up of Leo's contributions, bug fixes, and results |

### Stage 07 — IPCA Estimation v2 (8 characteristics, 2004+)

A narrower panel retaining only the 8 characteristics with full coverage from 2004,
intended to extend the estimation window. Scripts `07_02` through `07_04` are
placeholders not yet implemented.

| File | Description |
|------|-------------|
| `07_01_panel_construction_v2.py` | Same as `06_01` but 8 characteristics, 30-bond minimum; outputs to `outputs_v2/` |
| `07_05_results_overview_v2.ipynb` | Placeholder |

---

## Bug Fixes (Leo)

Three look-ahead and merge bugs were found and corrected. The full pipeline was
re-run after the fixes; see `06_09_overview.md` § 1 and § 3 for before/after metrics.

**1. Rolling characteristics include current-period return (`05_02b`)**
Group B rolling windows (momentum, volatility, skewness, VaR) were computed
including month `t`'s return. Because these enter the IPCA signal at `t`, this
gave the signal implicit knowledge of the return it was predicting.
Fix: all rolling windows shifted to end at `t−1`.

**2. Industry momentum uses contemporaneous cross-section (`05_02d`)**
Industry-level momentum aggregated the cross-sectional median spread within each
group at time `t` instead of using the prior month's median.
Fix: all industry aggregations now use the lagged (prior-month) median.

**3. Panel construction merges on a null column (`06_01`)**
Industry codes from `yieldbook_indicatives` were joined on `RIC`, which is entirely
null in that file. No bond received an industry code; industry characteristics were
zero throughout the panel.
Fix: merge on `CUSIP` instead. Post-fix industry code coverage is ~87%.

---

## Analysis Notebooks (Leo)

### `06_07_covariance_analysis.ipynb`

Characterises the structure of the K=5 IPCA model:

- Characteristic correlation heatmap (identifies collinear inputs)
- Factor covariance matrix — documents non-zero off-diagonal correlations; f1–f2 = 0.54,
  f1–f4 = 0.45 (IPCA does not impose orthogonality, unlike PCA)
- Implied beta covariance — propagates Γ through factor covariance to get model-implied
  cross-sectional return spread
- Characteristic importance ranking — top entries: `constant`, `spread`, `duration`,
  `equity_market_cap`, `equity_volatility`
- Factor interpretation via dominant Γ loadings:

| Factor | Interpretation |
|--------|----------------|
| f1 | Market / level (constant −0.87) |
| f2 | IG vs. HY spread (duration −0.59, spread +0.45) |
| f3 | Pure credit spread (+0.81) |
| f4 | Rate sensitivity (duration +0.60) |
| f5 | Distress / mispricing (spread_to_d2d, equity vol) |

### `06_08_backtest.ipynb`

End-to-end OOS backtest of the K=5 model over 118 months (Dec 2015 – Sep 2025).

**Signal correction.** The original backtest (`06_04`) sorted on `β̂'f̂_t`, where
`f̂_t` is recovered from a cross-section regression on `r_t`. This is circular —
sorting on a regression fit to the dependent variable produces Sharpe ≈ 5.78 but
has no predictive content. The corrected signal is `β̂'λ̂_t`, where `λ̂_t` is the
expanding-window mean of OOS factor realisations through `t−1`.

Sections:
1. Full-period gross and net performance summary
2. Subperiod analysis (pre-COVID, COVID shock, recovery, rate hike cycle, post-hike)
3. Drawdown analysis
4. Factor exposure regression (market and Treasury betas)
5. Rolling 24-month Sharpe
6. Signal-to-noise decomposition
7. Tangency portfolio comparison with corrected expanding window

---

## Key Results

### R² (K=5)

| Metric | Pre-fix | Post-fix | KPP ref |
|--------|---------|----------|---------|
| In-sample Total R² | 89.9% | 89.0% | 49.7% |
| OOS Total R² | 89.4% | 88.7% | 50.7% |
| In-sample RPE | 18.6% | 94.4% | 60.4% |
| OOS RPE | 17.3% | 90.7% | 63.4% |

Total R² changed by less than 1pp. RPE increased dramatically post-fix — the
original low RPE was an artefact of the look-ahead allowing the factor structure
to absorb cross-sectional mean returns.

### Portfolio Performance (K=5, OOS)

| Strategy | Previous | Corrected | KPP ref |
|----------|----------|-----------|---------|
| Quintile spread — gross Sharpe | 5.78 *(circular)* | −0.08 | 3.53 |
| Quintile spread — net Sharpe (19bps, 47% TO) | — | −0.16 | — |
| Tangency γ=0 — gross Sharpe | 0.80 *(look-ahead)* | −0.04 | 6.23 |

All three previous figures were artefacts of look-ahead bias. The corrected
Sharpe near zero is consistent with post-GFC compression of credit risk premia:
the cross-sectional signal-to-noise ratio averages 0.08 (idiosyncratic noise is
11× larger than the predictive signal).

---

## Outputs

Intermediate and final outputs are stored in `outputs/` (and `outputs_v2/` for
the v2 panel):

```
outputs/
  bond_panel_monthly*.parquet          # Stage 03 return panels
  treasury_monthly_return.parquet
  yieldbook_spread_duration_monthly.parquet
  characteristics_group_a/b/c/d.parquet
  characteristics_all.parquet
  ipca_panel_input.parquet
  ipca_monthly_counts.parquet
  ipca_insample/                        # gamma_beta, factors, metrics (K=1–5)
  ipca_oos/                             # oos_fitted, metrics (K=1–5)
  ipca_portfolios/                      # oos_port_data, oos_factors (K=5)
  backtest/                             # Five backtest figures (06_08)
```

---

## Panel Key

- Bond identifier: `RIC`
- Time dimension: `month_end`
- Datascope daily inputs use `Trade Date`; YieldBook uses `PricingDate`
- FMP uses `filingDate` / `date`; Norgate uses `Date`
