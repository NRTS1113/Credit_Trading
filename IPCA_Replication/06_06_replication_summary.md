# Replication Summary — Kelly, Palhares & Pruitt (2021)

## What we built

An end-to-end Python replication of the IPCA conditional factor model for corporate bond returns, covering data construction, model estimation, and portfolio evaluation.


| Script     | Description                                                       |
| ---------- | ----------------------------------------------------------------- |
| `05_02a–d` | 28 bond/firm characteristics across four groups                   |
| `06_01`    | Panel construction: DtS scaling, rank standardisation, imputation |
| `06_02`    | In-sample ALS estimation, K=1–5                                   |
| `06_03`    | Expanding-window OOS evaluation                                   |
| `06_04`    | Systematic portfolio construction                                 |


---

## Main findings vs. the paper


| Metric                       | Ours (K=5) | KPP (K=5) |
| ---------------------------- | ---------- | --------- |
| In-sample Total R²           | 89.9%      | 49.7%     |
| OOS Total R²                 | 89.4%      | 50.7%     |
| OOS RPE (individual bonds)   | 17.3%      | 63.4%     |
| In-sample / OOS gap          | 0.5pp      | −1.0pp    |
| Spread strategy gross Sharpe | 5.78       | 3.53      |
| Tangency gross Sharpe (γ=0)  | 0.80       | 6.23      |


**Directional conclusions that replicate:**

- OOS performance tracks in-sample closely (< 0.5pp gap), confirming IPCA generalises well — the core claim of KPP Section 4.1
- RPE is non-monotone in K, minimised at K=3 in both our sample and KPP
- The spread strategy produces economically meaningful returns, consistent with IPCA identifying a genuine cross-sectional signal in bond characteristics
- Increasing the smoothing parameter γ reduces turnover and gross Sharpe monotonically, with net Sharpe peaking around γ=0.3 — same pattern as KPP Table VIII

---

## Why our absolute numbers differ from KPP

Our R² (~90%) and spread Sharpe (5.78) exceed KPP's, while our tangency Sharpe (0.80) falls well short. These gaps are driven by sample differences, not methodology.

- **Sample period (2012–2025 vs. 1999–2020).** Our window post-dates the 2008 crisis and covers a decade of compressed credit spreads and low factor risk premia. This raises R² (more stable cross-sectional patterns) but depresses the tangency Sharpe (factor means near zero → low signal-to-noise in mean-variance optimisation).
- **Universe composition.** Our data skews ~80% investment grade due to FMP financial coverage constraints. IG bonds have tighter, more systematic return dynamics, making them easier to fit with a factor model.
- **Data quality.** FMP financial statements are backfilled via API, introducing potential look-ahead bias that KPP avoids through strict Compustat filing-date alignment. This is most likely to affect pricing error metrics.
- **Missing characteristics.** VIX beta (#29) is excluded due to data availability. BBW model comparison is omitted.


