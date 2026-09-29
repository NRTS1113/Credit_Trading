# LSEG YieldBook REST API Guide

Comprehensive guide for using the YieldBook Price/Yield (PY) API for fixed income analytics.

## Table of Contents
- [API Modes](#api-modes)
- [PY Input Parameters](#py-input-parameters)
- [Response Structure](#response-structure)
- [Calculation Methodology](#calculation-methodology)
- [Flow 1 vs Flow 2](#flow-1-vs-flow-2)
- [Practical Examples](#practical-examples)

---

## API Modes

### 1. Synchronous Mode (Direct Response)
**Endpoint:** `/sync/bond/py`  
**Best for:** Quick, single calculations (< 30 seconds)

```python
py_url = api_url(endpoint="/bond/py", mode="sync")
py_response = rq.post(py_url, headers=api_headers(), json=py_request_body)
result = py_response.json()['data']
```

### 2. Asynchronous Mode (Request-Results Pattern)
**Endpoint:** `/req/bond/py`  
**Best for:** Long-running calculations (30+ seconds)

```python
# Step 1: Submit request
py_url = api_url(endpoint="/bond/py", mode="req")
response = rq.post(py_url, headers=api_headers(), json=py_request_body)
request_id = response.json()["requestId"]

# Step 2: Poll for results
results_url = api_url(endpoint=f"/results/{request_id}")
results = rq.get(results_url, headers=api_headers())
```

### 3. Bulk Template (Multiple Securities)
**Endpoint:** `/bulk/template?job={job_name}`  
**Best for:** Processing many securities with identical assumptions  
**Requires:** Job context

```python
bulk_url = api_url(endpoint=f"/bulk/template?job={job_name}", mode="req")
request_body = {
    "path": "/bond/py",
    "dataSource": {"requestId": "my_bonds_csv"},
    "body": {
        "globalSettings": {"pricingDate": "2024-11-15"},
        "input": [{
            "identifier.$": "$.CUSIP",
            "level.$": "$.PRICE",
            "curve": {"curveType": "SWAP"}
        }]
    }
}
```

### 4. Deferred Bulk Template (Chained Calculations)
**Endpoint:** `/bulk/template/async-beta?job={job_id}&dep={dependency}`  
**Best for:** Using results from previous calculations as inputs

```python
endpoint = f"/bulk/template/async-beta?job={job_id}&dep={result_table_name}"
# Uses results from previous PY to populate new PY inputs
```

---

## PY Input Parameters

### Global Settings
```python
"globalSettings": {
    "pricingDate": "2023-03-31",         # Settlement/pricing date
    "usePreviousClose": True,            # Use previous closing prices
    "retrievePPMProjection": "true"      # Get prepayment projections
}
```

### Security Input Array

#### **`identifier` / `idType`**
Specify the security to price.

```python
"identifier": "3136FAWE",
"idType": "securityIDEntry"  # CUSIP, ISIN, etc.
```

#### **`level`** ⭐ (Price or Yield Input)
The starting point for calculation.

**Formats:**
- **Price:** `"100"`, `"98.50"`, `"326.9409o"` (o = offer price)
- **Yield:** `"10y"` (10-year yield), `"3.5y"` (3.5% yield)
- **Spread:** Can specify OAS spread

**Usage:**
- **Flow 1 (Price → Yield/OAS):** Input market price → Get yield, OAS
- **Flow 2 (Yield → Price):** Input yield level → Get theoretical price

#### **`curve`** ⭐ (Discount Curve)
Defines the interest rate environment for valuation.

```python
# Standard curves
{"curveType": "SWAP"}         # Swap curve
{"curveType": "GVT"}          # Government curve
{"curveType": "SWAP_RFR"}     # Risk-free rate swap (SOFR)

# User-defined curves (requires job store)
{"userDefined": {"$ref": "my_swap_curve"}}

# Market snapshot reference
{"userDefined": {"$ref": "latest_market_snap#curve.USD.SWAP_RFR"}}
```

#### **`extraSettings`** ⭐ (Calculation Controls)
Fine-tune calculation methodology.

```python
"extraSettings": {
    "includePartials": False,              # Include partial/key rate durations
    "optionModel": "OASEDUR",             # Option pricing model
    "useOASToCall": False,                # Use OAS to call date
    "partialVega": False,                 # Calculate partial vegas
    "refiElbowDuration": False,           # Refinancing elbow duration
    "primarySecondarySpreadDuration": False
}
```

#### **`volatility`** (For OAS Calculation)
Volatility assumptions for option-adjusted metrics.

```python
{"type": "Default"}           # YieldBook default volatility
{"type": "LMMSOFRNEW"}       # LMM SOFR volatility model
```

#### **`prepaySettings`** (For MBS/ABS)
Prepayment model assumptions.

```python
"prepaySettings": {
    "type": "Model",          # Use YieldBook prepayment model
    "rate": 100              # CPR/PSA rate (100 = 100% of model speed)
}
```

#### **`settlementType`**
```python
"settlementType": "MARKET"    # Market settlement convention
```

#### **`userTag`**
Custom identifier for tracking results in bulk requests.

```python
"userTag.$": "$.CUSIP"        # Use CUSIP as tag
```

---

## Response Structure

```json
{
  "meta": {
    "requestId": "R-12345",
    "status": "DONE",
    "timeStamp": "2025-09-03T16:07:49Z",
    "responseType": "BOND_PY"
  },
  "data": {
    "cusip": "3136FAWE",
    "identifier": "3136FAWE",
    "ticker": "FNMA",
    "description": "FNMA POOL",
    "securityType": "MORT",
    
    "py": {
      // Price & Yield
      "price": 100.25,
      "fullPrice": 100.50,
      "cleanPrice": 100.25,
      "yield": 3.5,
      "yieldToMaturity": 3.5,
      "yieldToWorst": 3.4,
      "currentYield": 3.2,
      
      // Spread Measures
      "oas": 45.2,              // Option-adjusted spread (bp)
      "zSpread": 48.5,          // Zero-volatility spread (bp)
      
      // Duration & Convexity
      "duration": 5.2,          // Modified duration
      "effectiveDuration": 4.8, // Option-adjusted duration
      "dv01": 0.052,            // Dollar value of 1bp
      "convexity": 0.25,
      "effectiveConvexity": 0.22,
      "spreadDuration": 4.9,
      
      // Key Rate Durations (if includePartials=true)
      "keyRateDurations": {
        "2y": 0.8,
        "5y": 2.1,
        "10y": 1.9,
        "30y": 0.2
      },
      
      // Weighted Average Life
      "wal": 6.5,
      "effectiveWal": 6.2,
      
      // Settlement Information
      "accruedInterest": 0.25,
      "accruedDays": 45,
      "settlementDate": "2023-04-03",
      
      // Pricing Context
      "curveType": "SWAP",
      "pricingDate": "2023-03-31"
    }
  }
}
```

**Key Output Fields:**
- **`price`/`fullPrice`:** Clean and dirty (accrued included) prices
- **`oas`:** Option-adjusted spread - key relative value metric
- **`effectiveDuration`:** Most important risk measure for bonds with options
- **`dv01`:** Dollar risk per 1bp yield move
- **`wal`:** Average time to receive principal

---

## Calculation Methodology

### Step 1: Input Processing
1. **Retrieve** security characteristics from YieldBook database
2. **Load** discount curve (Government, Swap, or User-defined)
3. **Process** pricing level (price vs yield input)

### Step 2: Cash Flow Generation

#### Fixed-Rate Bonds
- Deterministic coupon schedule
- Principal at maturity

#### Callable Bonds
- Models call schedule
- Uses volatility input for option pricing
- Binomial tree or Monte Carlo method

#### Mortgage-Backed Securities (MBS)
- **YieldBook proprietary prepayment model**
- Factors:
  - Refinancing incentive (current rates vs pool coupon)
  - Loan age, seasonality, burnout
  - Pool characteristics (FICO, LTV, loan purpose)
  - Historical behavior

### Step 3: Valuation

#### Basic Price/Yield
```
Price = Σ [Cash Flow_t / (1 + Discount Rate_t)^t]
```

#### Option-Adjusted Spread (OAS)
For securities with embedded options:

1. **Build interest rate tree/paths** (binomial or Monte Carlo)
2. **Generate cash flows** on each path
   - MBS: Prepayments vary by interest rate path
   - Callable: Optimal exercise at each node
3. **Solve for OAS iteratively:**
   ```
   Market Price = Average[Path Values]
   where Path Value = Σ [CF_t / (1 + (Curve Rate + OAS))^t]
   ```

**OAS** is the constant spread that makes model price equal market price.

### Step 4: Risk Measures

#### Modified Duration
```
Duration = -(1/Price) × (∂Price/∂Yield)
```
Calculated by shocking yield ±1bp

#### Effective Duration (OAS Duration)
```
Effective Duration = -(1/Price) × (∂Price/∂Curve)
```
- Shocks entire curve ±25bp
- Recalculates prepayments/option values
- Reprices holding OAS constant

#### DV01
```
DV01 = Duration × Price × 0.0001
```

#### Convexity
```
Convexity = (1/Price) × (∂²Price/∂Yield²)
```

#### Weighted Average Life (WAL)
```
WAL = Σ [(Principal CF_t × Time_t) / Total Principal]
```

---

## Flow 1 vs Flow 2

### **Flow 1: Price → Yield & OAS**

**Input:** Market price → **Output:** Yield, OAS, Duration

**When to Use:**
- ✅ **Mark-to-market valuation** (you have traded prices)
- ✅ **Relative value analysis** (compare OAS across bonds)
- ✅ **Daily risk reporting** (calculate duration at current prices)
- ✅ **Trade analysis** (understand what yield/spread you locked in)

**Example:**
```python
"globalSettings": {
    "pricingDate": "2024-11-15"
},
"input": [{
    "identifier": "3136FAWE",
    "level": "100.25",              # ← Actual market price
    "curve": {"curveType": "SWAP"}
}]
# Output: yield=3.2%, OAS=45bp, effectiveDuration=4.8
```

**Should `level` be the real price on pricing date?**
- **Yes** for mark-to-market and risk reporting
- Use actual market close price from that date
- This gives you market-implied OAS and yield

### **Flow 2: Yield → Price**

**Input:** Yield level → **Output:** Theoretical price

**When to Use:**
- ✅ **Scenario analysis** ("What if 10-year yields hit 5%?")
- ✅ **Fair value pricing** (illiquid bonds using comparable yields)
- ✅ **New issue pricing** (price at launch yield)
- ✅ **Target pricing** ("What price do I need for 4% yield?")

**Example:**
```python
"globalSettings": {
    "pricingDate": "2024-11-15"
},
"input": [{
    "identifier": "3136FAWE",
    "level": "5y",                  # ← Yield scenario (5%)
    "curve": {"curveType": "SWAP"}
}]
# Output: price=95.20 (shows mark-to-market impact)
```

---

## Practical Examples

### Example 1: Daily Portfolio Risk Report (Flow 1)
```python
py_request = {
    "globalSettings": {
        "pricingDate": "2024-11-15",
        "usePreviousClose": True
    },
    "input": [
        {
            "identifier": "912810SQ2",
            "level": "98.50",              # Yesterday's closing price
            "curve": {"curveType": "GVT"},
            "volatility": {"type": "Default"},
            "extraSettings": {
                "optionModel": "OASEDUR",
                "includePartials": True    # Get key rate durations
            }
        }
    ]
}
# Use: Calculate portfolio DV01 and duration for risk limits
```

### Example 2: Relative Value Analysis (Flow 1)
```python
# Compare OAS across similar bonds to find cheap/rich
bulk_request = {
    "path": "/bond/py",
    "dataSource": {"requestId": "my_universe"},  # CSV with CUSIPs and prices
    "body": {
        "globalSettings": {"pricingDate": "2024-11-15"},
        "input": [{
            "identifier.$": "$.CUSIP",
            "level.$": "$.MARKET_PRICE",           # Current market prices
            "curve": {"curveType": "SWAP_RFR"}
        }]
    }
}
# Output: Screen for bonds with OAS > 100bp (potential buys)
```

### Example 3: Stress Testing (Flow 2)
```python
py_request = {
    "globalSettings": {"pricingDate": "2024-11-15"},
    "input": [
        {
            "identifier": "3136FAWE",
            "level": "5y",                         # Stress scenario: 5% yield
            "curve": {"curveType": "SWAP"},
            "prepaySettings": {
                "type": "Model",
                "rate": 150                        # Higher prepayments
            }
        }
    ]
}
# Use: Calculate portfolio value under stress scenarios
```

### Example 4: MBS Pool Analysis (Flow 1)
```python
py_request = {
    "globalSettings": {"pricingDate": "2024-11-15"},
    "input": [
        {
            "identifier": "31424U8L3",             # Specific pool
            "level": "102.50",                     # Market price
            "curve": {"curveType": "SWAP_RFR"},
            "prepaySettings": {
                "type": "Model",
                "rate": 100
            },
            "volatility": {"type": "LMMSOFRNEW"},
            "extraSettings": {
                "optionModel": "OASEDUR",
                "refiElbowDuration": True          # Refinancing sensitivity
            }
        }
    ]
}
# Output: OAS, effective duration, WAL, prepayment speeds
```

### Example 5: User Curve Scenario (Flow 1)
```python
# Step 1: Create job and upload shocked curve
# Step 2: Price bond with user curve
py_request = {
    "globalSettings": {"pricingDate": "2024-11-15"},
    "input": [
        {
            "identifier": "3136FAWE",
            "level": "100",
            "curve": {
                "userDefined": {"$ref": "shocked_swap_curve"}  # +50bp shock
            }
        }
    ]
}
# Use: Scenario analysis with custom rate shocks
```

---

## Decision Tree: Which Flow to Use?

```
Do you have a market price for the bond?
│
├─ YES → Flow 1: Input the price as "level"
│   │
│   ├─ Goal: Valuation/Risk Reporting
│   │   → Use actual market price from pricing date
│   │   → Output: OAS, duration for that price
│   │
│   └─ Goal: What-if Scenario
│       → Use hypothetical shocked price
│       → Output: Implied yield/OAS at that price
│
└─ NO → Flow 2: Input a yield as "level"
    │
    ├─ Use comparable yield (e.g., "10y")
    ├─ Use target yield for scenario
    └─ Output: Theoretical price at that yield
```

---

## Key Metrics Summary

| Metric | Description | When to Use |
|--------|-------------|-------------|
| **OAS** | Spread adjusted for optionality | Relative value comparison |
| **Effective Duration** | Price sensitivity with options | Primary risk measure for MBS/callable |
| **DV01** | Dollar risk per 1bp | Position sizing, hedging |
| **Effective WAL** | Expected time to receive principal | Duration proxy for MBS |
| **Key Rate Durations** | Non-parallel shift sensitivity | Curve positioning |
| **Convexity** | Curvature of price-yield | Large rate moves |

---

## Performance Notes

- **Sync mode:** Seconds for simple bonds
- **Async mode:** 30+ seconds for:
  - Multi-path OAS (Monte Carlo)
  - Large MBS pools
  - Complex ABS structures
- **Bulk mode:** Optimal for 100+ securities
  - Parallel processing
  - Job-based management

---

## Resources

- **API Documentation:** https://www.yieldbook.com/s/support/rest-api.shtml
- **Support:** support@yieldbook.com / 888-333-5618
- **Analytics Help:** howto@yieldbook.com / 888-333-5617
- **Example Notebooks:** `example_notebooks/` directory

---

## Quick Reference

### Basic PY Request Template
```python
py_request_body = {
    "globalSettings": {
        "pricingDate": "2024-11-15"
    },
    "input": [
        {
            "identifier": "CUSIP_HERE",
            "idType": "securityIDEntry",
            "level": "PRICE_OR_YIELD",
            "curve": {
                "curveType": "SWAP"
            },
            "volatility": {
                "type": "Default"
            },
            "extraSettings": {
                "optionModel": "OASEDUR"
            }
        }
    ]
}
```

### Level Input Formats
- **Price:** `"100"`, `"98.50"`, `"102.25o"`
- **Yield:** `"3.5y"`, `"10y"`
- **Special:** `"o"` suffix = offer price

### Common Curve Types
- `"GVT"` - Government (Treasury)
- `"SWAP"` - Swap curve
- `"SWAP_RFR"` - SOFR swap curve
- `"GVT_TSYM"` - Treasury symmetric curve

---

## PY Results Data Structure

### Security Identifiers & Attributes
CUSIP, Ticker, Description, SecurityType, MaturityDate, NextCallDate, CurrentCoupon

### Pricing Data
- **Clean/Dirty Pricing**: Price, FullPrice, AccruedInterest, AccruedDays
- **Dates**: PricingDate, SettlementDate

### Yield Calculations (10 variants)
- **Standard**: Yield, CurrentYield, EffectiveYield
- **Callable**: YieldToWorst, YieldToNextCall, YieldToWorstCall
- **Annualized**: AnnualizedYield, SemiAnnualizedYield, CDYield

### Spread Analytics (14 variants)
- **Option-adjusted**: OAS
- **Z-spreads**: ZSpread, ZISpread, ZNSpread
- **Relative value**: AssetSwapSpread, GrossSpread, YieldCurveMargin
- **Curve-relative**: SpreadToActCurve, SpreadToTsyCurve, SpreadToBenchmark, SpreadToSwapCurve, SpreadToRFRSwapCurve, SpreadToWorstCall

### Duration Metrics (11 variants)
- **Core**: Duration, EffectiveDuration, MacaulayDuration
- **Spread-based**: SpreadDuration, YieldCurveDuration, SpreadDurationTreasury
- **Scenario**: DurationToWorstCase, FundedEffectiveDuration
- **Directional**: EffectiveDurationPriceUp, EffectiveDurationPriceDown

### Convexity Metrics (7 variants)
Convexity, EffectiveConvexity, MacaulayConvexity, SpreadConvexity, ConvexityCost, ConvexityEffect, FundedEffectiveConvexity

### Sensitivity Measures
DV01, EffectiveDV01, EffectiveCV01, SpreadDV01

### Curve Configuration
- **Curve IDs**: CurveType, CurveDate, TsyCurveID, SwapCurveID, OptionModelCurveID
- **Benchmarks**: Benchmark, BenchmarkToNextCall

### Time & Exposure
WAL (Weighted Average Life), YearsToMaturity, YearsToFinalMaturity, EconomicExposure

### Model Parameters
VolModelType, CompoundingFreq

**Data Format**: Time-series CSV with multiple pricing dates per security for historical analysis and risk attribution.

---

**Last Updated:** 2025-10-20
