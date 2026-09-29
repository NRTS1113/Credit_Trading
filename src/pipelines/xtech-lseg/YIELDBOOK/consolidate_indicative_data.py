#!/usr/bin/env python3
"""
Consolidate all ISIN-partitioned indicative data into consolidated parquet files.

This script scans all isin=* directories in the indicative folder and combines
the individual parquet files into consolidated files in the _consolidated directory.
"""

import polars as pl
import pandas as pd
import os
from pathlib import Path
from tqdm import tqdm
import json
import argparse

def consolidate_indicative_data(base_path="/Volumes/seb's ssd/Work/datastore/yieldbook/indicative"):
    """
    Consolidate all ISIN-partitioned data into consolidated files.
    
    Args:
        base_path: Base path to the indicative data directory
    """
    
    print(f"Consolidating indicative data from: {base_path}")
    
    if not os.path.exists(base_path):
        print(f"Error: Base path {base_path} does not exist")
        return
    
    # Create consolidated directory
    consolidated_dir = os.path.join(base_path, "_consolidated")
    os.makedirs(consolidated_dir, exist_ok=True)
    
    # Find all ISIN directories
    isin_dirs = [d for d in os.listdir(base_path) 
                 if d.startswith("isin=") and os.path.isdir(os.path.join(base_path, d))]
    
    print(f"Found {len(isin_dirs)} ISIN directories to process")
    
    if not isin_dirs:
        print("No ISIN directories found. Nothing to consolidate.")
        return
    
    # Define the expected parquet files and their consolidated names
    file_mappings = {
        "securities.parquet": "all_securities.parquet",
        "ratings_history.parquet": "all_ratings_history.parquet", 
        "underwriters.parquet": "all_underwriters.parquet",
        "esg_scores.parquet": "all_esg_scores.parquet",
        "frtb_data.parquet": "all_frtb_data.parquet"
    }
    
    # Process each file type
    for source_file, consolidated_file in file_mappings.items():
        print(f"\nProcessing {source_file} -> {consolidated_file}")
        
        dataframes = []
        processed_count = 0
        error_count = 0
        
        # Collect data from all ISIN directories
        schemas_seen = set()
        
        for isin_dir in tqdm(isin_dirs, desc=f"Collecting {source_file}"):
            file_path = os.path.join(base_path, isin_dir, source_file)
            
            if os.path.exists(file_path):
                try:
                    # Use polars for efficient reading
                    df = pl.read_parquet(file_path)
                    
                    # Only add non-empty dataframes
                    if len(df) > 0:
                        # Track schema variations
                        schema_key = tuple(sorted(df.columns))
                        schemas_seen.add(schema_key)
                        
                        dataframes.append(df)
                        processed_count += 1
                    
                except Exception as e:
                    print(f"Warning: Error reading {file_path}: {e}")
                    error_count += 1
        
        # Handle schema mismatches
        if len(schemas_seen) > 1:
            print(f"⚠️  Multiple schemas detected for {source_file}:")
            for i, schema in enumerate(schemas_seen):
                print(f"   Schema {i+1}: {list(schema)}")
            
            # Align schemas by finding common columns
            if dataframes:
                all_columns = set()
                for df in dataframes:
                    all_columns.update(df.columns)
                
                # Standardize all dataframes to have the same columns
                aligned_dataframes = []
                for df in dataframes:
                    # Add missing columns with null values
                    for col in all_columns:
                        if col not in df.columns:
                            df = df.with_columns(pl.lit(None).alias(col))
                    
                    # Reorder columns consistently
                    df = df.select(sorted(all_columns))
                    aligned_dataframes.append(df)
                
                dataframes = aligned_dataframes
                print(f"   ✅ Aligned {len(dataframes)} dataframes to common schema")
        
        # Consolidate and write if we have data
        if dataframes:
            try:
                # Concatenate all dataframes
                consolidated_df = pl.concat(dataframes, how="vertical")
                
                # Write consolidated file
                output_path = os.path.join(consolidated_dir, consolidated_file)
                consolidated_df.write_parquet(
                    output_path,
                    compression="zstd",
                    statistics=True
                )
                
                print(f"✅ {consolidated_file}: {len(consolidated_df):,} records from {processed_count} ISINs")
                
                # Print summary statistics
                if "isin" in consolidated_df.columns:
                    unique_isins = consolidated_df["isin"].n_unique()
                    print(f"   - Unique ISINs: {unique_isins:,}")
                
            except Exception as e:
                print(f"❌ Error consolidating {consolidated_file}: {e}")
        else:
            print(f"⚠️  No data found for {consolidated_file}")
        
        if error_count > 0:
            print(f"   - Errors encountered: {error_count}")
    
    # Generate summary statistics
    generate_consolidation_summary(consolidated_dir, len(isin_dirs))
    
    print(f"\n🎉 Consolidation complete! Files saved to: {consolidated_dir}")

