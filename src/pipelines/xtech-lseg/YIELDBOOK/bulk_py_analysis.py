"""
Bulk Price/Yield Analysis for Corporate Bonds using YieldBook API
Flow 1: Price → Yield, OAS, Duration, etc.

TWO MODES SUPPORTED:
====================

1. BATCH MODE (Default):
   - Waits for all calculations to complete
   - Retrieves all results at once
   - Usage: run_bulk_py_analysis(data, stream_results=False)

2. STREAMING MODE:
   - Retrieves partial results as calculations complete
   - Allows processing results incrementally
   - Can save/analyze results before all calculations finish
   - Usage: run_bulk_py_analysis(data, stream_results=True, stream_callback=your_callback)
   
Example streaming callback:
   def process_batch(partial_df, completed, total):
       print(f"Got {len(partial_df)} new results ({completed}/{total} done)")
       partial_df.to_csv(f"batch_{completed}.csv")
"""
# %%
import requests as rq
import pandas as pd
import time
from datetime import datetime
from typing import List, Dict, Optional
import io
import os
from tqdm import tqdm


class YieldBookBulkAnalyzer:
    """Handles bulk PY analysis for multiple bonds across multiple dates"""
    
    def __init__(self, api_id: str, api_key: str):
        self.api_id = api_id
        self.api_key = api_key
        self.api_base_url = "https://api.yieldbook.com/analytics/v2"
        self.access_token = None
        
    def authenticate(self):
        """Get access token for API authentication"""
        auth_url = "https://www.yieldbook.com/x/oauth/api-token"
        auth_config = {
            "client_id": self.api_id,
            "client_secret": self.api_key,
            "grant_type": "client_credentials",
            "audience": "API2-PROD"
        }
        
        response = rq.post(auth_url, params=auth_config)
        if response.status_code == 200:
            self.access_token = response.json().get("accessToken")
            print("✓ Successfully authenticated")
        else:
            raise Exception(f"Authentication failed: {response.text}")
    
    def _api_url(self, endpoint: str, mode: Optional[str] = None) -> str:
        """Construct API URL"""
        if not mode:
            return "/".join([self.api_base_url.strip("/"), endpoint.strip("/")])
        return "/".join([self.api_base_url.strip("/"), mode.strip("/"), endpoint.strip("/")])
    
    def _api_headers(self) -> Dict:
        """Get API headers with authentication"""
        return {
            'Accept': '*/*',
            'Authorization': f"Bearer {self.access_token}",
            'content-type': 'application/json'
        }
    
    def run_bulk_py_analysis(
        self,
        bonds_data: pd.DataFrame,
        job_name: str = "bulk_py_job",
        curve_type: str = "SWAP",
        output_fields: Optional[List[str]] = None,
        stream_results: bool = False,
        stream_callback: Optional[callable] = None
    ) -> pd.DataFrame:
        """
        Run bulk PY analysis for bonds with prices
        
        Args:
            bonds_data: DataFrame with columns [CUSIP, PricingDate, Price]
            job_name: Name for the job
            curve_type: Curve type (SWAP, GVT, etc.)
            output_fields: List of fields to retrieve from results
            stream_results: If True, retrieve results as they complete (default: False)
            stream_callback: Function to call for each batch of results (optional)
                           Signature: callback(partial_df: pd.DataFrame, completed: int, total: int)
            
        Returns:
            DataFrame with PY analytics results
        """
        if self.access_token is None:
            self.authenticate()
        
        # Validate input data
        required_cols = ['CUSIP', 'PricingDate', 'Price']
        if not all(col in bonds_data.columns for col in required_cols):
            raise ValueError(f"bonds_data must have columns: {required_cols}")
        
        print(f"Starting bulk PY analysis for {len(bonds_data)} records...")
        
        # Step 1: Create job
        job_id = self._create_job(job_name)
        
        # Step 2: Upload data to job store
        self._upload_data_to_job_store(job_name, bonds_data)
        
        # Step 3: Submit bulk PY template
        self._submit_bulk_py_template(job_name, curve_type)
        
        # Step 4: Close job
        self._close_job(job_name)
        
        # Step 5: Wait for completion (with optional streaming)
        if stream_results:
            all_results = self._wait_and_stream_results(
                job_id, job_name, output_fields, stream_callback
            )
            results_df = all_results
        else:
            self._wait_for_job_completion(job_id)
            # Step 6: Retrieve results
            results_df = self._retrieve_results(job_name, output_fields)
        
        print(f"✓ Analysis complete. Retrieved {len(results_df)} results")
        return results_df
    
    def _create_job(self, job_name: str) -> str:
        """Create a new job"""
        url = self._api_url(endpoint="/jobs")
        response = rq.post(url, headers=self._api_headers(), json={"name": job_name})
        
        # Accept both 200 and 201 as success
        if response.status_code in [200, 201]:
            job_id = response.json()["id"]
            print(f"✓ Created job '{job_name}' (ID: {job_id})")
            return job_id
        else:
            raise Exception(f"Failed to create job (status {response.status_code}): {response.text}")
    
    def _upload_data_to_job_store(self, job_name: str, bonds_data: pd.DataFrame):
        """Upload bonds data to job store as CSV"""
        table_name = "bonds_input"
        url = self._api_url(endpoint=f"/job-store/{job_name}/table/{table_name}")
        
        # Convert DataFrame to CSV string
        csv_buffer = io.StringIO()
        bonds_data.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()
        
        headers = {
            'Accept': '*/*',
            'Authorization': f"Bearer {self.access_token}",
            'Content-type': 'application/csv'
        }
        
        response = rq.put(url, headers=headers, data=csv_data)
        if response.status_code in [200, 201, 204]:
            print(f"✓ Uploaded {len(bonds_data)} records to job store")
        else:
            raise Exception(f"Failed to upload data (status {response.status_code}): {response.text}")
    
    def _submit_bulk_py_template(self, job_name: str, curve_type: str):
        """Submit bulk PY template request"""
        url = self._api_url(endpoint=f"/bulk/template?job={job_name}", mode="req")
        
        request_body = {
            "path": "/bond/py",
            "dataSource": {
                "requestId": "bonds_input"
            },
            "body": {
                "globalSettings": {
                    "pricingDate.$": "$.PricingDate"
                },
                "input": [{
                    "idType": "cusip",
                    "identifier.$": "$.CUSIP",
                    "userTag.$": "$.CUSIP",
                    "level.$": "$.Price",
                    "curve": {
                        "curveType": curve_type
                    },
                    "volatility": {
                        "type": "Default"
                    },
                    "extraSettings": {
                        "optionModel": "OASEDUR",
                        "includePartials": False
                    }
                }]
            }
        }
        
        response = rq.post(url, headers=self._api_headers(), json=request_body)
        if response.status_code in [200, 201]:
            num_requests = len(response.json().get('results', []))
            print(f"✓ Submitted {num_requests} PY calculation requests")
        else:
            raise Exception(f"Failed to submit bulk template (status {response.status_code}): {response.text}")
    
    def _close_job(self, job_name: str):
        """Close the job to signal no more requests"""
        url = self._api_url(endpoint=f"/jobs/{job_name}/close")
        response = rq.post(url, headers=self._api_headers())
        
        if response.status_code in [200, 201, 204]:
            print(f"✓ Closed job '{job_name}'")
        else:
            raise Exception(f"Failed to close job (status {response.status_code}): {response.text}")
    
    def _wait_for_job_completion(self, job_id: str, timeout: int = 36000, interval: int = 10):  # 10 hours timeout
        """Wait for job to complete"""
        url = self._api_url(endpoint=f"/jobs/{job_id}/status")
        
        print("Waiting for job completion", end="")
        time_passed = 0
        
        while time_passed < timeout:
            response = rq.get(url, headers=self._api_headers())
            if response.status_code == 200:
                status = response.json().get("jobStatus")
                if status == "DONE":
                    print(" ✓ Done")
                    return
            
            print(".", end="", flush=True)
            time.sleep(interval)
            time_passed += interval
        
        raise TimeoutError(f"Job did not complete within {timeout} seconds")
    
    def _wait_and_stream_results(
        self,
        job_id: str,
        job_name: str,
        output_fields: Optional[List[str]],
        callback: Optional[callable] = None,
        timeout: int = 36000,  # 10 hours timeout (36000 seconds)
        interval: int = 30  # Check every 30 seconds (was 10) to reduce API load
    ) -> pd.DataFrame:
        """
        Wait for job completion while streaming results as they become available
        
        Args:
            job_id: Job ID to monitor
            job_name: Job name for results retrieval
            output_fields: Fields to retrieve
            callback: Optional callback function(partial_df, completed, total)
            timeout: Maximum wait time in seconds
            interval: Polling interval in seconds
            
        Returns:
            Complete DataFrame with all results
        """
        url = self._api_url(endpoint=f"/jobs/{job_id}/status")
        
        print("Streaming results as they complete...")
        time_passed = 0
        last_ok_count = 0
        all_results = []
        
        while time_passed < timeout:
            response = rq.get(url, headers=self._api_headers())
            if response.status_code == 200:
                job_status = response.json()
                status = job_status.get("jobStatus")
                ok_count = job_status.get("okCount", 0)
                total_count = job_status.get("requestCount", 0)
                
                # Check if new results are available
                if ok_count > last_ok_count:
                    print(f"\n  → {ok_count}/{total_count} calculations completed, retrieving results...")
                    
                    # Small delay to allow results to be written to results store
                    time.sleep(2)
                    
                    # Retrieve partial results
                    try:
                        partial_df = self._retrieve_results(job_name, output_fields)
                        
                        # Check if results are actually available (race condition handling)
                        actual_result_count = len(partial_df)
                        
                        if actual_result_count < ok_count:
                            print(f"  ⚠ Results not yet available ({actual_result_count}/{ok_count}), will retry...")
                            continue  # Skip this iteration, try again next poll
                        
                        # Filter to new results only (skip already retrieved)
                        new_results = partial_df.iloc[last_ok_count:ok_count]
                        
                        if len(new_results) > 0:
                            all_results.append(new_results)
                            
                            # Call callback if provided
                            if callback:
                                callback(new_results, ok_count, total_count)
                            
                            last_ok_count = ok_count
                        else:
                            print(f"  ⚠ No new results in this batch, will retry...")
                            
                    except Exception as e:
                        print(f"  ⚠ Warning: Could not retrieve partial results: {str(e)}")
                
                # Check if done
                if status == "DONE":
                    print(f"\n✓ All calculations complete ({ok_count}/{total_count})")
                    
                    # Final retrieval to ensure we have everything
                    final_df = self._retrieve_results(job_name, output_fields)
                    return final_df
            
            print(".", end="", flush=True)
            time.sleep(interval)
            time_passed += interval
        
        raise TimeoutError(f"Job did not complete within {timeout} seconds")
    
    def _retrieve_results(self, job_name: str, output_fields: Optional[List[str]] = None) -> pd.DataFrame:
        """Retrieve results in pandas format"""
        # Default output fields - using correct field paths from YieldBook API
        if output_fields is None:
            output_fields = [
                # Basic Identification
                "CUSIP:userTag",
                "PricingDate:globalSettings.pricingDate",
                "Ticker:py.ticker",
                "Description:py.description",
                "IssuerTicker:py.issuerTicker",
                "SecurityType:py.securityType",
                
                # 1. Basic Bond Characteristics
                "Coupon:py.coupon",
                "MaturityDate:py.maturityDate",
                "Currency:py.currency",
                "DatedDate:py.datedDate",
                "FirstCouponDate:py.firstCouponDate",
                
                # 5. Pricing Details
                "Price:py.price",
                "FullPrice:py.fullPrice",
                "AccruedInterest:py.accruedInterest",
                "AccruedDays:py.accruedDays",
                "SettlementDate:py.settlementDate",
                
                # 2. Yield/Spread Metrics
                "Yield:py.yield",
                "YieldToMaturity:py.yieldToMaturity",
                "YieldToWorst:py.yieldToWorst",
                "YieldToNextCall:py.yieldToNextCall",
                "YieldToWorstCall:py.yieldToWorstCall",
                "CurrentYield:py.currentYield",
                "EffectiveYield:py.effectiveYield",
                "AnnualizedYield:py.annualizedYield",
                "SemiAnnualizedYield:py.semiAnnualizedYield",
                "CDYield:py.cdYield",
                "OAS:py.oas",
                "ZSpread:py.zSpread",
                "ZISpread:py.ziSpread",
                "ZNSpread:py.znSpread",
                "ISpread:py.iSpread",
                "GSpread:py.gSpread",
                "AssetSwapSpread:py.assetSwapSpread",
                "GrossSpread:py.grossSpread",
                "StaticSpread:py.staticSpread",
                "ECurveSpread:py.eCurveSpread",
                "SpreadToActCurve:py.spreadToActCurve",
                "SpreadToTsyCurve:py.spreadToTsyCurve",
                "SpreadToBenchmark:py.spreadToBenchmark",
                "SpreadToSwapCurve:py.spreadToSwapCurve",
                "SpreadToRFRSwapCurve:py.spreadToRFRSwapCurve",
                "SpreadToWorstCall:py.spreadToWorstCall",
                "YieldCurveMargin:py.yieldCurveMargin",
                
                # 3. Duration Variants
                "Duration:py.duration",
                "ModifiedDuration:py.modifiedDuration",
                "EffectiveDuration:py.effectiveDuration",
                "MacaulayDuration:py.macaulayDuration",
                "SpreadDuration:py.spreadDuration",
                "YieldCurveDuration:py.yieldCurveDuration",
                "SpreadDurationTreasury:py.spreadDurationTreasury",
                "DurationToWorstCase:py.durationToWorstCase",
                "FundedEffectiveDuration:py.fundedEffectiveDuration",
                "EffectiveDurationPriceUp:py.effectiveDurationPriceUp",
                "EffectiveDurationPriceDown:py.effectiveDurationPriceDown",
                
                # 4. Convexity Metrics
                "Convexity:py.convexity",
                "EffectiveConvexity:py.effectiveConvexity",
                "ModifiedConvexity:py.modifiedConvexity",
                "MacaulayConvexity:py.macaulayConvexity",
                "SpreadConvexity:py.spreadConvexity",
                "ConvexityCost:py.convexityCost",
                "ConvexityEffect:py.convexityEffect",
                "FundedEffectiveConvexity:py.fundedEffectiveConvexity",
                
                # Risk Measures
                "DV01:py.dv01",
                "EffectiveDV01:py.effectiveDV01",
                "EffectiveCV01:py.effectiveCV01",
                "SpreadDV01:py.spreadDV01",
                "PVBP:py.pvbp",
                "BPV:py.bpv",
                "WAL:py.wal",
                "EffectiveWAL:py.effectiveWal",
                
                # 6. Curve Information
                "CurveType:py.curveType",
                "CurveDate:py.curveDate",
                "TsyCurveID:py.tsyCurveID",
                "SwapCurveID:py.swapCurveID",
                "OptionModelCurveID:py.optionModelCurveID",
                "Benchmark:py.benchmark",
                "BenchmarkToNextCall:py.benchmarkToNextCall",
                
                # 7. Date Information
                "PricingDate:py.pricingDate",
                "NextCallDate:py.nextCallDate",
                "NextPaymentDate:py.nextPaymentDate",
                "LastPrincipalPaymentDate:py.lastPrincipalPaymentDate",
                "FirstPrincipalPaymentDate:py.firstPrincipalPaymentDate",
                "CurrentAccrualDate:py.currentAccrualDate",
                "YearsToMaturity:py.yearsToMaturity",
                "YearsToFinalMaturity:py.yearsToFinalMaturity",
                
                # 8. Credit/Prepayment Metrics
                "CreditLoss:py.creditLoss",
                "PrepayRate:py.prepayRate",
                "PrepayType:py.prepayType",
                "CMMType:py.cmmType",
                "CurrentCoupon:py.currentCoupon",
                "MoatsCurrentCoupon:py.moatsCurrentCoupon",
                "EconomicExposure:py.economicExposure",
                "SettleDateFactor:py.settleDateFactor",
                "PrincipalWritedownCreditLoss:py.principalWritedownCreditLoss",
                "CumulativeLossToNextCallCurrent:py.cumulativeLossToNextCallCurrent",
                "CumulativeLossToNextCallOriginal:py.cumulativeLossToNextCallOriginal",
                "CumulativeDefaultToNextCallCurrent:py.cumulativeDefaultToNextCallCurrent",
                "CumulativeDefaultToNextCallOriginal:py.cumulativeDefaultToNextCallOriginal",
                
                # 9. Model Information
                "ModelCode:py.modelCode",
                "VolModelType:py.volModelType",
                "ClassName:py.className",
                "CompoundingFreq:py.compoundingFreq",
                
                # 10. Credit Ratings (may not always be available)
                "Rating:py.rating",
                "IssuerRating:py.issuerRating",
                "MoodyRating:py.moodyRating",
                "SPRating:py.spRating",
                "FitchRating:py.fitchRating"
            ]
        
        fields_param = ",".join(output_fields)
        url = self._api_url(
            endpoint=f"/results/bulk/pandas-json/table?ids=J:{job_name}&fields={fields_param}"
        )
        
        response = rq.get(url, headers=self._api_headers())
        if response.status_code == 200:
            data = response.json().get("data")
            df = pd.DataFrame.from_dict(data)
            if 'index' in df.columns:
                df = df.drop(columns=['index'])
            return df
        else:
            raise Exception(f"Failed to retrieve results (status {response.status_code}): {response.text}")

