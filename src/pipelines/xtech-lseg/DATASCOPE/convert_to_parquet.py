# %%
import pandas as pd
import os

def csv_to_parquet(csv_path, chunk_size=100000, numeric_patterns=None):
    """
    Convert CSV file to parquet format with proper data type handling.
    
    Parameters:
    -----------
    csv_path : str
        Path to the CSV file
    chunk_size : int, default=10000
        Number of rows to read per chunk
    numeric_patterns : list of str, optional
        Column name patterns that should be treated as numeric.
        If None, uses default patterns for price/yield columns.
    
    Returns:
    --------
    str
        Path to the generated parquet file
    """
    # Default numeric patterns for financial data
    if numeric_patterns is None:
        numeric_patterns = [
            'price', 'yield', 'rate', 'spread', 'coupon', 
            'volume', 'amount', 'value', 'bid', 'ask', 'mid',
            'oas', 'duration', 'convexity', 'dv01', 'ytm', 'ytw',
            'accrued', 'proceeds', 'z-spread', 'g-spread',
            'open', 'high', 'low', 'close', 'vwap'
        ]
    
    # Read CSV in chunks
    chunks = []
    for chunk in pd.read_csv(csv_path, chunksize=chunk_size):
        chunks.append(chunk)
    
    # Concatenate all chunks into a single DataFrame
    df = pd.concat(chunks, ignore_index=True)
    
    # Drop columns that are all null
    df = df.dropna(axis=1, how='all')

    # drop Wertpapier if Wertpapier is in the column name
    if 'Wertpapier' in df.columns:
        df = df.drop(columns=['Wertpapier'])
    
    # Track columns that have non-null values before conversion
    cols_with_data_before = {col: df[col].notna().any() for col in df.columns}
    
    # Convert only specified columns to numeric, keep others as strings
    numeric_cols = []
    exception_cols=['Inverse Rate Marker']
    for col in df.select_dtypes(include=['object']).columns:
        if col in exception_cols:
            should_be_numeric=False
        else:
            # Check if column name matches any numeric pattern
            col_lower = col.lower()
            should_be_numeric = any(pattern in col_lower for pattern in numeric_patterns)
        
        if should_be_numeric:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            numeric_cols.append(col)
    
    # Check for columns that became all null after conversion
    data_loss_cols = []
    for col in df.columns:
        had_data_before = cols_with_data_before.get(col, False)
        has_data_after = df[col].notna().any()
        if had_data_before and not has_data_after:
            data_loss_cols.append(col)
    
    # Generate parquet file path
    parquet_path = csv_path.replace('.csv', '.parquet')
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(parquet_path), exist_ok=True)
    
    # Save to parquet
    df.to_parquet(parquet_path)
    
    print(f"Successfully converted {os.path.basename(csv_path)} to parquet")
    print(f"Converted {len(numeric_cols)} columns to numeric: {numeric_cols}")
    print(f"Output: {parquet_path}")
    
    # Warn about data loss
    if data_loss_cols:
        print(f"\n⚠️  WARNING: {len(data_loss_cols)} column(s) had data in CSV but are all NULL in parquet:")
        for col in data_loss_cols:
            print(f"  - {col}")
        print("  This may indicate incorrect type conversion. Consider reviewing numeric_patterns.\n")
    
    return parquet_path

# %%
# Convert all CSV files to parquet
csv_files = [
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Elektron_Timeseries_EOD.csv",
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales.csv",
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Terms_and_Conditions.csv",
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Historical_Reference.csv"

    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/example_data/Elektron_Timeseries_EOD_example.csv",
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/example_data/Tick_History_Time_and_Sales_example.csv",
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/example_data/Terms_and_Conditions_example.csv",
    # "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/example_data/Historical_Reference_example.csv",
    #  "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/example_data/Tick_History_Intraday_Summaries_1Min_example.csv"

    "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/benchmark_us_treasury/Elektron_Timeseries_EOD_us_treasury.csv",
    "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/benchmark_us_treasury/Tick_History_Time_and_Sales_us_treasury.csv",
    "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/benchmark_us_treasury/Terms_and_Conditions_us_treasury.csv",
    "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/benchmark_us_treasury/Historical_Reference_us_treasury.csv",

]

for csv_file in csv_files:
    csv_to_parquet(csv_file)

# %%
import pandas as pd
df=pd.read_parquet("/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Elektron_Timeseries_EOD.parquet")
# df=pd.read_parquet("/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales.parquet")
df.head()

# %%
df.columns

# %%
