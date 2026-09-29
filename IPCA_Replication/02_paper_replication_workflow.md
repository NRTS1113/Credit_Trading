# Replication Workflow: "Modeling Corporate Bond Returns" (Kelly, Palhares, Pruitt, 2021)

This document translates the paper into a concrete, reproducible workflow using the
data available under `src/data`. It also highlights mismatches between the paper's
data requirements (**ICE/IDC corporate bond analytics**) and the current local datasets.

## 1. Paper Summary (What We Need to Replicate)

The paper estimates an **IPCA (Instrumented PCA)** model for corporate bond returns with
**time-varying betas** driven by bond and issuer characteristics.

<u><strong>Key empirical elements</strong></u>:

- **Frequency:** **monthly** bond returns (credit excess returns).
- **Universe:** US corporate bonds in **ICE/IDC (1999-2020)**, proxied by **BofA IG/HY** indices.
- **Return scaling:** **monthly credit excess return** divided by **max(DtS, 0.25)**, where
  **DtS = duration × spread**.
- **Instruments (characteristics):** 29 bond/firm characteristics, cross-sectionally
  rank standardized each month to the range **[-0.5, 0.5]**, plus a **constant**.
- **Estimation:** IPCA with K factors (benchmark K=5), expanding window OOS with a
  **36-month burn-in**. Factors recovered each month via **cross-sectional regression**.
- **Benchmarks:** observable factor models (**MKT**, **BBW**, **FF**) using **rolling 36-month betas**.
- **Tests:** model fit (**Total/TS/CS R2**, **relative pricing error**), **managed portfolios**,
  **size/maturity** and **industry** portfolios, and **systematic strategy Sharpe ratios**.

## 2. Required Data and Frequency

Minimum data needed to implement the paper:

1. **Monthly** bond returns (credit excess return): price change plus coupons, hedged to
   remove pure rate exposure, for each bond and **month**.
2. **Monthly** bond analytics: **duration** and **spread** (for **DtS** scaling).
3. **Monthly** bond characteristics (29 in total, including **spread**, **duration**, **bond
   volatility**, **spread-to-distance-to-default**, **ratings**, **momentum**, etc.).
4. Bond identifiers: stable bond ID (**RIC/CUSIP/issue ID**) and dates.
5. Optional: issuer equity data for **equity momentum** and **equity volatility**.

The paper is fundamentally **monthly**. **Daily** data can be used but must be aggregated
to **month-end** values, and returns must be constructed at the **monthly** horizon.

## 3. What We Have in `src/data` (Quality Snapshot)

Based on `src/data/data_quality_report.txt`:

- `datascope_price_eod.parquet`
  - 2,193,461 rows x 13 columns
  - Trade Date range: **2002-01-31** to **2025-09-30**
  - Missing rate: **5.58%**
- `datascope_yield_eod.parquet`
  - 2,193,461 rows x 8 columns
  - Trade Date range: **2002-01-31** to **2025-09-30**
  - Missing rate: **5.77%**
- `datascope_characteristic_eod.parquet`
  - 2,193,461 rows x 26 columns
  - Trade Date range: **2002-01-31** to **2025-09-30**
  - Missing rate: **~0%**
- `yieldbook_price_yield.parquet`
  - 87,833 rows x 71 columns
  - Missing rate: **0.55%**
- `norgate_eod_stock_prices.parquet`
  - 2,906,856 rows x 10 columns
  - Missing rate: **0%**
- `fmp_hist_financial_statements.parquet`
  - 12,622 rows x 386 columns (high missingness in many fields)

The exploratory notebook `notebooks/00_data_snapshot.ipynb` documents the **panel-like**
structure of these files and confirms that **`RIC` + `Trade Date`** aligns across the
Datascope EOD datasets.

## 4. Mapping Paper Requirements to Available Data

Paper requirement -> Available local data (gap assessment):

- **Monthly credit excess return:** **NOT** directly present.
  - We only have EOD prices/yields, not ICE credit excess returns.
  - Action: Construct **monthly total returns** from EOD prices, and if possible
    hedge with **Treasury returns** to approximate excess returns.