# %%
def prepare_monthly_bond_data(
    cusips: List[str],
    start_date: str = "2018-08-01",
    end_date: str = "2025-09-01",
    prices: Optional[Dict[str, List[float]]] = None
) -> pd.DataFrame:
    """
    Prepare monthly bond data for analysis
    
    Args:
        cusips: List of CUSIP identifiers
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        prices: Dict mapping CUSIP to list of prices (one per month)
                If None, must provide prices separately
    
    Returns:
        DataFrame with CUSIP, PricingDate, Price columns
    """
    # Generate monthly dates
    dates = pd.date_range(start=start_date, end=end_date, freq='MS')
    
    records = []
    for cusip in cusips:
        if prices and cusip in prices:
            price_list = prices[cusip]
            for i, date in enumerate(dates):
                if i < len(price_list):
                    records.append({
                        'CUSIP': cusip,
                        'PricingDate': date.strftime('%Y-%m-%d'),
                        'Price': str(price_list[i])
                    })
        else:
            # If no prices provided, leave as placeholder
            for date in dates:
                records.append({
                    'CUSIP': cusip,
                    'PricingDate': date.strftime('%Y-%m-%d'),
                    'Price': ''
                })
    
    return pd.DataFrame(records)


# =============================================================================
# PRODUCTION FUNCTION: Process Real Corporate Bond Data
# =============================================================================
# %%
def process_corporate_bonds_from_datascope(
    api_id: str,
    api_key: str,
    price_parquet_path: str = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Elektron_Timeseries_EOD.parquet",
    reference_csv_path: str = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/YIELDBOOK/reference/CorpBonds_reference.csv",
    output_base_dir: str = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/YIELDBOOK/py",
    start_date: str = "2018-01-01",
    end_date: str = "2025-09-30",
    batch_size: int = 25,  # Reduced from 100 to avoid timeouts (50 bonds × 93 months = ~4,650 calcs)
    curve_type: str = "SWAP"
):
    """
    Process corporate bonds from Datascope EOD data with YieldBook PY analysis
    
    Args:
        api_id: YieldBook API ID
        api_key: YieldBook API key
        price_parquet_path: Path to Elektron_Timeseries_EOD.parquet
        reference_csv_path: Path to RIC-CUSIP mapping CSV
        output_base_dir: Base directory for output (creates subdirs per bond)
        start_date: Start date for analysis (YYYY-MM-DD)
        end_date: End date for analysis (YYYY-MM-DD)
        batch_size: Number of bonds to process per batch
        curve_type: Curve type for analysis (SWAP, GVT, etc.)
    """
    print("=" * 80)
    print("CORPORATE BOND PY ANALYSIS - PRODUCTION RUN")
    print("=" * 80)
    
    # Step 1: Load and prepare price data
    print("\n[1/6] Loading price data from parquet...")
    df = pd.read_parquet(price_parquet_path)
    print(f"  ✓ Loaded {len(df)} rows")
    
    # Pivot to get RIC as columns, dates as index
    print("  → Pivoting data...")
    df_pivot = df.pivot_table(index=['Trade Date'], columns='RIC', values='Average of Bid and Ask')
    df_pivot.index = pd.to_datetime(df_pivot.index)
    print(f"  ✓ Pivoted: {len(df_pivot)} dates × {len(df_pivot.columns)} RICs")
    
    # Resample to month-end
    print("  → Resampling to month-end...")
    df_monthly = df_pivot.resample('ME').last()
    print(f"  ✓ Resampled: {len(df_monthly)} monthly periods")
    
    # Filter date range
    print(f"  → Filtering dates: {start_date} to {end_date}...")
    df_monthly = df_monthly.loc[start_date:end_date]
    print(f"  ✓ Filtered: {len(df_monthly)} months")
    
    # Step 2: Load RIC-CUSIP mapping
    print("\n[2/6] Loading RIC-CUSIP mapping...")
    ref_df = pd.read_csv(reference_csv_path)
    print(f"  ✓ Loaded {len(ref_df)} mappings")
    
    # Create mapping dict
    ric_to_cusip = dict(zip(ref_df['indic.ric'], ref_df['cusip']))
    print(f"  ✓ Created mapping dictionary")
    
    # Step 3: Identify bonds to process
    print("\n[3/6] Identifying bonds with valid data...")
    rics_with_cusip = [ric for ric in df_monthly.columns if ric in ric_to_cusip]
    print(f"  ✓ Found {len(rics_with_cusip)} RICs with CUSIP mapping")
    
    # Filter to RICs with sufficient data (at least 1 non-null price)
    valid_rics = []
    for ric in rics_with_cusip:
        if df_monthly[ric].notna().sum() > 0:
            valid_rics.append(ric)
    print(f"  ✓ {len(valid_rics)} RICs have valid price data")
    
    # Step 4: Split into batches
    print(f"\n[4/6] Organizing into batches of {batch_size}...")
    batches = [valid_rics[i:i + batch_size] for i in range(0, len(valid_rics), batch_size)]
    print(f"  ✓ Created {len(batches)} batches")
    
    # Create output directory
    os.makedirs(output_base_dir, exist_ok=True)
    print(f"  ✓ Output directory: {output_base_dir}")
    
    # Step 5: Initialize YieldBook analyzer
    print("\n[5/6] Initializing YieldBook analyzer...")
    analyzer = YieldBookBulkAnalyzer(api_id=api_id, api_key=api_key)
    analyzer.authenticate()
    
    # Step 6: Process batches
    print(f"\n[6/6] Processing {len(batches)} batches...")
    
    overall_progress = tqdm(total=len(valid_rics), desc="Overall Progress", position=0)
    batches_skipped = 0
    batches_processed = 0
    batches_failed = 0
    
    for batch_idx, ric_batch in enumerate(batches, 1):
        print(f"\n{'='*80}")
        print(f"BATCH {batch_idx}/{len(batches)}: Processing {len(ric_batch)} bonds")
        print(f"{'='*80}")
        
        # Re-authenticate before each batch to avoid token expiration
        if batch_idx > 1:
            print("  → Re-authenticating...")
            try:
                analyzer.authenticate()
                print("  ✓ Re-authenticated successfully")
            except Exception as e:
                print(f"  ⚠ Re-authentication failed: {str(e)}")
                # Continue anyway, might still work
        
        # Prepare data for this batch
        batch_records = []
        ric_to_cusip_batch = {}
        
        for ric in ric_batch:
            cusip = ric_to_cusip[ric]
            ric_to_cusip_batch[ric] = cusip
            
            # Get prices for this RIC
            prices = df_monthly[ric].dropna()
            
            for date, price in prices.items():
                batch_records.append({
                    'CUSIP': cusip,
                    'PricingDate': date.strftime('%Y-%m-%d'),
                    'Price': str(price)
                })
        
        batch_df = pd.DataFrame(batch_records)
        print(f"  → Prepared {len(batch_df)} calculations ({len(ric_batch)} bonds × avg prices)")
        
        if len(batch_df) == 0:
            print(f"  ⚠ No valid data in this batch, skipping...")
            batches_skipped += 1
            overall_progress.update(len(ric_batch))
            continue
        
        # Check if batch already processed (all bonds have results)
        batch_already_done = True
        for ric in ric_batch:
            cusip = ric_to_cusip_batch[ric]
            bond_dir = os.path.join(output_base_dir, cusip)
            final_file = os.path.join(bond_dir, f"final_results_batch_{batch_idx}.csv")
            
            if not os.path.exists(final_file):
                batch_already_done = False
                break
        
        if batch_already_done:
            print(f"  ✓ Batch {batch_idx} already processed (all results exist), skipping...")
            batches_skipped += 1
            overall_progress.update(len(ric_batch))
            continue
        
        # Run analysis in batch mode (no streaming)
        try:
            job_name = f"corp_bonds_batch_{batch_idx}_{int(time.time())}"
            
            print(f"  → Starting bulk analysis (waiting for all {len(batch_df)} calculations to complete)...")
            
            results = analyzer.run_bulk_py_analysis(
                bonds_data=batch_df,
                job_name=job_name,
                curve_type=curve_type,
                stream_results=False  # Batch mode: wait for all results
            )
            
            # Save final results per bond
            print(f"\n  → Saving final results for {len(ric_batch)} bonds...")
            for ric in tqdm(ric_batch, desc=f"  Saving batch {batch_idx}", leave=False):
                cusip = ric_to_cusip_batch[ric]
                cusip_results = results[results['CUSIP'] == cusip]
                
                if len(cusip_results) > 0:
                    bond_dir = os.path.join(output_base_dir, cusip)
                    os.makedirs(bond_dir, exist_ok=True)
                    
                    # Save final consolidated results
                    final_file = os.path.join(bond_dir, f"final_results_batch_{batch_idx}.csv")
                    cusip_results.to_csv(final_file, index=False)
                    
                    # Save summary
                    summary_file = os.path.join(bond_dir, f"summary_batch_{batch_idx}.txt")
                    with open(summary_file, 'w') as f:
                        f.write(f"Bond: {cusip}\n")
                        f.write(f"RIC: {ric}\n")
                        f.write(f"Batch: {batch_idx}\n")
                        f.write(f"Calculations: {len(cusip_results)}\n")
                        f.write(f"Date Range: {cusip_results['PricingDate'].min()} to {cusip_results['PricingDate'].max()}\n")
                        if 'OAS' in cusip_results.columns:
                            f.write(f"\nOAS Statistics:\n")
                            f.write(f"  Mean: {cusip_results['OAS'].mean():.2f}\n")
                            f.write(f"  Std: {cusip_results['OAS'].std():.2f}\n")
                            f.write(f"  Min: {cusip_results['OAS'].min():.2f}\n")
                            f.write(f"  Max: {cusip_results['OAS'].max():.2f}\n")
            
            print(f"  ✓ Batch {batch_idx} complete: {len(results)} calculations")
            batches_processed += 1
            
        except Exception as e:
            print(f"  ✗ Error in batch {batch_idx}: {str(e)}")
            # Save error log with more details
            error_file = os.path.join(output_base_dir, f"error_batch_{batch_idx}.txt")
            with open(error_file, 'w') as f:
                f.write(f"Batch {batch_idx} failed\n")
                f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Error: {str(e)}\n")
                f.write(f"Number of bonds in batch: {len(ric_batch)}\n")
                f.write(f"Number of calculations attempted: {len(batch_df)}\n")
                f.write(f"\nRICs in batch:\n")
                for ric in ric_batch:
                    f.write(f"  - {ric} (CUSIP: {ric_to_cusip_batch.get(ric, 'N/A')})\n")
            
            print(f"  → Error details saved to: {error_file}")
            print(f"  → Continuing with next batch...")
            batches_failed += 1
        
        # Update overall progress
        overall_progress.update(len(ric_batch))
    
    overall_progress.close()
    
    print("\n" + "=" * 80)
    print("PROCESSING COMPLETE")
    print("=" * 80)
    print(f"Results saved to: {output_base_dir}")
    print(f"Total bonds processed: {len(valid_rics)}")
    print(f"Output structure: {output_base_dir}/<CUSIP>/")
    print(f"\nBatch Summary:")
    print(f"  Total batches: {len(batches)}")
    print(f"  ✓ Processed: {batches_processed}")
    print(f"  ⊙ Skipped (already done): {batches_skipped}")
    print(f"  ✗ Failed: {batches_failed}")


