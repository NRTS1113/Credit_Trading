# %% indicative yieldbook
import duckdb
import pandas as pd
import polars as pl
from pathlib import Path
from prepare_aligned_tickers import aligned_rics

df=pd.read_parquet("../../datastore/xtech-lseg/YIELDBOOK/indicative/_consolidated/all_securities.parquet")

# filter to only include aligned_rics
df=df[df["indic.ric"].isin(aligned_rics)]

# rename indic.ric to RIC and set as index
df=df.rename(columns={"indic.ric": "RIC"})
df=df.set_index("RIC")

# save to parquet
df.to_parquet("../data/yieldbook_indicatives.parquet")

# %% price/yield yieldbook
ref=pd.read_csv("../../datastore/xtech-lseg/YIELDBOOK/reference/CorpBonds_reference.csv")

# find a list of cusip in ref if in that row, its indic.ric is in aligned_rics
ref_filtered = ref[ref["indic.ric"].isin(aligned_rics)]
aligned_cusips = ref_filtered["cusip"].unique().tolist()
print(f"Total aligned CUSIPs: {len(aligned_cusips)}")

# for all dir(cusip) in ../../datastore/xtech-lseg/YIELDBOOK/py
# if cusip is in aligned_cusips, read all csv files, else skip
py_dir = Path("../../datastore/xtech-lseg/YIELDBOOK/py")
all_dfs = []

for cusip_dir in py_dir.iterdir():
    if not cusip_dir.is_dir():
        continue
    
    cusip = cusip_dir.name
    if cusip in aligned_cusips:
        # Read all CSV files in this cusip directory
        csv_files = list(cusip_dir.glob("*.csv"))
        if csv_files:
            print(f"Processing {cusip}: {len(csv_files)} files")
            for csv_file in csv_files:
                try:
                    df_temp = pd.read_csv(csv_file)
                    df_temp['cusip'] = cusip  # Add cusip identifier
                    all_dfs.append(df_temp)
                except Exception as e:
                    print(f"Error reading {csv_file}: {e}")

# concat all dataframes 
if all_dfs:
    df_price_yield = pd.concat(all_dfs, ignore_index=True)
    print(f"Total records: {len(df_price_yield)}")
    
    # Merge with reference to add RIC column
    df_price_yield = df_price_yield.merge(
        ref_filtered[['cusip', 'indic.ric']].rename(columns={'indic.ric': 'RIC'}),
        on='cusip',
        how='left'
    )
    
    # save to ../data/yieldbook_price_yield.parquet
    df_price_yield.to_parquet("../data/yieldbook_price_yield.parquet")
    print(f"Saved yieldbook_price_yield.parquet with {len(df_price_yield)} records")
else:
    print("No price/yield data found for aligned CUSIPs")

# %%