def generate_consolidation_summary(consolidated_dir, total_isin_dirs):
    """Generate a summary of the consolidation process"""
    
    summary = {
        "consolidation_timestamp": pd.Timestamp.now().isoformat(),
        "total_isin_directories": total_isin_dirs,
        "consolidated_files": {}
    }
    
    # Check each consolidated file
    for file_name in ["all_securities.parquet", "all_ratings_history.parquet", 
                      "all_underwriters.parquet", "all_esg_scores.parquet", "all_frtb_data.parquet"]:
        
        file_path = os.path.join(consolidated_dir, file_name)
        
        if os.path.exists(file_path):
            try:
                # Get basic file info
                file_size = os.path.getsize(file_path)
                
                # Read with polars to get record count efficiently
                df = pl.scan_parquet(file_path)
                record_count = df.select(pl.count()).collect().item()
                
                # Get unique ISINs if column exists
                unique_isins = None
                try:
                    unique_isins = df.select(pl.col("isin").n_unique()).collect().item()
                except:
                    pass
                
                summary["consolidated_files"][file_name] = {
                    "exists": True,
                    "file_size_mb": round(file_size / (1024 * 1024), 2),
                    "record_count": record_count,
                    "unique_isins": unique_isins
                }
                
            except Exception as e:
                summary["consolidated_files"][file_name] = {
                    "exists": True,
                    "error": str(e)
                }
        else:
            summary["consolidated_files"][file_name] = {
                "exists": False
            }
    
    # Save summary
    summary_path = os.path.join(consolidated_dir, "consolidation_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n📊 Consolidation Summary:")
    print(f"   - Total ISIN directories processed: {total_isin_dirs}")
    
    for file_name, info in summary["consolidated_files"].items():
        if info.get("exists"):
            if "record_count" in info:
                print(f"   - {file_name}: {info['record_count']:,} records, {info['file_size_mb']} MB")
                if info.get("unique_isins"):
                    print(f"     └── Unique ISINs: {info['unique_isins']:,}")
            else:
                print(f"   - {file_name}: Error - {info.get('error', 'Unknown')}")
        else:
            print(f"   - {file_name}: Not created (no data)")
    
    print(f"   - Summary saved to: {summary_path}")

def verify_consolidated_data(consolidated_dir):
    """Verify the integrity of consolidated data"""
    
    print(f"\n🔍 Verifying consolidated data in: {consolidated_dir}")
    
    files_to_check = [
        "all_securities.parquet",
        "all_ratings_history.parquet", 
        "all_underwriters.parquet",
        "all_esg_scores.parquet",
        "all_frtb_data.parquet"
    ]
    
    for file_name in files_to_check:
        file_path = os.path.join(consolidated_dir, file_name)
        
        if os.path.exists(file_path):
            try:
                df = pl.scan_parquet(file_path)
                
                # Basic checks
                record_count = df.select(pl.count()).collect().item()
                
                if record_count > 0:
                    # Check for duplicates if ISIN column exists
                    if "isin" in df.columns:
                        duplicates = df.group_by("isin").agg(pl.count().alias("count")).filter(pl.col("count") > 1)
                        duplicate_count = duplicates.select(pl.count()).collect().item()
                        
                        if duplicate_count > 0:
                            print(f"⚠️  {file_name}: {duplicate_count} ISINs have duplicate records")
                        else:
                            print(f"✅ {file_name}: No duplicates found")
                    else:
                        print(f"✅ {file_name}: {record_count:,} records")
                else:
                    print(f"⚠️  {file_name}: Empty file")
                    
            except Exception as e:
                print(f"❌ {file_name}: Error during verification - {e}")
        else:
            print(f"❌ {file_name}: File not found")

def main():
    """Main function with command line argument support"""
    
    parser = argparse.ArgumentParser(description="Consolidate YieldBook indicative data")
    parser.add_argument(
        "--base-path", 
        default="/Volumes/seb's ssd/Work/datastore/yieldbook/indicative",
        help="Base path to the indicative data directory"
    )
    parser.add_argument(
        "--verify", 
        action="store_true",
        help="Verify consolidated data after creation"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("YieldBook Indicative Data Consolidation")
    print("=" * 60)
    
    # Run consolidation
    consolidate_indicative_data(args.base_path)
    
    # Run verification if requested
    if args.verify:
        consolidated_dir = os.path.join(args.base_path, "_consolidated")
        verify_consolidated_data(consolidated_dir)
    
    print("\n" + "=" * 60)
    print("Consolidation process completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
