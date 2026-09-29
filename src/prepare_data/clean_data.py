"""
Clean data files by removing columns with all missing values.
Also provides comprehensive data quality analysis.
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any
import time


def analyze_data_quality(df: pd.DataFrame, file_name: str) -> Dict[str, Any]:
    """
    Perform comprehensive data quality analysis (optimized for large datasets).
    
    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe
    file_name : str
        Name of the file being analyzed
        
    Returns
    -------
    Dict[str, Any]
        Dictionary containing quality metrics
    """
    quality_report = {}
    
    # Basic shape info
    quality_report['rows'] = len(df)
    quality_report['columns'] = len(df.columns)
    
    # Missing value analysis per column (optimized - single pass)
    missing_count = df.isna().sum()
    missing_stats = pd.DataFrame({
        'column': df.columns,
        'missing_count': missing_count.values,
        'missing_rate': (missing_count / len(df) * 100).values
    })
    missing_stats = missing_stats.sort_values('missing_rate', ascending=False)
    quality_report['missing_stats'] = missing_stats
    
    # Overall missing rate (reuse missing_count)
    total_cells = df.shape[0] * df.shape[1]
    missing_cells = missing_count.sum()
    quality_report['overall_missing_rate'] = (missing_cells / total_cells * 100) if total_cells > 0 else 0
    
    # Duplicate rows (skip for very large datasets)
    if len(df) < 10_000_000:  # Only check for datasets under 10M rows
        duplicate_count = df.duplicated().sum()
        quality_report['duplicate_rows'] = duplicate_count
        quality_report['duplicate_rate'] = (duplicate_count / len(df) * 100) if len(df) > 0 else 0
    else:
        quality_report['duplicate_rows'] = 'Skipped (dataset too large)'
        quality_report['duplicate_rate'] = 'N/A'
    
    # Data types
    quality_report['dtypes'] = df.dtypes.value_counts().to_dict()
    
    # Memory usage (shallow - much faster than deep=True)
    quality_report['memory_mb'] = df.memory_usage(deep=False).sum() / 1024 / 1024
    
    # Identify date columns and get date ranges
    date_columns = []
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            date_columns.append(col)
            non_null = df[col].dropna()
            if len(non_null) > 0:
                quality_report[f'{col}_range'] = {
                    'min': non_null.min(),
                    'max': non_null.max(),
                    'span_days': (non_null.max() - non_null.min()).days
                }
    quality_report['date_columns'] = date_columns
    
    # Numeric columns statistics (optimized)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if numeric_cols:
        quality_report['numeric_columns_count'] = len(numeric_cols)
        
        # Vectorized checks - much faster
        quality_report['columns_with_zeros'] = []
        quality_report['columns_with_negatives'] = []
        quality_report['columns_with_inf'] = []
        
        for col in numeric_cols:
            col_data = df[col]
            # Check for zeros (only if there are non-null values)
            if col_data.notna().any() and (col_data == 0).any():
                quality_report['columns_with_zeros'].append(col)
            # Check for negatives
            if col_data.notna().any() and (col_data < 0).any():
                quality_report['columns_with_negatives'].append(col)
            # Check for infinities
            if np.isinf(col_data).any():
                quality_report['columns_with_inf'].append(col)
    
    return quality_report


def print_quality_report(report: Dict[str, Any], file_name: str, report_file=None) -> None:
    """
    Print a formatted data quality report to console and optionally to a file.
    
    Parameters
    ----------
    report : Dict[str, Any]
        Quality report dictionary
    file_name : str
        Name of the file
    report_file : file object, optional
        File object to write the report to
    """
    def write_line(line: str):
        """Helper to write to both console and file"""
        print(line)
        if report_file:
            report_file.write(line + "\n")
    
    write_line(f"\n{'='*80}")
    write_line(f"DATA QUALITY REPORT: {file_name}")
    write_line(f"{'='*80}")
    
    # Basic info
    write_line(f"\n📊 BASIC INFO:")
    write_line(f"  Shape: {report['rows']:,} rows × {report['columns']} columns")
    write_line(f"  Memory: {report['memory_mb']:.2f} MB (estimated)")
    
    # Handle duplicate reporting (may be skipped for large datasets)
    if isinstance(report['duplicate_rows'], str):
        write_line(f"  Duplicate rows: {report['duplicate_rows']}")
    else:
        write_line(f"  Duplicate rows: {report['duplicate_rows']:,} ({report['duplicate_rate']:.2f}%)")
    
    # Missing value analysis
    write_line(f"\n❌ MISSING VALUES:")
    write_line(f"  Overall missing rate: {report['overall_missing_rate']:.2f}%")
    
    missing_stats = report['missing_stats']
    high_missing = missing_stats[missing_stats['missing_rate'] > 0]
    
    if len(high_missing) > 0:
        write_line(f"  Columns with missing values: {len(high_missing)}/{report['columns']}")
        write_line(f"\n  Top columns by missing rate:")
        for idx, row in high_missing.head(10).iterrows():
            write_line(f"    • {row['column']:<40} {row['missing_count']:>8,} ({row['missing_rate']:>6.2f}%)")
        
        if len(high_missing) > 10:
            write_line(f"    ... and {len(high_missing) - 10} more columns with missing values")
    else:
        write_line(f"  ✓ No missing values found")
    
    # Columns with all missing values
    all_missing = missing_stats[missing_stats['missing_rate'] == 100]
    if len(all_missing) > 0:
        write_line(f"\n  ⚠️  Columns with 100% missing: {list(all_missing['column'].values)}")
    
    # Data types
    write_line(f"\n📝 DATA TYPES:")
    for dtype, count in report['dtypes'].items():
        write_line(f"  {str(dtype):<20} {count:>3} columns")
    
    # Date ranges
    if report['date_columns']:
        write_line(f"\n📅 DATE COLUMNS:")
        for col in report['date_columns']:
            range_key = f'{col}_range'
            if range_key in report and report[range_key]:
                date_range = report[range_key]
                write_line(f"  {col}:")
                write_line(f"    Range: {date_range['min']} to {date_range['max']}")
                if date_range['span_days'] is not None:
                    write_line(f"    Span: {date_range['span_days']:,} days")
    
    # Numeric columns analysis
    if 'numeric_columns_count' in report:
        write_line(f"\n🔢 NUMERIC COLUMNS: {report['numeric_columns_count']} columns")
        if report['columns_with_zeros']:
            write_line(f"  Columns with zeros: {len(report['columns_with_zeros'])}")
        if report['columns_with_negatives']:
            write_line(f"  Columns with negatives: {len(report['columns_with_negatives'])}")
        if report['columns_with_inf']:
            write_line(f"  ⚠️  Columns with infinite values: {report['columns_with_inf']}")
    
    write_line(f"\n{'='*80}\n")


def drop_all_missing_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop columns where all values are missing.
    
    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe
        
    Returns
    -------
    pd.DataFrame
        Dataframe with all-missing columns removed
    """
    # Get columns where all values are missing
    all_missing_cols = df.columns[df.isna().all()].tolist()
    
    if all_missing_cols:
        print(f"  🗑️  Dropping {len(all_missing_cols)} columns with all missing values: {all_missing_cols}")
        df = df.drop(columns=all_missing_cols)
    
    return df


