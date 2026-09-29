# %%
import os
import pandas as pd
from pathlib import Path
from functools import reduce

from prepare_aligned_tickers import aligned_tickers_fmp as tickers
from prepare_aligned_tickers import ticker_fmp_map_ticker_lseg
from prepare_aligned_tickers import ticker_lseg_map_ric as ticker_fmp_map_ric_lseg


# %%
# Define all fundamental data directories to process
PIT_statements_dirs = [
    "balance_sheet_statement_bulk",
    "balance_sheet_statement_growth_bulk",
    "cash_flow_statement_bulk",
    "cash_flow_statement_growth_bulk",
    "income_statement_bulk",
    "income_statement_growth_bulk",
    "key_metrics",
    "financial_ratios",
    
]

corp_actions=[   
    "dividends",
    "earnings",
    "stock_splits"
    ]

 
other_dirs=[
    "earnings_supprises_bulk",
    "enterprise_values",
    "historical_grades",
    "historical_market_cap",
    "historical_ratings",
    "owner_earnings"
]

market_performance_dirs=[
    "historical_industry_pe",
    "historical_industry_performance",
    "historical_sector_pe",
    "historical_sector_performance"
]

# Collect all filtered dataframes
all_filtered_dfs = []

# Process each directory
for dir_name in PIT_statements_dirs:
    print(f"\n{'='*80}")
    print(f"Processing: {dir_name}")
    print(f"{'='*80}")
    
    base_dir = Path(__file__).resolve().parents[2] / "datastore" / "xtech-fmp" / "fundamental" / dir_name / "PIT" 

    # Check if PIT directory exists
    if not base_dir.exists():
        print(f"PIT directory does not exist: {base_dir}")
        continue
    
    # Find the most recent date directory
    date_dirs = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("date=")])
    
    if not date_dirs:
        print(f"No date directories found in {base_dir}")
        continue
    
    # Use the most recent date directory
    data_dir = date_dirs[-1]
    print(f"Using date directory: {data_dir.name}")
    
    # Read all parquet files in the directory
    parquet_files = list(data_dir.glob("*.parquet"))
    
    if not parquet_files:
        print(f"No parquet files found in {data_dir}")
        continue
    
    print(f"Found {len(parquet_files)} parquet files")
    
    # Read and concatenate all parquet files
    df_list = [pd.read_parquet(f) for f in parquet_files]
    df_data = pd.concat(df_list, ignore_index=True)
    print(f"Total records before filtering: {len(df_data)}")
    
    # Filter by tickers
    df_filtered = df_data[df_data['symbol'].isin(tickers)].copy()
    print(f"Total records after filtering: {len(df_filtered)}")
    
    # Ensure consistent types for merge keys
    if 'symbol' in df_filtered.columns:
        df_filtered['symbol'] = df_filtered['symbol'].astype(str)
    if 'fiscalYear' in df_filtered.columns:
        df_filtered['fiscalYear'] = pd.to_numeric(df_filtered['fiscalYear'], errors='coerce').astype('Int64')
    if 'period' in df_filtered.columns:
        df_filtered['period'] = df_filtered['period'].astype(str)
    
    # Convert remaining object columns to string to avoid type conflicts
    for col in df_filtered.select_dtypes(include=['object']).columns:
        if col not in ['symbol', 'fiscalYear', 'period']:
            df_filtered[col] = df_filtered[col].astype(str)
    
    # Collect filtered dataframe (without source_dir to avoid conflicts in merge)
    all_filtered_dfs.append((dir_name, df_filtered))
    
    # Find tickers that exist in tickers list but not in filtered data
    found_symbols = set(df_filtered['symbol'].unique())
    missing_symbols = [ticker for ticker in tickers if ticker not in found_symbols and ticker is not None]
    print(f"Missing symbols in this directory: {len(missing_symbols)}")

# Merge all filtered dataframes on symbol, fiscalYear, period
if all_filtered_dfs:
    print(f"\n{'='*80}")
    print("Merging all dataframes...")
    print(f"{'='*80}")
    
    # Start with the first dataframe
    df_all_filtered = all_filtered_dfs[0][1].copy()
    print(f"Starting with {all_filtered_dfs[0][0]}: {len(df_all_filtered)} records")
    
    # Merge remaining dataframes
    for i in range(1, len(all_filtered_dfs)):
        dir_name, df_next = all_filtered_dfs[i]
        print(f"Merging {dir_name}: {len(df_next)} records")
        
        # Merge on common columns
        df_all_filtered = pd.merge(
            df_all_filtered,
            df_next,
            on=['symbol', 'fiscalYear', 'period'],
            how='outer',
            suffixes=('', f'_{dir_name}')
        )
        print(f"  After merge: {len(df_all_filtered)} records")
    
    print(f"\n{'='*80}")
    print("All processing complete!")
    print(f"{'='*80}")
    print(f"Total records after merging: {len(df_all_filtered)}")
    print(f"Total unique symbols: {df_all_filtered['symbol'].nunique()}")
    print(f"Total columns: {len(df_all_filtered.columns)}")
