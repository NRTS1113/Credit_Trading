# %%
import duckdb
import pandas as pd
import polars as pl
from prepare_aligned_tickers import aligned_rics

# %% Read EOD Price Data
df=pd.read_parquet("../../datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Elektron_Timeseries_EOD.parquet")

# Filter to aligned_rics
df=df[df['RIC'].isin(aligned_rics)]

# Drop useless cols and cols has too much missing data
df.drop(columns=['Valoren','Usage Instrument Type',
                'Usage Instrument SubType','Trading Status',
                'Reuters Editorial RIC','Refinitiv Classification Scheme Description',
                'Refinitiv Classification Scheme','RCP ID','Quote PermID','PE Code'], inplace=True)

# Price columns
price_cols = [
    'RIC',  # Reuters Instrument Code - unique identifier for the security
    'Trade Date',  # Trading date for the price data
    'Open Ask',  # Opening ask (sell) price for the day
    'Open Bid',  # Opening bid (buy) price for the day
    'Ask High',  # Highest ask (sell) price during the day
    'Bid High',  # Highest bid (buy) price during the day
    'Low Ask',  # Lowest ask (sell) price during the day
    'Low Bid',  # Lowest bid (buy) price during the day
    'Ask',  # Current/closing ask (sell) price
    'Bid',  # Current/closing bid (buy) price
    'Average of Bid and Ask',  # Mid-price calculated as average of bid and ask
    'Universal Ask Price',  # Standardized ask price across all markets
    'Universal Bid Price',  # Standardized bid price across all markets
    'Universal Close Price',  # Standardized closing price across all markets
]

# Yield columns
yield_cols = [
    'RIC',  # Reuters Instrument Code - unique identifier for the security
    'Trade Date',  # Trading date for the yield data
    'Open Yield',  # Opening yield for the day (yield to maturity)
    'Low Yield',  # Lowest yield during the day
    'High Yield',  # Highest yield during the day
    'Ask Yield',  # Yield based on ask price (lower yield due to higher price)
    'Bid Yield',  # Yield based on bid price (higher yield due to lower price)
    'Close Yield',  # Closing yield for the day
]

# Characteristic columns (metadata and identifiers)
characteristic_cols = [
    'RIC',  # Reuters Instrument Code - unique identifier for the security, e.g., '10373QAC4='
    'Trade Date',  # Trading date for the record, e.g., '09/24/2018'
    'Asset ID',  # Unique hex identifier for the asset, e.g., '0x00102c49b2df150d'
    'Asset Status',  # Current status code of the asset, e.g., 'ISS' (Issued)
    'Asset Status Description',  # Human-readable asset status, e.g., 'Issued'
    'Asset SubType',  # Industry classification code, e.g., 'CFIN' (Financials)
    'Asset SubType Description',  # Industry classification description, e.g., 'Financials'
    'Asset Type',  # Broad asset category code, e.g., 'CORP' (Corporate bond)
    'Asset Type Description',  # Asset category description, e.g., 'Corporate'
    'Country of Incorporation',  # ISO country code of issuer incorporation, e.g., 'US'
    'Country of Incorporation Description',  # Full country name, e.g., 'United States'
    'Currency Code',  # ISO currency code for the bond, e.g., 'USD'
    'Currency Code Description',  # Full currency name, e.g., 'US Dollar'
    'ESMA Standard Market Size Currency Code',  # European regulatory standard currency, e.g., 'EUR'
    'Exchange Code',  # Market/exchange code where traded, e.g., 'CPN'
    'Exchange Description',  # Full exchange name, e.g., 'REFINITIV COMPOSITE AMER'
    'Instrument ID',  # Primary instrument identifier (usually RIC), e.g., '10373QAC4='
    'Instrument ID Type',  # Type of instrument identifier used, e.g., 'RIC'
    'Issue PermID',  # Refinitiv Permanent ID for the bond issue, e.g., 192812541152.0
    'Issuer Name',  # Full legal name of the bond issuer, e.g., 'BP CAPITAL MARKETS AMERICA INC'
    'Issuer OrgID',  # Organization ID for the issuer, e.g., 100030700.0
    'Issuer PermID',  # Refinitiv Permanent ID for the issuer entity, e.g., 5000029986.0
    'Quote ID',  # Unique hex identifier for the quote, e.g., '0x00102c7e2ff7158f'
    'Reference Company',  # Abbreviated company reference name, e.g., 'BP CAP MKTS AMER'
    'Security Description',  # Full bond description with coupon and maturity, e.g., 'BP 3.937 09/21/28 \'28'
    'Ticker',  # Stock ticker symbol of the parent company, e.g., 'BP'
]


