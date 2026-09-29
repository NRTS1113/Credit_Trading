# %%
import requests as rq
import json as js
from pprint import pprint 
import pandas as pd
import os
from tqdm import tqdm
from multiprocessing import Pool, Manager
from functools import partial
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

api_id = "seb@exponential-tech.ai-api"
api_key = "1f5f3b42-0262-43bf-059a-d8ff607c207a"

PIPELINE_DATASTORE__BASE_PATH="/Volumes/seb's ssd/Work/datastore"
yieldbook_dir=os.path.join(PIPELINE_DATASTORE__BASE_PATH, "yieldbook")
os.makedirs(yieldbook_dir, exist_ok=True)

# %%
auth_url = "https://www.yieldbook.com/x/oauth/api-token"
auth_config = {
    "client_id": api_id, # "<CLIENT ID: your.email@company.com-api>",
    "client_secret": api_key, # "<API KEY: obtained https://from www.yieldbook.com>",
    "grant_type": "client_credentials",
    "audience": "API2-PROD"
}

def get_access_token(url, config):
    token_resp = rq.post(url, params=config)
    if token_resp:
        return token_resp.json().get("accessToken")

    print(f"Error retrieving token: {str(token_resp)}. Please check your credentials.")
    return None

access_token = get_access_token(auth_url, auth_config)

# %%
api_base_url = "https://api.yieldbook.com/analytics/v2"

def api_url(endpoint: str, mode: str = None):
    if not mode:
        return "/".join([api_base_url.strip("/"), endpoint.strip("/")])
    
    return "/".join([api_base_url.strip("/"), mode.strip("/"), endpoint.strip("/")])

def api_headers():
    return {
        'Accept': '*/*',
        'Authorization': f"Bearer {access_token}",
        'content-type': 'application/json'
    }
print(access_token)


# %%
start_date = "2018-08-01"
end_date = "2025-09-01"
dates = pd.date_range(start=start_date, end=end_date, freq='MS').strftime('%Y-%m-%d').tolist()

# %%
for ticker in ['BIGINDEX']:
    for date in tqdm(dates,total=len(dates)):
        output_dir = os.path.join(yieldbook_dir, "index_constituents", f"index={ticker}", f"date={date}")
        constituents_file = os.path.join(output_dir, "constituents.parquet")
        reference_file = os.path.join(output_dir, "reference.parquet")
        
        if os.path.exists(constituents_file) and os.path.exists(reference_file):
            continue
            
        try:
            url = f"https://api.yieldbook.com/analytics/v2/sync/index/data/{ticker}/{date}"
            response = rq.get(url, headers = api_headers())
            res = response.json()
            df = pd.DataFrame(res['results'])
            df['asof_date'] = date
            reference = pd.DataFrame([res['extra']['currency']['USD']], index=[0])
            reference['asof_date'] = date

            os.makedirs(output_dir, exist_ok=True)
            df.to_parquet(constituents_file, index=False)
            reference.to_parquet(reference_file, index=False)
        except Exception as e:
            print(f"Error processing {ticker} for {date}: {str(e)}")

# %%
dfs=[]
references=[]
for date in dates:
    fp=os.path.join(yieldbook_dir, "index_constituents",f"index=BIGINDEX",f"date={date}","constituents.parquet")
    df=pd.read_parquet(fp)
    dfs.append(df)
    fp=os.path.join(yieldbook_dir, "index_constituents",f"index=BIGINDEX",f"date={date}","reference.parquet")
    df=pd.read_parquet(fp)
    references.append(df)
 
df=pd.concat(dfs)
references=pd.concat(references)
references.set_index('asof_date', inplace=True)

# %% [markdown]
# ## Load Indicative Data and filter Corp Bonds

# %%
isins = df["isin"].unique().tolist()
os.makedirs(os.path.join(yieldbook_dir, "indicative"), exist_ok=True)

