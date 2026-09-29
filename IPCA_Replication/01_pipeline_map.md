# IPCA Replication Pipeline Map (IPCA_Replication)

This note documents the **current** workflow under `IPCA_Replication/`: which
scripts read which inputs, what they output, and the intended run order. It is
focused on the replication pipeline (not the upstream `src/prepare_*` data build).

Important context:
- The pipeline expects monthly panels; most raw sources in `src/data` are daily
  and are aggregated here.
- Several scripts require `fastparquet` (they explicitly set `engine="fastparquet"`).
- Treasury hedging is optional. If `wrds_eod_us_treasury_monthly.parquet` is
  missing, `credit_excess_return` is left `NA`, and downstream steps will drop
  those rows.

## Core Inputs (from `src/data`)

- `datascope_price_eod.parquet` (daily bond prices)
- `datascope_yield_eod.parquet` (daily bond yields)
- `yieldbook_price_yield.parquet` (YieldBook OAS + Duration)
- `yieldbook_indicatives.parquet` (bond static fields: coupon, issue date, rating)
- `fmp_hist_financial_statements.parquet` (issuer financials)
- `fmp_enterprise_valuations_ratings.parquet` (market cap, stock price)
- `norgate_eod_stock_prices.parquet` (equity prices for momentum/volatility)
- `datascope_characteristic_eod.parquet` (bond → equity ticker bridge)
- `wrds_eod_us_treasury_monthly.parquet` (optional Treasury hedge)

## Stage 03 — Monthly Returns + Treasury Hedge

1. `03_01a_build_monthly_bond_panel.py`
   - Input: `src/data/datascope_price_eod.parquet`, `src/data/datascope_yield_eod.parquet`
   - Output: `IPCA_Replication/outputs/bond_panel_monthly.parquet`
   - Key fields: `RIC`, `month_end`, `price`, `yield`, `price_return`

2. `03_02a_treasury_hedge.py`
   - Input: `outputs/bond_panel_monthly.parquet`,
     `src/data/wrds_eod_us_treasury_monthly.parquet` (optional)
   - Output: `outputs/treasury_monthly_return.parquet`,
     `outputs/bond_panel_monthly_with_treasury.parquet`
   - Key fields: `treasury_ret`, `credit_excess_return`

3. `03_02c_clean_after_hedge.py`
   - Input: `outputs/bond_panel_monthly_with_treasury.parquet`
   - Output: `outputs/bond_panel_monthly_clean.parquet`
   - Action: drop missing `credit_excess_return`, winsorise at 1%/99%

## Stage 04 — Spread/Duration Panel (YieldBook)

4. `04_01a_build_monthly_spread_duration.py`
   - Input: `src/data/yieldbook_price_yield.parquet`
   - Output: `outputs/yieldbook_spread_duration_monthly.parquet`
   - Key fields: `RIC`, `month_end`, `OAS`, `Duration`

5. `04_02a_merge_spread_duration.py`
   - Input: `outputs/bond_panel_monthly_clean.parquet`,
     `outputs/yieldbook_spread_duration_monthly.parquet`
   - Output: `outputs/bond_panel_monthly_clean_with_spread_duration.parquet`

6. `04_02c_clean_spread_duration.py`
   - Input: `outputs/bond_panel_monthly_clean_with_spread_duration.parquet`
   - Output: `outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet`
   - Action: drop fully-missing RICs; ffill/bfill OAS, Duration, price, yield

## Stage 05 — Characteristics (Groups A–D → All)

7. `05_02a_characteristics_group_a_static.py`
   - Input: `outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet`,
     `src/data/yieldbook_indicatives.parquet`
   - Output: `outputs/characteristics_group_a.parquet`
   - Group A: `bond_age`, `coupon`, `face_value`, `duration`, `spread`, `rating`

8. `05_02b_characteristics_group_b_rolling.py`
   - Input: base panel + Group A + `yieldbook_indicatives`
   - Output: `outputs/characteristics_group_b.parquet`
   - Group B: bond momentum, skewness, volatility, VaR, etc.