# Convert Trade Date to datetime
df['Trade Date']=pd.to_datetime(df['Trade Date'], format='%m/%d/%Y')

# Use RIC and Trade Date as identifiers (primary key) and sort by them
df_price=df[price_cols].sort_values(by=['RIC','Trade Date'])
df_yield=df[yield_cols].sort_values(by=['RIC','Trade Date'])
df_characteristic=df[characteristic_cols].sort_values(by=['RIC','Trade Date'])

# Reset index and drop old index
df_price.reset_index(drop=True, inplace=True)
df_yield.reset_index(drop=True, inplace=True)
df_characteristic.reset_index(drop=True, inplace=True)

# save to parquet in ../data
df_price.to_parquet('../data/datascope_price_eod.parquet')
df_yield.to_parquet('../data/datascope_yield_eod.parquet')
df_characteristic.to_parquet('../data/datascope_characteristic_eod.parquet')

# %% Read resampled daily data
# Read all resampled_daily_combined.parquet files from 2018 to 2025
import glob
import os

dfs = []
for year in range(2018, 2026):  # 2018 to 2025 inclusive
    file_path = f'../../datastore/xtech-lseg/DATASCOPE/resampled_daily/{year}/resampled_daily_combined.parquet'
    if os.path.exists(file_path):
        df_year = pd.read_parquet(file_path)
        dfs.append(df_year)

# Concatenate all dataframes
df_resampled = pd.concat(dfs, ignore_index=True)

print(df_resampled.head())

# Filter to aligned_rics
df_resampled = df_resampled[df_resampled['#RIC'].isin(aligned_rics)]

# Save complete dataframe with all columns
df_resampled_sorted = df_resampled.sort_values(by=['#RIC', 'Date-Time']).reset_index(drop=True)

# Convert all numeric columns to proper types to avoid ArrowInvalid error
# Exclude identifier and string columns
non_numeric_cols = ['#RIC', 'Date-Time', 'Domain', 'Ex/Cntrb.ID', 'Qualifiers', 'Date', 'Exch Time']
numeric_cols_complete = [col for col in df_resampled_sorted.columns if col not in non_numeric_cols]
for col in numeric_cols_complete:
    df_resampled_sorted[col] = pd.to_numeric(df_resampled_sorted[col], errors='coerce')

df_resampled_sorted.to_parquet('../data/datascope_eod_resampled_from_tick_complete.parquet')

# Price columns
price_cols_tick = [
    '#RIC',  # Reuters Instrument Code - unique identifier for the security
    'Date-Time',  # Timestamp of the quote
    'Bid Price',  # Bid (buy) price for the quote
    'Ask Price',  # Ask (sell) price for the quote
    'Mid Price',  # Mid-price calculated as average of bid and ask
    'Open',  # Opening price for the day
    'High',  # Highest price during the day
    'Low',  # Lowest price during the day
    'Net Change',  # Net price change from previous quote
]

# Yield columns
yield_cols_tick = [
    '#RIC',  # Reuters Instrument Code - unique identifier for the security
    'Date-Time',  # Timestamp of the quote
    'Bid Yld',  # Yield based on bid price
    'Ask Yld',  # Yield based on ask price
    'Mid Yield',  # Mid-yield calculated as average of bid and ask yields
    'ISMA Bid Yld',  # ISMA bid yield
    'ISMA Ask Yld',  # ISMA ask yield
    'Open Yld',  # Opening yield for the day
    'High Yld',  # Highest yield during the day
    'Low Yld',  # Lowest yield during the day
]