# Get existing processed ISINs
exist_isins = [f.split("=")[1] for f in os.listdir(os.path.join(yieldbook_dir, "indicative")) if "isin" in f and not f.endswith(".json")]

# Load excluded ISINs from previous runs
excluded_isins_file = os.path.join(yieldbook_dir, "indicative", "excluded_isins.json")
excluded_isins = set()
if os.path.exists(excluded_isins_file):
    try:
        with open(excluded_isins_file, 'r') as f:
            excluded_data = js.load(f)
            # Extract original ISINs from excluded records
            for record in excluded_data:
                if record.get('original_isin'):
                    excluded_isins.add(record['original_isin'])
        print(f"Loaded {len(excluded_isins)} excluded ISINs from previous runs")
    except Exception as e:
        print(f"Warning: Could not load excluded ISINs file: {e}")

# Filter out already processed and excluded ISINs
original_count = len(isins)
isins = [c for c in isins if c not in exist_isins and c not in excluded_isins]
filtered_count = len(isins)

print(f"ISIN filtering summary:")
print(f"- Original ISINs: {original_count}")
print(f"- Already processed: {len(exist_isins)}")
print(f"- Previously excluded: {len(excluded_isins)}")
print(f"- Total ISINs to process: {filtered_count}")

# %%
batch_size = 10
con_c=0
for i in tqdm(range(0, len(isins), batch_size),total=len(range(0, len(isins), batch_size))):
    con_c+=1
    if con_c>10:
        time.sleep(15)
        con_c=0
    batch_isins = isins[i:i+batch_size]
    print(f"Processing batch {i//batch_size + 1}, {len(batch_isins)} ISINs")

    # Use ThreadPoolExecutor instead of multiprocessing Pool for Jupyter compatibility
    max_workers = 10
    print(f"Using {max_workers} worker threads...")

    # ===== PHASE 1: SUBMIT CUSIP REQUESTS =====
    # Collect all request IDs using threading (works better in Jupyter than multiprocessing)

    def submit_isin_request(isin):
        """Submit request for a single isin"""
        try:
            # Build the indicative data endpoint URL
            indic_endpoint = "/bond/indic/{identifier}?idType={identifier_type}"
            indic_url = api_url(
                endpoint=indic_endpoint.format(identifier=isin, identifier_type="isin"), 
                mode="req"
            )
            
            # Make the API request for indicative data
            indic_response = rq.get(indic_url, headers=api_headers())

            if not indic_response:
                print(f"Error submitting indicative data request for {isin}: {str(indic_response)}")
                return {"isin": isin, "request_id": None, "error": str(indic_response)}
            else:
                response_json = indic_response.json()
                # print(f"Successfully submitted request for {isin}")
                indic_request_id = response_json["requestId"]
                return {"isin": isin, "request_id": indic_request_id, "error": None}
                
        except Exception as e:
            error_msg = f"Exception processing ISIN {isin}: {str(e)}"
            print(error_msg)
            return {"isin": isin, "request_id": None, "error": error_msg}

    # Submit all ISIN requests using ThreadPoolExecutor
    all_isin_results = []
    successful_request_ids = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_isin = {executor.submit(submit_isin_request, isin): isin for isin in batch_isins}
        
        # Process completed tasks with progress bar
        for future in tqdm(as_completed(future_to_isin), total=len(batch_isins), desc="Processing ISINs"):
            result = future.result()
            all_isin_results.append(result)
            
            # Collect successful request IDs
            if result["request_id"]:
                successful_request_ids.append(result["request_id"])

    print(f"\nISIN Processing Complete:")
    print(f"- Total ISINs processed: {len(batch_isins)}")
    print(f"- Successful requests: {len(successful_request_ids)}")
    print(f"- Failed requests: {len(batch_isins) - len(successful_request_ids)}")
    print(f"- Request IDs collected: {len(successful_request_ids)}")

    # Wait for API to process the requests
    print("\nWaiting for API to process requests...")
    time.sleep(2)  # Adjust based on typical API processing time

    # ===== PHASE 2: RETRIEVE RESULTS FOR ALL REQUEST IDs =====
    def retrieve_single_result(request_id):
        """Retrieve results for a single request ID"""
        try:
            # Build the results endpoint URL
            results_endpoint = "/results/{requestId}"
            results_url = api_url(
                endpoint=results_endpoint.format(requestId=request_id),
                mode=None
            )
            
            # Make the API request to get results
            results_response = rq.get(results_url, headers=api_headers())
            
            if not results_response:
                error_msg = f"Error retrieving results for request {request_id}: {str(results_response)}"
                print(error_msg)
                return {"request_id": request_id, "data": None, "error": error_msg}
            else:
                results_json = results_response.json()
                # print(f"Successfully retrieved results for request {request_id}")
                return {"request_id": request_id, "data": results_json, "error": None}
                
        except Exception as e:
            error_msg = f"Exception retrieving results for request {request_id}: {str(e)}"
            print(error_msg)
            return {"request_id": request_id, "data": None, "error": error_msg}

    # Retrieve results for all request IDs using ThreadPoolExecutor
    if successful_request_ids:
        print(f"\nRetrieving results for {len(successful_request_ids)} request IDs...")
        
        all_results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all result retrieval tasks
            future_to_request_id = {executor.submit(retrieve_single_result, req_id): req_id 
                                for req_id in successful_request_ids}
            
            # Process completed tasks with progress bar
            for future in tqdm(as_completed(future_to_request_id), 
                            total=len(successful_request_ids), 
                            desc="Retrieving results"):
                result = future.result()
                all_results.append(result)
        
        # Separate successful and failed result retrievals
        successful_results = [result["data"]["data"]  for result in all_results if result["data"]["data"] is not None]
        failed_results = [result["data"]["data"] for result in all_results if result["data"]["data"] is None]
        
        print(f"\nResults Retrieval Complete:")
        print(f"- Total request IDs processed: {len(successful_request_ids)}")
        print(f"- Successful result retrievals: {len(successful_results)}")
        print(f"- Failed result retrievals: {len(failed_results)}")
        
        # Save results to file for later analysis
        if successful_results:
            results_df = pd.DataFrame(successful_results)
            
            # Add original query ISIN mapping for tracking excluded ISINs
            isin_to_request_id = {result["isin"]: result["request_id"] for result in all_isin_results if result["request_id"]}
            request_id_to_isin = {v: k for k, v in isin_to_request_id.items()}
            
            # Add original_isin column to track the queried ISIN
            results_df['original_isin'] = results_df.index.map(
                lambda idx: request_id_to_isin.get(
                    all_results[idx]["request_id"] if idx < len(all_results) else None
                )
            )
            
            # Alternative approach: map by position if request_id mapping fails
            if results_df['original_isin'].isna().all():
                # Map by position in successful results
                successful_request_mapping = []
                for result in all_results:
                    if result["data"] and result["data"]["data"] is not None:
                        # Find original ISIN for this request_id
                        original_isin = request_id_to_isin.get(result["request_id"])
                        successful_request_mapping.append(original_isin)
                
                if len(successful_request_mapping) == len(results_df):
                    results_df['original_isin'] = successful_request_mapping
        
        # Print sample of successful results
        # if successful_results:
        #     print(f"\nSample result (first successful):")
        #     print(js.dumps(successful_results[0], indent=2))
            
    else:
        print("No successful request IDs available for results retrieval.")
        all_results = []

    # Final summary
    print(f"\n===== PROCESSING SUMMARY =====")
    print(f"Original ISINs: {len(batch_isins)}")
    print(f"Request IDs generated: {len(successful_request_ids)}")
    print(f"Results retrieved: {len([r for r in all_results if r['data'] is not None]) if 'all_results' in locals() else 0}")
    print(f"All results available as: all_results")
    print(results_df.head(1))

    from hive_partition_indicative import process_indicative_data_to_hive
    dfs_dict=process_indicative_data_to_hive(results_df)