- **Duration and spread (DtS):** partially present.
  - `yieldbook_price_yield.parquet` has OAS and Duration fields (monthly-ish).
  - Datascope EOD does not include spreads directly in the EOD price table.
  - Action: Use **YieldBook** as the source for **spread** and **duration**; join by **RIC** and date.
- **Characteristics (29):** partially present.
  - `datascope_characteristic_eod.parquet` has issuer/bond metadata (not the full 29).
  - `yieldbook_price_yield.parquet` has OAS, Duration, and other yield analytics.
  - `fmp_hist_financial_statements.parquet` provides issuer financials for some firm-level
  variables, but coverage is likely sparse.
  - `norgate_eod_stock_prices.parquet` supports equity momentum and volatility.
  - Action: Use a **reduced** characteristic set to start, then expand.

## 5. Proposed Replication Workflow (Using Current Data)

This section maps each step to the **actual files** in `IPCA_Replication/`.

### 5.0 Data Snapshot and Coverage Review

**Notebook:** `notebooks/00_data_snapshot.ipynb`

Use this to confirm available columns, date ranges, and missingness before running
any transformations.

What to check:
- File coverage by **RIC / CUSIP / Trade Date**
- Min/max dates and missingness for price/yield/characteristics
- Whether datasets align at the **daily** level before aggregation

### 5.1 Pipeline Map (Inventory + Run Order)

**Doc:** `notebooks/01_pipeline_map.md`

Summary of data inputs/outputs, working-directory assumptions, and a safe run order.

What to confirm:
- Which files are **read-only** vs. **written**
- Current repo limitations (missing upstream mapping files)
- Known execution issues (corrupt parquet, missing reconciliation)

### 5.2 Workflow (Paper → Code Mapping)

**Doc:** `IPCA_Replication/02_paper_replication_workflow.md`

Design document translating the paper into concrete steps using the current repo.

What to confirm:
- Paper requirements vs. our available proxies
- Which steps are **approximate** (credit excess return, DtS scaling)
- Which steps are **missing** (full 29 characteristics, benchmark models)

### 5.3 03-series: Returns + Hedge + IPCA

- `IPCA_Replication/03_01a_build_monthly_bond_panel.py`
- `IPCA_Replication/03_01b_sensecheck_bond_panel.ipynb`
- `IPCA_Replication/03_02a_treasury_hedge.py`
- `IPCA_Replication/03_02b_sensecheck_hedge_panel.ipynb`
- `IPCA_Replication/03_02c_clean_after_hedge.py`
- `IPCA_Replication/03_02d_sensecheck_clean_panel.ipynb`
- `IPCA_Replication/03_03_ipca_replication.ipynb`

Build the monthly bond return panel, hedge with Treasuries, clean, and run IPCA.

Inputs:
- `src/data/datascope_price_eod.parquet`
- `src/data/datascope_yield_eod.parquet`
- `src/data/wrds_eod_us_treasury_monthly.parquet` (if available)

Outputs:
- `IPCA_Replication/outputs/bond_panel_monthly.parquet`
- `IPCA_Replication/outputs/bond_panel_monthly_with_treasury.parquet`
- `IPCA_Replication/outputs/bond_panel_monthly_clean.parquet`

Key fields:
- `RIC`, `month_end`, `price`, `yield`, `price_return`, `credit_excess_return`

### 5.4 04-series: Spread/Duration Panel

- `IPCA_Replication/04_01a_build_monthly_spread_duration.py`
- `IPCA_Replication/04_01b_sensecheck_spread_duration.ipynb`
- `IPCA_Replication/04_02a_merge_spread_duration.py`
- `IPCA_Replication/04_02b_sensecheck_merged_spread_duration.ipynb`
- `IPCA_Replication/04_02c_clean_spread_duration.py`
- `IPCA_Replication/04_02d_sensecheck_clean_spread_duration.ipynb`

Extract OAS and duration from YieldBook, merge with returns, and clean.

Inputs:
- `src/data/yieldbook_price_yield.parquet`
- `IPCA_Replication/outputs/bond_panel_monthly_clean.parquet`

Outputs:
- `IPCA_Replication/outputs/yieldbook_spread_duration_monthly.parquet`
- `IPCA_Replication/outputs/bond_panel_monthly_clean_with_spread_duration.parquet`
- `IPCA_Replication/outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet`

