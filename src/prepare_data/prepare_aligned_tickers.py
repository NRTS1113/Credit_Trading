# %%
import pandas as pd
from pathlib import Path


# Load tickers from reconciliation file with proper encoding
df = pd.read_excel(Path(__file__).resolve().parents[2] / "datastore" / "xtech-fmp" / "reconciliation" / "final_matches_adjusted.xlsx")
df=df[df['match_method']=='exact_match']
aligned_tickers_fmp = df['symbol_fmp'].unique().tolist()
aligned_tickers_lseg = df['symbol_lseg'].unique().tolist()
print(f"Loaded {len(aligned_tickers_fmp)} unique tickers")
ticker_fmp_map_ticker_lseg=dict(zip(df['symbol_fmp'], df['symbol_lseg']))

df=pd.read_parquet("../../datastore/xtech-lseg/DATASCOPE/issuer_reference.parquet")
df=df[df['Ticker'].isin(aligned_tickers_lseg)]
aligned_rics=df['RIC'].unique().tolist()
print(f"total number of unique bond issuers(Ticker): {len(aligned_tickers_lseg)}")
print(f"total number of unique bonds(RIC): {len(aligned_rics)}")

ticker_lseg_map_ric=dict(zip(df['Ticker'], df['RIC']))