# =============================================================================
# TEST FUNCTION
# =============================================================================
# %%
def test_single_bond_analysis():
    """
    Test with one bond (Apple Inc) and constant price of 100
    from 2018-08 to 2025-09
    """
    print("=" * 70)
    print("TEST: Single Bond Analysis with Constant Price")
    print("=" * 70)
    
    # Configuration (UPDATE THESE WITH YOUR CREDENTIALS)
    API_ID = "seb@exponential-tech.ai-api"
    API_KEY = "1f5f3b42-0262-43bf-059a-d8ff607c207a"
    
    # Test bond:
    TEST_CUSIP = "3136FAWE"  
    
    # Generate monthly dates from 2018-08 to 2025-09
    dates = pd.date_range(start="2023-03-01", end="2025-09-01", freq='MS')
    
    # Create test data with constant price of 100
    test_data = pd.DataFrame({
        'CUSIP': [TEST_CUSIP] * len(dates),
        'PricingDate': [d.strftime('%Y-%m-%d') for d in dates],
        'Price': ['100'] * len(dates)  # Constant price
    })
    
    print(f"\nTest Data:")
    print(f"  Bond: {TEST_CUSIP}")
    print(f"  Periods: {len(test_data)} months ({test_data['PricingDate'].min()} to {test_data['PricingDate'].max()})")
    print(f"  Price: Constant at 100")
    print(f"\nFirst few records:")
    print(test_data.head())
    
    # Initialize analyzer
    analyzer = YieldBookBulkAnalyzer(api_id=API_ID, api_key=API_KEY)
    
    try:
        # Run analysis
        results = analyzer.run_bulk_py_analysis(
            bonds_data=test_data,
            job_name=f"test_job_{int(time.time())}",  # Unique job name
            curve_type="SWAP"
        )
        
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"\nRetrieved {len(results)} results")
        print("\nFirst 5 results:")
        print(results.head())
        
        print("\nResult columns:")
        print(results.columns.tolist())
        
        # Basic statistics
        if 'Yield' in results.columns:
            print(f"\nYield statistics:")
            print(results['Yield'].describe())
        
        if 'OAS' in results.columns:
            print(f"\nOAS statistics:")
            print(results['OAS'].describe())
        
        # Save results
        output_file = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        results.to_csv(output_file, index=False)
        print(f"\n✓ Results saved to: {output_file}")
        
        return results
        
    except Exception as e:
        print(f"\n✗ Error during analysis: {str(e)}")
        raise