# Risk metrics columns
risk_cols_tick = [
    '#RIC',  # Reuters Instrument Code - unique identifier for the security
    'Date-Time',  # Timestamp of the quote
    'Duration',  # Macaulay duration in years
    'Mod Durtn',  # Modified duration (price sensitivity to yield changes)
    'BPV',  # Basis Point Value (dollar change per 1bp yield move)
    'Convexity',  # Convexity (second-order price sensitivity)
    'Bench Spd',  # Benchmark spread in basis points
    'Swp Spd',  # Swap spread in basis points
    'Asst Swp Spd',  # Asset swap spread in basis points
    '1M Basis Asset Swap Spread',  # 1-month basis asset swap spread
    '3M Basis Asset Swap Spread',  # 3-month basis asset swap spread
    '6M Basis Asset Swap Spread',  # 6-month basis asset swap spread
    'Z Spread',  # Z-spread (spread over zero-coupon curve)
    'Premium',  # Premium over par value
]

# Metadata columns
metadata_cols_tick = [
    '#RIC',  # Reuters Instrument Code - unique identifier for the security
    'Date-Time',  # Timestamp of the quote
    'Domain',  # Data domain type
    'GMT Offset',  # GMT timezone offset in hours
    'Ex/Cntrb.ID',  # Exchange or contributor identifier
    'Exch Time',  # Exchange-reported time of the quote
    'Qualifiers',  # Quote qualifier codes indicating data quality/type
    'Date',  # Trade date (date only, no time)
]

# Convert Date-Time to datetime
df_resampled['Date-Time'] = pd.to_datetime(df_resampled['Date-Time'])
if 'Date' in df_resampled.columns:
    df_resampled['Date'] = pd.to_datetime(df_resampled['Date'])

# Filter columns that exist in the dataframe
price_cols_available = [col for col in price_cols_tick if col in df_resampled.columns]
yield_cols_available = [col for col in yield_cols_tick if col in df_resampled.columns]
risk_cols_available = [col for col in risk_cols_tick if col in df_resampled.columns]
metadata_cols_available = [col for col in metadata_cols_tick if col in df_resampled.columns]

# Create separate dataframes and sort by identifiers
df_price_tick = df_resampled[price_cols_available].sort_values(by=['#RIC', 'Date-Time'])
df_yield_tick = df_resampled[yield_cols_available].sort_values(by=['#RIC', 'Date-Time'])
df_risk_tick = df_resampled[risk_cols_available].sort_values(by=['#RIC', 'Date-Time'])
df_metadata_tick = df_resampled[metadata_cols_available].sort_values(by=['#RIC', 'Date-Time'])

# Reset index and drop old index
df_price_tick.reset_index(drop=True, inplace=True)
df_yield_tick.reset_index(drop=True, inplace=True)
df_risk_tick.reset_index(drop=True, inplace=True)
df_metadata_tick.reset_index(drop=True, inplace=True)

# Convert numeric columns to proper types to avoid ArrowTypeError
# For price columns (exclude RIC and Date-Time which are identifiers)
numeric_price_cols = [col for col in df_price_tick.columns if col not in ['#RIC', 'Date-Time']]
for col in numeric_price_cols:
    df_price_tick[col] = pd.to_numeric(df_price_tick[col], errors='coerce')

# For yield columns
numeric_yield_cols = [col for col in df_yield_tick.columns if col not in ['#RIC', 'Date-Time']]
for col in numeric_yield_cols:
    df_yield_tick[col] = pd.to_numeric(df_yield_tick[col], errors='coerce')

# For risk columns
numeric_risk_cols = [col for col in df_risk_tick.columns if col not in ['#RIC', 'Date-Time']]
for col in numeric_risk_cols:
    df_risk_tick[col] = pd.to_numeric(df_risk_tick[col], errors='coerce')

# For metadata columns (only convert numeric ones, preserve strings)
numeric_metadata_cols = [col for col in df_metadata_tick.columns if col not in ['#RIC', 'Date-Time', 'Domain', 'Ex/Cntrb.ID', 'Qualifiers', 'Date', 'Exch Time']]
for col in numeric_metadata_cols:
    df_metadata_tick[col] = pd.to_numeric(df_metadata_tick[col], errors='coerce')

# Save to parquet in ../data
df_price_tick.to_parquet('../data/datascope_price_eod_resampled_from_tick.parquet')
df_yield_tick.to_parquet('../data/datascope_yield_eod_resampled_from_tick.parquet')
df_risk_tick.to_parquet('../data/datascope_risk_eod_resampled_from_tick.parquet')
df_metadata_tick.to_parquet('../data/datascope_metadata_eod_resampled_from_tick.parquet')
# %%
