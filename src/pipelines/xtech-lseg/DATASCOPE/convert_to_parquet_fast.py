"""
Ultra-fast streaming CSV to Parquet converter - optimized for maximum speed.
Use this when you need the fastest conversion and don't need detailed progress tracking.

Speed optimizations:
- No row counting (saves one full data pass)
- LZ4 compression (faster than snappy)
- No progress monitoring overhead
- Simplified output
"""

import polars as pl
import os
import time
import psutil

# Force maximum parallelism
os.environ['POLARS_MAX_THREADS'] = str(os.cpu_count() or 16)


def csv_to_parquet_fast(csv_path, numeric_patterns=None, compression='lz4'):
    """
    Ultra-fast CSV to Parquet conversion with minimal overhead.
    
    Parameters:
    -----------
    csv_path : str
        Path to the CSV file
    numeric_patterns : list of str, optional
        Column name patterns that should be treated as numeric
    compression : str, default='lz4'
        Compression codec: 'lz4' (fastest), 'snappy' (balanced), 
        'zstd' (best compression), 'uncompressed'
    
    Returns:
    --------
    str
        Path to the generated parquet file
    """
    # Default numeric patterns
    if numeric_patterns is None:
        numeric_patterns = [
            'price', 'yield', 'rate', 'spread', 'coupon', 
            'volume', 'amount', 'value', 'bid', 'ask', 'mid',
            'oas', 'duration', 'convexity', 'dv01', 'ytm', 'ytw',
            'accrued', 'proceeds', 'z-spread', 'g-spread',
            'open', 'high', 'low', 'close', 'vwap'
        ]
    
    exception_cols = ['Inverse Rate Marker']
    
    print(f"Fast mode: Converting {os.path.basename(csv_path)}")
    
    # File size for reporting
    file_size_gb = os.path.getsize(csv_path) / (1024**3)
    print(f"Input size: {file_size_gb:.2f} GB")
    
    # Scan CSV with speed optimizations
    lazy_df = pl.scan_csv(
        csv_path,
        infer_schema_length=10000,
        ignore_errors=True,
        low_memory=False,  # Trade memory for speed
        rechunk=False,     # Skip rechunking
    )
    
    # Get schema from first row
    first_row = lazy_df.head(1).collect()
    columns = first_row.columns
    
    # Identify columns to process
    cols_to_drop = []
    numeric_cols = []
    
    if 'Wertpapier' in columns:
        cols_to_drop.append('Wertpapier')
    
    for col in columns:
        if col in cols_to_drop:
            continue
        
        col_lower = col.lower()
        if col in exception_cols:
            should_be_numeric = False
        else:
            should_be_numeric = any(pattern in col_lower for pattern in numeric_patterns)
        
        if should_be_numeric:
            numeric_cols.append(col)
    
    print(f"Columns: {len(columns)}, Numeric conversions: {len(numeric_cols)}")
    
    # Apply transformations
    if cols_to_drop:
        lazy_df = lazy_df.drop(cols_to_drop)
    
    for col in numeric_cols:
        lazy_df = lazy_df.with_columns([
            pl.col(col).cast(pl.Float64, strict=False).alias(col)
        ])
    
    # Output path
    parquet_path = csv_path.replace('.csv', '.parquet')
    os.makedirs(os.path.dirname(parquet_path) or '.', exist_ok=True)
    
    # Track memory and time
    process = psutil.Process()
    start_memory = process.memory_info().rss / (1024**2)
    start_time = time.time()
    
    print(f"\nStreaming to parquet ({compression} compression)...")
    print("Processing... (no progress bar for maximum speed)")
    
    # TRUE STREAMING with optimal settings
    lazy_df.sink_parquet(
        parquet_path,
        compression=compression,
        maintain_order=False,  # Enable parallel processing
    )
    
    elapsed_time = time.time() - start_time
    end_memory = process.memory_info().rss / (1024**2)
    peak_memory = end_memory - start_memory
    output_size_gb = os.path.getsize(parquet_path) / (1024**3)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"✓ COMPLETED")
    print(f"{'='*60}")
    print(f"Output: {os.path.basename(parquet_path)} ({output_size_gb:.2f} GB)")
    print(f"Time: {elapsed_time:.1f}s ({elapsed_time/60:.1f} min)")
    print(f"Memory: ~{peak_memory:.0f} MB peak")
    print(f"Compression: {file_size_gb/output_size_gb:.1f}x")
    
    # Estimate rows processed (if you have the info)
    # For accurate row count, we'd need to count which adds overhead
    mb_per_sec = (file_size_gb * 1024) / elapsed_time
    print(f"Throughput: {mb_per_sec:.1f} MB/s")
    
    return parquet_path


def batch_convert(csv_files, compression='lz4'):
    """
    Convert multiple CSV files in batch.
    
    Parameters:
    -----------
    csv_files : list of str
        List of CSV file paths to convert
    compression : str
        Compression codec to use
    """
    print(f"Batch converting {len(csv_files)} files...")
    print(f"Using {os.environ.get('POLARS_MAX_THREADS', 'auto')} threads")
    print(f"Compression: {compression}\n")
    
    total_start = time.time()
    results = []
    
    for i, csv_file in enumerate(csv_files, 1):
        if not os.path.exists(csv_file):
            print(f"[{i}/{len(csv_files)}] SKIP: {csv_file} (not found)\n")
            continue
        
        print(f"[{i}/{len(csv_files)}]")
        try:
            parquet_path = csv_to_parquet_fast(csv_file, compression=compression)
            results.append((csv_file, parquet_path, True))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((csv_file, None, False))
        print()
    
    total_elapsed = time.time() - total_start
    
    # Summary
    successful = sum(1 for _, _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE")
    print(f"{'='*60}")
    print(f"Total time: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print(f"Successful: {successful}/{len(csv_files)}")
    
    return results


# Example usage
if __name__ == "__main__":
    # Single file conversion
    csv_file = "/Volumes/seb's ssd/Work/datastore/vendor-data/xtech-lseg/DataScope/filtered_bonds/Tick_History_Time_and_Sales_2018.csv"
    
    if os.path.exists(csv_file):
        csv_to_parquet_fast(csv_file, compression='lz4')
    else:
        print(f"File not found: {csv_file}")
    
    # Batch conversion example
    # csv_files = [
    #     "/path/to/file1.csv",
    #     "/path/to/file2.csv",
    # ]
    # batch_convert(csv_files, compression='lz4')