else:
    print(f"\n{'='*80}")
    print("No filtered data found!")
    print(f"{'='*80}")

# %%
# filter fiscal year from 2017 to 2025
df_all_filtered = df_all_filtered[(df_all_filtered['fiscalYear'] >= 2017)]
print(f"Total records after filtering fiscal year: {len(df_all_filtered)}")

# Map FMP tickers to LSEG tickers
if 'symbol' in df_all_filtered.columns:
    df_all_filtered['symbol'] = df_all_filtered['symbol'].map(ticker_fmp_map_ticker_lseg).fillna(df_all_filtered['symbol'])
    print(f"Mapped FMP tickers to LSEG tickers")

# Add RIC column
if 'symbol' in df_all_filtered.columns:
    df_all_filtered['RIC'] = df_all_filtered['symbol'].map(ticker_fmp_map_ric_lseg)
    print(f"Added RIC column")

# %%
df_all_filtered.to_parquet(Path(__file__).resolve().parents[1] / "data" / "fmp_hist_financial_statements.parquet")

# %%
# ========================================================================================
# Process corp_actions: dividends, earnings, stock_splits
# ========================================================================================
def process_category(dir_list, category_name, merge_keys, output_filename, base_path_type="fundamental"):
    """Process a category of directories and merge on specified keys
    
    Args:
        dir_list: List of directory names to process
        category_name: Name of the category for logging
        merge_keys: List of columns to merge on
        output_filename: Name of output parquet file
        base_path_type: Either 'fundamental' or 'market' to determine base path
    """
    all_filtered_dfs = []
    
    for dir_name in dir_list:
        print(f"\n{'='*80}")
        print(f"Processing: {dir_name}")
        print(f"{'='*80}")
        
        base_dir = Path(__file__).resolve().parents[2] / "datastore" / "xtech-fmp" / base_path_type / dir_name / "PIT"
        
        if not base_dir.exists():
            print(f"PIT directory does not exist: {base_dir}")
            continue
        
        date_dirs = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("date=")])
        
        if not date_dirs:
            print(f"No date directories found in {base_dir}")
            continue
        
        data_dir = date_dirs[-1]
        print(f"Using date directory: {data_dir.name}")
        
        parquet_files = list(data_dir.glob("*.parquet"))
        
        if not parquet_files:
            print(f"No parquet files found in {data_dir}")
            continue
        
        print(f"Found {len(parquet_files)} parquet files")
        
        df_list = [pd.read_parquet(f) for f in parquet_files]
        df_data = pd.concat(df_list, ignore_index=True)
        print(f"Total records before filtering: {len(df_data)}")
        
        # Filter by tickers only if 'symbol' column exists
        if 'symbol' in df_data.columns:
            df_filtered = df_data[df_data['symbol'].isin(tickers)].copy()
            print(f"Total records after filtering: {len(df_filtered)}")
            
            found_symbols = set(df_filtered['symbol'].unique())
            missing_symbols = [ticker for ticker in tickers if ticker not in found_symbols and ticker is not None]
            print(f"Missing symbols in this directory: {len(missing_symbols)}")
        else:
            # No symbol column, use all data (e.g., sector/industry level data)
            df_filtered = df_data.copy()
            print(f"No symbol column - keeping all records: {len(df_filtered)}")
        
        # Ensure consistent types for merge keys
        for key in merge_keys:
            if key in df_filtered.columns:
                if key == 'symbol':
                    df_filtered[key] = df_filtered[key].astype(str)
                elif 'date' in key.lower() or 'year' in key.lower():
                    # Try to convert to datetime first, if fails keep as string
                    try:
                        df_filtered[key] = pd.to_datetime(df_filtered[key])
                    except:
                        df_filtered[key] = df_filtered[key].astype(str)
        
        # Convert remaining object columns to string
        for col in df_filtered.select_dtypes(include=['object']).columns:
            if col not in merge_keys:
                df_filtered[col] = df_filtered[col].astype(str)
        
        all_filtered_dfs.append((dir_name, df_filtered))
    
    # Merge all filtered dataframes
    if all_filtered_dfs:
        print(f"\n{'='*80}")
        print(f"Merging {category_name} dataframes...")
        print(f"{'='*80}")
        
        df_merged = all_filtered_dfs[0][1].copy()
        print(f"Starting with {all_filtered_dfs[0][0]}: {len(df_merged)} records")
        
        for i in range(1, len(all_filtered_dfs)):
            dir_name, df_next = all_filtered_dfs[i]
            print(f"Merging {dir_name}: {len(df_next)} records")
            
            df_merged = pd.merge(
                df_merged,
                df_next,
                on=merge_keys,
                how='outer',
                suffixes=('', f'_{dir_name}')
            )
            print(f"  After merge: {len(df_merged)} records")
        
        print(f"\n{'='*80}")
        print(f"{category_name} processing complete!")
        print(f"{'='*80}")
        print(f"Total records: {len(df_merged)}")
        if 'symbol' in df_merged.columns:
            print(f"Total unique symbols: {df_merged['symbol'].nunique()}")
        print(f"Total columns: {len(df_merged.columns)}")
        
        # Map FMP tickers to LSEG tickers before saving
        if 'symbol' in df_merged.columns:
            df_merged['symbol'] = df_merged['symbol'].map(ticker_fmp_map_ticker_lseg).fillna(df_merged['symbol'])
            print(f"Mapped FMP tickers to LSEG tickers")
        
        # Add RIC column
        if 'symbol' in df_merged.columns:
            df_merged['RIC'] = df_merged['symbol'].map(ticker_fmp_map_ric_lseg)
            print(f"Added RIC column")
        
        # Save to file
        output_path = Path(__file__).resolve().parents[1] / "data" / output_filename
        df_merged.to_parquet(output_path)
        print(f"Saved to: {output_path}")
        
        return df_merged
    else:
        print(f"\n{'='*80}")
        print(f"No {category_name} data found!")
        print(f"{'='*80}")
        return None