Key fields:
- `RIC`, `month_end`, `OAS`, `Duration`, `price`, `yield`

### 5.5 05-series: Characteristics Inventory + Build

- `IPCA_Replication/05_01_characteristics_inventory.ipynb`
- `IPCA_Replication/05_02a_build_characteristics.py`
- `IPCA_Replication/05_02c_sensecheck_characteristics.ipynb`

Inventory available characteristics, build a reduced monthly set, and sensecheck.

Inputs:
- `src/data/yieldbook_price_yield.parquet`
- `src/data/yieldbook_indicatives.parquet`
- `src/data/fmp_hist_financial_statements.parquet`
- `src/data/norgate_eod_stock_prices.parquet`

Outputs:
- `IPCA_Replication/outputs/bond_characteristics_monthly.parquet`

Key fields (current reduced set):
- `RIC`, `month_end`, `bond_age`, `CurrentCoupon`, `face_value`
- `EffectiveDuration`, `OAS`, `bond_momentum_6m`
- `equity_momentum_6m`, `equity_volatility`
- `book_to_price`, `debt_to_ebitda`, `book_leverage`, `firm_total_debt`, `equity_mkt_cap`

### 5.6 Planned: DtS Scaling + Rank Standardization (Not Built Yet)

Use `DtS = Duration × OAS` to scale returns and rank‑standardize characteristics
cross‑sectionally to **[-0.5, 0.5]** each month.

Planned inputs:
- `bond_panel_monthly_clean_with_spread_duration_filtered.parquet`
- `bond_characteristics_monthly.parquet`

Planned outputs:
- `bond_panel_monthly_scaled.parquet`
- `bond_characteristics_monthly_ranked.parquet`

### 5.7 Planned: Portfolio Tests + Benchmarks (Not Built Yet)

Construct characteristic‑sorted portfolios and benchmark models (e.g., MKT/BBW/FF)
for comparison with paper tables and Sharpe ratios.

Planned outputs:
- Managed portfolio return tables
- Benchmark regression tables
- Summary metrics (Total/TS/CS R2, pricing error)

## 6. Minimum Data Checklist (What We Must Have)

To do a credible replication with this repo:

- `datascope_price_eod.parquet` (**monthly** price construction)
- `yieldbook_price_yield.parquet` (**duration**, **spread/OAS**)
- `datascope_characteristic_eod.parquet` (**bond identifiers**, metadata)
- `norgate_eod_stock_prices.parquet` (**equity momentum/volatility**)
- `wrds_eod_us_treasury_monthly.parquet` (**Treasury hedge**, if present)

If **Treasury** data is missing, you can still run **IPCA** on **price-only returns**,
but it will not be the paper's **credit excess return** design.

## 7. Known Gaps vs. the Paper

- The paper uses **ICE/IDC** data with proprietary analytics and a specific bond universe.
- Our data are from **Datascope + YieldBook**; coverage and definitions differ.
- Some required characteristics (**distance-to-default**, **bond volatility**, etc.)
  may not be fully reconstructable from current fields.
- Therefore, expect a **partial replication** focused on methodology rather than
  exact numeric matches.

## 8. Concrete Run Order in This Repo

1. `03_01a_build_monthly_bond_panel.py` → `03_01b_sensecheck_bond_panel.ipynb`
2. `03_02a_treasury_hedge.py` → `03_02b_sensecheck_hedge_panel.ipynb`
3. `03_02c_clean_after_hedge.py` → `03_02d_sensecheck_clean_panel.ipynb`
4. `04_01a_build_monthly_spread_duration.py` → `04_01b_sensecheck_spread_duration.ipynb`
5. `04_02a_merge_spread_duration.py` → `04_02b_sensecheck_merged_spread_duration.ipynb`
6. `04_02c_clean_spread_duration.py` → `04_02d_sensecheck_clean_spread_duration.ipynb`
7. `05_01_characteristics_inventory.ipynb` (review columns / gaps)
8. `05_02a_build_characteristics.py` → `05_02c_sensecheck_characteristics.ipynb`
9. `03_03_ipca_replication.ipynb`