9. `05_02c_characteristics_group_c_firm.py`
   - Input: base panel + `yieldbook_indicatives`,
     `fmp_hist_financial_statements`, `fmp_enterprise_valuations_ratings`,
     `norgate_eod_stock_prices`, `datascope_characteristic_eod`
   - Output: `outputs/characteristics_group_c.parquet`
   - Group C: financials, equity momentum/volatility, distance-to-default

10. `05_02d_characteristics_group_b_dependent.py`
    - Input: base panel + Group C
    - Output: `outputs/characteristics_group_d.parquet`
    - Group D: `spread_to_d2d`

11. `05_02e_build_all.py`
    - Input: `characteristics_group_a/b/c/d.parquet`
    - Output: `outputs/characteristics_all.parquet`
    - Adds `constant` and orders 28 characteristics (VIX beta excluded)

## Stage 06 — IPCA Panel + Estimation (v1, 28 characteristics)

12. `06_01_panel_construction.py`
    - Input: `outputs/characteristics_all.parquet`,
      `outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet`
    - Output: `outputs/ipca_panel_input.parquet`,
      `outputs/ipca_monthly_counts.parquet`
    - Action: DtS scaling, rank-standardisation, imputation, MIN_BONDS filter (50)

13. `06_02_ipca_estimation.py`
    - Input: `outputs/ipca_panel_input.parquet`
    - Output: `outputs/ipca_insample/gamma_beta_K1..K5.parquet`,
      `outputs/ipca_insample/factors_K1..K5.parquet`,
      `outputs/ipca_insample/insample_metrics.csv`

14. `06_03_ipca_oos.py`
    - Input: `outputs/ipca_panel_input.parquet`
    - Output: `outputs/ipca_oos/oos_fitted_K1..K5.parquet`,
      `outputs/ipca_oos/oos_metrics.csv`

15. `06_04_ipca_portfolios.py`
    - Reads pre-saved `outputs/ipca_portfolios/oos_port_data_K5.parquet` and
      `outputs/ipca_portfolios/oos_factors_K5.parquet`
    - Output: `outputs/ipca_portfolios/spread_returns.csv`,
      `outputs/ipca_portfolios/tangency_sharpe.csv`
    - Note: the script does **not** run the OOS loop; it only builds portfolios
      from saved OOS betas/factors.

## Stage 07 — IPCA Panel + Estimation (v2, 8 characteristics, 2004+)

16. `07_01_panel_construction_v2.py`
    - Input: same as `06_01`, but keeps 8 characteristics with full 2004+ coverage
    - Output: `outputs_v2/ipca_panel_input_v2.parquet`,
      `outputs_v2/ipca_monthly_counts_v2.parquet`
    - Action: DtS scaling, rank-standardisation, imputation, MIN_BONDS filter (30)

17. `07_02_ipca_estimation_v2.py` (placeholder)
18. `07_03_ipca_oos_v2.py` (placeholder)
19. `07_04_ipca_portfolios_v2.py` (placeholder)

## Notebooks and Sensechecks

- `00_data_snapshot.ipynb` — data coverage and missingness
- `03_01b_sensecheck_bond_panel.ipynb` / `03_02b_sensecheck_hedge_panel.ipynb`
- `03_02d_sensecheck_clean_panel.ipynb`
- `04_01b_sensecheck_spread_duration.ipynb`
- `04_02b_sensecheck_merged_spread_duration.ipynb`
- `04_02d_sensecheck_clean_spread_duration.ipynb`
- `05_01_characteristics_inventory.ipynb`
- `05_03_characteristics_output_overview.ipynb`
- `06_05_results_overview.ipynb`
- `07_05_results_overview_v2.ipynb` (empty placeholder)

## Key Identifiers

- Panel key: `RIC` + `month_end`
- Datascope daily inputs use `Trade Date`
- YieldBook uses `PricingDate`
- FMP uses `filingDate` and `date` (monthly endpoints)
- Norgate uses `Date` (equity prices)