def clean_parquet_file(file_path: str, report_file=None) -> float:
    """
    Clean a single parquet file and analyze its data quality.
    
    Parameters
    ----------
    file_path : str
        Path to the parquet file
    report_file : file object, optional
        File object to write the quality report to
        
    Returns
    -------
    float
        Time taken to process the file in seconds
    """
    start_time = time.time()
    file_name = os.path.basename(file_path)
    
    # Read the file
    read_start = time.time()
    df = pd.read_parquet(file_path)
    read_time = time.time() - read_start
    
    # Analyze data quality
    analysis_start = time.time()
    quality_report = analyze_data_quality(df, file_name)
    analysis_time = time.time() - analysis_start
    
    # Print to console and optionally to file
    print_quality_report(quality_report, file_name, report_file=report_file)
    
    # Drop all-missing columns
    df_cleaned = drop_all_missing_columns(df)
    
    # Save the cleaned file
    if df_cleaned.shape != df.shape:
        save_start = time.time()
        df_cleaned.to_parquet(file_path)
        save_time = time.time() - save_start
        message = f"  ✓ Saved cleaned file (shape: {df.shape} → {df_cleaned.shape})"
    else:
        save_time = 0
        message = f"  ✓ No changes needed"
    
    print(message)
    if report_file:
        report_file.write(message + "\n")
    
    total_time = time.time() - start_time
    timing_msg = f"  ⏱️  Timing: Read {read_time:.2f}s | Analysis {analysis_time:.2f}s | Save {save_time:.2f}s | Total {total_time:.2f}s"
    print(timing_msg)
    if report_file:
        report_file.write(timing_msg + "\n\n")
    
    return total_time


