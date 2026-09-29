# Contributions — Post-Replication Work (Leo)

This document summarises the work added on top of the existing IPCA replication
(commit `b3b4b7e`, Shirui). It covers three areas: pipeline bug fixes, new analysis
notebooks, and the resulting changes to reported metrics.

---

## 1. Bug Fixes

### 1a. Look-ahead bias in rolling characteristics (`05_02b`)

The original script computed rolling bond characteristics (momentum, volatility,
skewness, VaR) using windows that included the current period's return. Because
these characteristics enter the IPCA signal at month `t`, including `r_t` in their
construction means the signal implicitly knows the return it is trying to predict.

**Fix:** Shifted all rolling windows to end at `t-1` (i.e., exclude the current
month's return before computing the rolling window).

### 1b. Look-ahead bias in industry momentum (`05_02d`)

Industry momentum was computed using the contemporaneous cross-sectional median
spread within each industry group, rather than the lagged median. This caused the
characteristic at month `t` to embed information about peer bond returns at `t`.

**Fix:** All industry-level aggregations now use the lagged (prior-month)
cross-sectional median.

### 1c. CUSIP merge for industry codes (`06_01`)

Panel construction merged industry codes from the YieldBook indicatives file using
the `RIC` column, which is entirely null in that dataset. As a result, no bond
received an industry code and the industry characteristics were zeroed out for the
full panel.

**Fix:** Merge on `CUSIP` instead of `RIC`. Post-fix industry code coverage is ~87%.

---

## 2. New Analysis Notebooks

### 2a. Covariance analysis (`06_07_covariance_analysis.ipynb`)

Characterises the structure of the K=5 IPCA model:

- **Characteristic correlation heatmap** — identifies collinear inputs (e.g., duration
  and spread clusters) that may create redundancy in Γ.
- **Factor covariance matrix** — documents non-zero off-diagonal correlations among
  the five latent factors. f1–f2 correlation = 0.54, f1–f4 = 0.45. Factors are not
  orthogonal because they share duration exposure; IPCA imposes no orthogonality
  constraint (unlike PCA).
- **Implied beta covariance** — propagates Γ through the factor covariance to get
  the model-implied cross-sectional spread in expected returns.
- **Characteristic importance ranking** — top-5 absolute Γ entries: `constant`,
  `spread`, `duration`, `equity_market_cap`, `equity_volatility`.
- **Factor interpretation via Γ loadings:**

| Factor | Dominant loadings | Interpretation |
|--------|-------------------|----------------|
| f1 | constant (−0.87) | Market / level |
| f2 | duration (−0.59), spread (+0.45) | IG vs. HY spread |
| f3 | spread (+0.81) | Pure credit spread |
| f4 | duration (+0.60) | Rate sensitivity |
| f5 | spread_to_d2d (+0.47), equity_vol (−0.39) | Distress / mispricing |

### 2b. Full backtest (`06_08_backtest.ipynb`)

End-to-end OOS backtest of the K=5 model over 118 months (Dec 2015 – Sep 2025).

**Signal correction.** The previous backtest (`06_04`) sorted bonds on
`β̂_{i,t}' f̂_t` — the fitted value using the *same period's* recovered factor.
Since `f̂_t` is estimated from a cross-section regression on `r_t`, sorting on it
is equivalent to sorting on realised returns. This produces Sharpe ≈ 5.78 but is
circular. The corrected signal is `β̂_{i,t}' λ̂_t`, where `λ̂_t` is the
expanding-window mean of OOS factor realisations up to `t-1` (no look-ahead).
A 12-month burn-in is required before `λ̂_t` is stable, reducing the test window
from 130 to 118 months.

**Transaction costs and turnover.** The quintile sort tracks long-book (Q5) and
short-book (Q1) RIC membership month-to-month. Monthly one-way turnover is
computed as the fraction of each book replaced, and 19bps is deducted per unit of
turnover. Mean monthly turnover is 47.4%, producing a TC drag of 2.14% p.a.

**Sections implemented:**
1. Full-period performance summary (gross and net)
2. Subperiod analysis (pre-COVID, COVID shock, recovery, rate hike cycle, post-hike)
3. Drawdown analysis
4. Factor exposure regression — regresses strategy returns on market and Treasury
   factors to decompose alpha from systematic rate/credit exposure
5. Rolling 24-month Sharpe
6. Signal-to-noise decomposition — quantifies why high R² does not translate to
   portfolio Sharpe
7. Tangency portfolio comparison — re-implements the `06_04` tangency with
   corrected expanding window (`hist < t`) and 19bps TC, side-by-side with the
   quintile spread

---

## 3. Results

### 3a. R² metrics — before and after fixes

| Metric (K=5) | Previous (pre-fix) | Updated (post-fix) | KPP ref |
|---|---|---|---|
| In-sample Total R² | 89.9% | 89.0% | 49.7% |
| OOS Total R² | 89.4% | 88.7% | 50.7% |
| In-sample RPE | 18.6% | 94.4% | 60.4% |
| OOS RPE | 17.3% | 90.7% | 63.4% |

**Total R²** changed by less than 1pp — the look-ahead fix removes only a small
amount of spurious variance.

**RPE** increased dramatically. RPE = Σα̂ᵢ² / Σr̄ᵢ² measures how well the model
explains *average return differences* across bonds (pricing error in the
cross-sectional mean, not variance). The previous low RPE (14–27%) was
anomalously below KPP (52–63%) because the look-ahead in rolling characteristics
was allowing the factor structure to absorb cross-sectional mean returns. Post-fix,
RPE of ~90% is above KPP, reflecting that the model captures return covariance well
but struggles to explain the level of expected returns — consistent with compressed
post-GFC risk premia.

### 3b. Portfolio performance — before and after fixes

| Strategy | Previous | Corrected | KPP ref |
|---|---|---|---|
| Quintile spread — gross Sharpe | 5.78 *(circular signal)* | **−0.08** | 3.53 |
| Quintile spread — net Sharpe (19bps, 47% TO) | — | **−0.16** | — |
| Tangency γ=0 — gross Sharpe | 0.80 *(hist ≤ t)* | **−0.04** | 6.23 |
| Tangency γ=0.3 — net Sharpe (19bps) | 0.53 *(hist ≤ t)* | **−0.07** | 2.93 |

All three previous Sharpe figures were artefacts:

- **5.78**: signal `β̂'f̂_t` uses the current period's factor recovery, which is a
  regression fit to `r_t`. Sorting on `β̂'f̂_t` is equivalent to sorting on
  in-sample fitted values — not a forward-looking signal.
- **0.80 / 0.53**: the tangency computed `μ = mean(hist)` with `hist` including
  month `t`. Portfolio weights are tilted toward factors that happened to be
  positive this period, generating ~1.1bps/month of look-ahead profit. Removing
  this drops the Sharpe from 0.80 to −0.04.
- **0.07** (intermediate quintile result): used `λ̂ = mean(F_insample)` where the
  in-sample factors span the full panel including the OOS test period. Switching to
  expanding-window `λ̂_t` (hist < t) shifts the gross Sharpe to −0.08.

**Turnover and transaction costs.** Mean monthly turnover of the quintile spread is
47.4% — nearly half the long and short books are replaced each month. At 19bps
one-way this produces a TC drag of 2.14% p.a., pushing the net Sharpe to −0.16.
High turnover confirms that the signal `β̂'λ̂_t` is not persistent enough to
support a low-cost implementation at monthly frequency.

### 3c. Signal-to-noise

The root cause of the low corrected Sharpe is not the portfolio construction but
the size of the risk premia in our sample period:

| Factor | Monthly λ̂ | Annualised |
|--------|-----------|-----------|
| f1 | 0.65% | 7.8% |
| f2 | 1.43% | 17.2% |
| f3 | 1.44% | 17.3% |
| f4 | 0.39% | 4.7% |
| f5 | 0.89% | 10.6% |

The cross-sectional standard deviation of the signal (`β̂'λ̂`) averages 0.0046,
versus a cross-sectional standard deviation of realised returns of 0.0578 —
a signal-to-noise ratio of **0.08**. Idiosyncratic noise is 11× larger than the
predictive signal, so even a correctly-specified model produces a near-zero
sorting Sharpe. This is consistent with the post-GFC compression of credit risk
premia documented in the literature.

---

## 5. Performance Gap vs. KPP — Analysis and Proposed Improvements

### 5a. Why our portfolio Sharpe is lower

The IPCA model itself replicates well — OOS Total R² of 88.7% vs KPP's 50.7%, and
the factor structure is economically interpretable. The gap is entirely in portfolio
performance (Sharpe −0.08 vs KPP's 3.53). Four compounding factors explain this.

**i. Sample period misses elevated risk premia**

KPP's sample (1999–2020) spans the dot-com bust, the GFC, and their aftermath — a
period of wide credit spreads and high factor risk premia. Our sample (2015–2025)
is post-GFC, characterised by central bank suppression of volatility and compressed
credit spreads. The signal `β̂'λ̂` is only useful when `λ̂` is large; if factors
earn near-zero premia, sorting on expected betas generates no return regardless of
how accurately Γ is estimated.

A rough comparison: to match KPP's quintile Sharpe of 3.53, our cross-sectional
SNR of 0.08 would need to be approximately 40× larger — implying factor premia
roughly 6× higher than observed in our sample.

**ii. Universe skew toward investment grade**

Our panel is ~80% IG due to FMP financial coverage constraints. IG bonds cluster
tightly in spread and duration, reducing the cross-sectional dispersion that IPCA
exploits. The quintile Q5–Q1 spread is narrow when the underlying return
distribution is compressed. KPP's universe includes a larger HY component with
wider spread dispersion and higher characteristic-driven return variation.

**iii. High RPE indicates weak cross-sectional pricing**

Our post-fix RPE of ~90% means the model's bond-level alpha (time-series mean
residual) is almost as large as the mean return itself. The factors explain
covariance well (R² ~89%) but not expected return differences across bonds. This
disconnect — high R², high RPE — is the hallmark of a variance decomposition that
has not identified true risk premia. In KPP's sample, the RPE of 60% reflects a
better alignment between characteristic loadings and realised premia.

**iv. Signal instability drives high turnover**

Monthly turnover of 47% implies that a bond's quintile rank changes frequently.
Two sources contribute:
- **Imputation noise:** spread_to_d2d, earnings_to_price, and book_leverage have
  30–70% imputation rates. Cross-sectional median fills reduce variation and
  introduce discontinuities when new data arrives.
- **Expanding λ̂ instability:** early in the test period λ̂_t is estimated on a
  short history, producing volatile weights that shift quintile rankings even when
  betas are stable.

---

### 5b. Proposed improvements

**1. Reduce rebalancing frequency**

The single highest-impact change for net performance. Quarterly rebalancing would
cut the 2.14% p.a. TC drag by roughly 3×. Alternatively, a persistence filter —
only rebalancing a bond out of Q5/Q1 if it moves by 2+ quintiles — would preserve
most of the signal while cutting turnover substantially.

**2. Apply a minimum issue size screen**

Filter to bonds with face value ≥ $250M (a common threshold for institutional
liquidity). This removes the smallest, most illiquid issues whose return noise
dominates the signal and whose bid-ask spreads in practice exceed the 19bps assumed
here.

**3. Hedge duration exposure**

The factor regression (Section 4) shows a Treasury coefficient of 6.4 (t = 1.8).
Going duration-neutral — matching the DV01 of the long and short books — would
reduce annualised vol from ~27% and isolate the pure credit spread signal. This
alone could improve the Sharpe materially even without changing gross returns.

**4. Focus on high-coverage characteristics**

The covariance analysis (06_07) shows spread, duration, equity_market_cap, and
equity_volatility dominate the Gamma matrix. Re-running IPCA on a pruned
characteristic set — dropping the heavily-imputed inputs — would reduce imputation
noise and produce a more stable signal.

**5. Rolling λ̂ window**

Replace the expanding-window λ̂_t with a rolling 36-month window. In a
regime-shifting sample (post-GFC → rate hike cycle), a long-history mean dilutes
recent premia. A 3-year rolling window is more responsive to the prevailing credit
environment and would produce better-calibrated signals during the 2022–2023 rate
hike cycle.

**6. Concentrate on high-dispersion regimes**

The subperiod analysis shows the model performs best during COVID (large spread
moves) and the rate hike cycle (high factor dispersion). A strategy that activates
only when cross-sectional return dispersion exceeds a threshold would concentrate
exposure to periods where SNR is highest, avoiding the compressed environments
where sorting generates no meaningful spread.

---

## 4. Remaining Limitations

- **Equal weighting:** Positions ignore issue size and liquidity. Weighting by
  face value or applying a minimum issue size screen would make the strategy more
  realistic and avoid small illiquid bonds that cannot be traded at quoted spreads.
- **Unhedged rate exposure:** The factor exposure regression shows a Treasury
  coefficient of 6.4 (t = 1.8). A duration-neutral implementation would reduce
  volatility and isolate the pure credit signal.
- **Rebalancing frequency:** 47% monthly turnover suggests the quintile ranking
  is highly unstable. Lower-frequency rebalancing (quarterly) or a signal
  persistence filter could reduce TC drag substantially.