# Process corp_actions (dividends, earnings, stock_splits)
df_corp_actions = process_category(
    corp_actions,
    "Corporate Actions",
    ['symbol', 'date'],
    "fmp_corp_actions.parquet"
)

# %%
# Process other_dirs: enterprise valuations, ratings, and historical metrics
other_dirs_corrected = [
    "enterprise_values",
    "historical_grades",
    "historical_market_cap",
    "historical_ratings",
    "owner_earnings"
]

df_other = process_category(
    other_dirs_corrected,
    "Enterprise Valuations & Ratings",
    ['symbol', 'date'],
    "fmp_enterprise_valuations_ratings.parquet"
)

# %%
# Process market_performance_dirs (these are in 'market' folder, not 'fundamental')
# Note: These do not have 'symbol' column as they are sector/industry level data
df_market = process_category(
    market_performance_dirs,
    "Market Performance",
    ['date'],  # Market data typically doesn't have symbol column
    "fmp_market_performance.parquet",
    base_path_type="market"
)

# %%
# ========================================================================================
# SUMMARY OF PROCESSED DATA
# ========================================================================================
# The following datasets have been created:
# 1. fmp_hist_financial_statements.parquet - Merged on [symbol, fiscalYear, period]
#    - balance_sheet_statement_bulk, balance_sheet_statement_growth_bulk
#    - cash_flow_statement_bulk, cash_flow_statement_growth_bulk
#    - income_statement_bulk, income_statement_growth_bulk
#    - key_metrics, financial_ratios
#    - Filtered for fiscal years >= 2017
#    - Symbol column mapped from FMP to LSEG tickers
#
# 2. fmp_corp_actions.parquet - Merged on [symbol, date]
#    - dividends, earnings, stock_splits
#    - Symbol column mapped from FMP to LSEG tickers
#
# 3. fmp_enterprise_valuations_ratings.parquet - Merged on [symbol, date]
#    - enterprise_values, historical_grades, historical_market_cap
#    - historical_ratings, owner_earnings
#    - Symbol column mapped from FMP to LSEG tickers
#
# 4. fmp_market_performance.parquet - Merged on [date]
#    - historical_industry_pe, historical_industry_performance
#    - historical_sector_pe, historical_sector_performance
#    - No symbol filtering (sector/industry level data)
# ========================================================================================

# %%
