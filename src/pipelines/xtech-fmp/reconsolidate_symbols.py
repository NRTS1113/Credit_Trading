# # %%
# import importlib.util
# from pathlib import Path
# import pandas as pd

# df=pd.read_parquet("../../../datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Elektron_Timeseries_EOD.parquet")

# # %%
# Issuer_cols = ['RIC', 'Trade Date', 'Issuer OrgID', 'Issuer PermID','Issuer Name','Ticker']
# df_issuer=df[Issuer_cols]

# # %%
# df_issuer.to_parquet("../../../datastore/xtech-lseg/DATASCOPE/issuer_reference.parquet", engine="pyarrow")

# %%
import pandas as pd
import os
from pathlib import Path
df_issuer=pd.read_parquet("../../../datastore/xtech-lseg/DATASCOPE/issuer_reference.parquet")
symbols=list(df_issuer['Ticker'].unique())
issuer_name_symbol_map=dict(zip(df_issuer['Ticker'],df_issuer['Issuer Name']))

# Import symbol reconciler
from symbol_reconciler import CompanyNameMatcher

# Convert issuer_name_symbol_map to DataFrame format expected by reconciler
df_source_a = pd.DataFrame([
    {'symbol': symbol, 'issuer_name': name} 
    for symbol, name in issuer_name_symbol_map.items()
])

# Load FMP company profile data
fmp_parquet_path = Path(__file__).resolve().parents[3] / "datastore" / "xtech-fmp" / "fundamental" / "company_profile_bulk" / "PIT" / "date=2025-10-22" / "data.parquet"
df_source_b = pd.read_parquet(fmp_parquet_path)

print(f"\nSource A (LSEG): {len(df_source_a)} unique ticker-name pairs")
print(f"Source B (FMP): {len(df_source_b)} records")

# Initialize matcher with default thresholds
matcher = CompanyNameMatcher(
    high_confidence_threshold=90.0,
    medium_confidence_threshold=80.0,
    low_confidence_threshold=70.0
)

# Perform reconciliation
# process_mode options:
#   'both' - Process all stages (common symbols, only in A, only in B) [default]
#   'only_a' - Process common symbols and symbols only in source A (skip source B)
#   'only_b' - Process common symbols and symbols only in source B (skip source A)
#   'common_only' - Only process symbols that exist in both sources
print("\nStarting symbol reconciliation...")
exact_matches, cross_matches, unmatched = matcher.reconcile_sources(
    source_a=df_source_a,
    source_b=df_source_b,
    symbol_col_a='symbol',
    name_col_a='issuer_name',
    symbol_col_b='symbol',
    name_col_b='companyName',
    process_mode='only_a'  # Change this to control which stages to process
)

# Print summary
print(f"\n{'='*60}")
print(f"Reconciliation Summary")
print(f"{'='*60}")
print(f"Exact symbol matches: {len(exact_matches)}")
print(f"Cross-symbol matches: {len(cross_matches)}")
print(f"Unmatched: {len(unmatched)}")

if len(cross_matches) > 0:
    auto_accept = cross_matches[cross_matches['action'] == 'accept']
    manual_review = cross_matches[cross_matches['action'] == 'review']
    print(f"  - Auto-accept (high confidence): {len(auto_accept)}")
    print(f"  - Manual review (medium/low): {len(manual_review)}")

# Save reconciliation results
reconciliation_output_dir = Path(__file__).resolve().parents[3] / "datastore" / "xtech-fmp" / "reconciliation"
os.makedirs(reconciliation_output_dir, exist_ok=True)

exact_matches.to_csv(reconciliation_output_dir / 'exact_symbol_matches.csv', index=False)
cross_matches.to_csv(reconciliation_output_dir / 'cross_symbol_matches.csv', index=False)
unmatched.to_csv(reconciliation_output_dir / 'unmatched_symbols.csv', index=False)

print(f"\nReconciliation results saved to: {reconciliation_output_dir}")

# Create unified ticker list using reconciliation results
# Start with symbols that match exactly with high confidence
high_confidence_exact = exact_matches[exact_matches['confidence'] == 'high']['symbol'].tolist()

# Add symbols from cross-matches with high confidence (use symbol_b which is FMP symbol)
high_confidence_cross = cross_matches[cross_matches['confidence'] == 'high']['symbol_b'].tolist()

# Combine for final ticker list
tickers = list(set(high_confidence_exact + high_confidence_cross))
print(f"\nFinal ticker list: {len(tickers)} symbols (high confidence matches only)")


# %%
# Create a final matches df with standardized columns
# symbol_lseg, symbol_fmp, company_name_lseg, company_name_fmp, match_score, match_method, confidence, action, source

print("\nCreating final matches dataframe...")
import os
from pathlib import Path
import pandas as pd

# Read the CSV files
exact_matches_df = pd.read_csv(reconciliation_output_dir / 'exact_symbol_matches.csv')
cross_matches_df = pd.read_csv(reconciliation_output_dir / 'cross_symbol_matches.csv')

# Align column names for exact_matches
exact_matches_aligned = exact_matches_df.rename(columns={
    'symbol_a': 'symbol_lseg',
    'symbol_b': 'symbol_fmp',
    'name_a': 'company_name_lseg',
    'name_b': 'company_name_fmp'
})

# Align column names for cross_matches
cross_matches_aligned = cross_matches_df.rename(columns={
    'symbol_a': 'symbol_lseg',
    'symbol_b': 'symbol_fmp',
    'name_a': 'company_name_lseg',
    'name_b': 'company_name_fmp'
})

# Select only the columns we want in the final output
columns_to_keep = [
    'symbol_lseg', 'symbol_fmp', 
    'company_name_lseg', 'company_name_fmp',
    'match_score', 'match_method'
]

exact_matches_final = exact_matches_aligned[columns_to_keep]
cross_matches_final = cross_matches_aligned[columns_to_keep]

# subset
# Add subset column to indicate source
exact_matches_final = exact_matches_aligned[columns_to_keep].copy()
cross_matches_final = cross_matches_aligned[columns_to_keep].copy()
exact_matches_final.loc[:, 'subset'] = 'exact'
cross_matches_final.loc[:, 'subset'] = 'cross'

# Combine all matches
final_matches = pd.concat([exact_matches_final, cross_matches_final], ignore_index=True)

# Save to CSV
final_matches.to_csv(reconciliation_output_dir / 'final_matches.csv', index=False)

print(f"Final matches saved to: {reconciliation_output_dir / 'final_matches.csv'}")
print(f"Total matches: {len(final_matches)}")
print(f"  - From exact matches: {len(exact_matches_final)}")
print(f"  - From cross matches: {len(cross_matches_final)}")

# %%