def clean_all_data_files(data_dir: str = "../data", save_reports: bool = False) -> None:
    """
    Clean all parquet files in the data directory and analyze their quality.
    
    Parameters
    ----------
    data_dir : str
        Path to the data directory (relative to this script)
    save_reports : bool
        Whether to save all quality reports to a single text file
    """
    overall_start = time.time()
    
    # Get absolute path
    script_dir = Path(__file__).parent
    data_path = (script_dir / data_dir).resolve()
    
    print("\n" + "="*80)
    print(f"DATA QUALITY ANALYSIS AND CLEANING (Optimized)")
    print("="*80)
    print(f"\nData directory: {data_path}")
    
    # Find all parquet files, exclude quality report files
    parquet_files = [f for f in data_path.glob("*.parquet") if not str(f).endswith('_quality_report.parquet')]
    
    if not parquet_files:
        print("No parquet files found")
        return
    
    print(f"Found {len(parquet_files)} parquet files to analyze\n")
    
    # Open report file if saving
    report_file = None
    report_path = None
    if save_reports:
        report_path = data_path / "data_quality_report.txt"
        report_file = open(report_path, 'w', encoding='utf-8')
        # Write header to file
        report_file.write("="*80 + "\n")
        report_file.write(f"DATA QUALITY ANALYSIS AND CLEANING REPORT\n")
        report_file.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        report_file.write(f"Data directory: {data_path}\n")
        report_file.write(f"Total files: {len(parquet_files)}\n")
        report_file.write("="*80 + "\n\n")
    
    try:
        # Process each file and track timing
        total_file_time = 0
        for i, file_path in enumerate(parquet_files, 1):
            header = f"\n[{i}/{len(parquet_files)}]"
            print(header)
            if report_file:
                report_file.write(header + "\n")
            
            file_time = clean_parquet_file(str(file_path), report_file=report_file)
            total_file_time += file_time
    finally:
        # Always close the file if it was opened
        if report_file:
            # Write summary to file
            report_file.write("\n" + "="*80 + "\n")
            report_file.write(f"✓ COMPLETED: Analyzed and cleaned {len(parquet_files)} files\n")
            overall_time = time.time() - overall_start
            report_file.write(f"⏱️  Total time: {overall_time:.2f}s ({overall_time/60:.2f} minutes)\n")
            report_file.write(f"⏱️  Average per file: {total_file_time/len(parquet_files):.2f}s\n")
            report_file.write("="*80 + "\n")
            report_file.close()
    
    overall_time = time.time() - overall_start
    
    print("\n" + "="*80)
    print(f"✓ COMPLETED: Analyzed and cleaned {len(parquet_files)} files")
    print(f"⏱️  Total time: {overall_time:.2f}s ({overall_time/60:.2f} minutes)")
    print(f"⏱️  Average per file: {total_file_time/len(parquet_files):.2f}s")
    if save_reports:
        print(f"📊 Quality report saved to: {report_path}")
    print("="*80 + "\n")


if __name__ == "__main__":
    import sys
    
    # Check if user wants to save reports
    save_reports = '--save-reports' in sys.argv or '-s' in sys.argv
    
    clean_all_data_files(save_reports=save_reports)
