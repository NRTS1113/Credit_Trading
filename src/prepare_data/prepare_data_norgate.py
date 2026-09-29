# %%
from prepare_aligned_tickers import aligned_tickers_fmp
import os
import pandas as pd

# get available tickers from norgate
available_tickers_norgate = [ticker.split(".csv")[0] for ticker in os.listdir("/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-norgate/us-eqt/US Equities")]

# find common tickers
common_tickers = list(set(aligned_tickers_fmp) & set(available_tickers_norgate))
print(f"Found {len(common_tickers)} common tickers")
print(f"missing tickers: {list(set(aligned_tickers_fmp) - set(available_tickers_norgate))}")

# get available delisted tickers
available_delisted_tickers_norgate = [ticker.split(".csv")[0] for ticker in os.listdir("/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-norgate/us-eqt/US Equities Delisted")]
# Fixed version - only keep tickers that have a dash and year >= 2018
available_delisted_tickers_norgate = [
    ticker.split("-")[0] 
    for ticker in available_delisted_tickers_norgate 
    if len(ticker.split("-")) > 1 and ticker.split("-")[1] >= "2018"
]
# find common delisted tickers
common_delisted_tickers = list(set(aligned_tickers_fmp) & set(available_delisted_tickers_norgate))
print(f"Found {len(common_delisted_tickers)} common delisted tickers")
print(f"common_delisted_tickers: {common_delisted_tickers}")

# %%
delisted_tickers=['XLNX', 'ATH']
#find original tickers for delisted_tickers
available_delisted_tickers_norgate = [ticker.split(".csv")[0] for ticker in os.listdir("/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-norgate/us-eqt/US Equities Delisted")]
for ticker in available_delisted_tickers_norgate:
    if ticker.split("-")[0] in delisted_tickers:
        print(ticker)

# %%
# read all common_tickers
dfs=[]
for ticker in common_tickers:
    df = pd.read_csv(f"/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-norgate/us-eqt/US Equities/{ticker}.csv")
    dfs.append(df)

# read all common_delisted_tickers
common_delisted_tickers=["ATH-202112", "XLNX-202202"]
for ticker in common_delisted_tickers:
    df = pd.read_csv(f"/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-norgate/us-eqt/US Equities Delisted/{ticker}.csv")
    df['Symbol']=ticker.split("-")[0]
    dfs.append(df)

# %%
df = pd.concat(dfs)
df.to_parquet("../data/norgate_eod_stock_prices.parquet")

# %%