# %%
def test_streaming_results():
    """
    Test streaming results - retrieve partial results as calculations complete
    """
    print("=" * 70)
    print("TEST: Streaming Results")
    print("=" * 70)
    
    # Configuration
    API_ID = "seb@exponential-tech.ai-api"
    API_KEY = "1f5f3b42-0262-43bf-059a-d8ff607c207a"
    TEST_CUSIP = "3136FAWE"
    
    # Generate monthly dates for larger dataset
    dates = pd.date_range(start="2023-03-01", end="2025-09-01", freq='MS')
    
    test_data = pd.DataFrame({
        'CUSIP': [TEST_CUSIP] * len(dates),
        'PricingDate': [d.strftime('%Y-%m-%d') for d in dates],
        'Price': ['100'] * len(dates)
    })
    
    print(f"\nTest Data: {len(test_data)} monthly calculations")
    
    # Define callback to process partial results
    batch_num = [0]  # Use list to allow modification in nested function
    
    def save_partial_results(partial_df, completed, total):
        """Save each batch of results as they arrive"""
        if len(partial_df) == 0:
            print(f"  ⚠ Received empty batch, skipping save")
            return
        
        batch_num[0] += 1
        # Filename shows batch number and actual row count
        filename = f"batch_{batch_num[0]}_rows_{len(partial_df)}_total_{completed}_of_{total}.csv"
        partial_df.to_csv(filename, index=False)
        print(f"  ✓ Saved batch #{batch_num[0]}: {len(partial_df)} new results to {filename}")
        
        # Show sample of new results
        if 'OAS' in partial_df.columns:
            avg_oas = partial_df['OAS'].mean()
            print(f"     Average OAS in this batch: {avg_oas:.2f} bps")
        
        # Show date range if available
        if 'PricingDate' in partial_df.columns:
            dates = partial_df['PricingDate'].unique()
            print(f"     Date range: {dates.min()} to {dates.max()} ({len(dates)} dates)")
    
    # Initialize analyzer
    analyzer = YieldBookBulkAnalyzer(api_id=API_ID, api_key=API_KEY)
    
    try:
        # Run with streaming enabled
        results = analyzer.run_bulk_py_analysis(
            bonds_data=test_data,
            job_name=f"stream_test_{int(time.time())}",
            curve_type="SWAP",
            stream_results=True,  # Enable streaming
            stream_callback=save_partial_results  # Process results as they arrive
        )
        
        print("\n" + "=" * 70)
        print("FINAL RESULTS")
        print("=" * 70)
        print(f"\nTotal results: {len(results)}")
        print(f"Columns: {len(results.columns)}")
        
        # Save final consolidated results
        final_file = f"final_streaming_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        results.to_csv(final_file, index=False)
        print(f"\n✓ Final results saved to: {final_file}")
        
        return results
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        raise


# %%
def run_production_analysis():
    """
    Run production analysis on all corporate bonds
    """
    API_ID = "seb@exponential-tech.ai-api"
    API_KEY = "1f5f3b42-0262-43bf-059a-d8ff607c207a"
    
    process_corporate_bonds_from_datascope(
        api_id=API_ID,
        api_key=API_KEY,
        batch_size=5,  # 25 bonds per batch, 10 hour timeout per batch
        curve_type="SWAP"
    )


# %%
if __name__ == "__main__":
    # Choose one to run:
    
    # 1. Run production analysis (hundreds of bonds from Datascope)
    run_production_analysis()
    
    # 2. Run simple test (single bond, constant price)
    # test_single_bond_analysis()
    
    # 3. Run streaming test
    # test_streaming_results()

# %%
