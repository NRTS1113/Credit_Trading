"""
Resample tick data to daily or hourly frequency using DuckDB and Polars.
Processes one RIC at a time to avoid loading all data into memory.
"""
# %%
import duckdb
import polars as pl
from pathlib import Path
from tqdm import tqdm
from typing import Literal

# Import aligned RICs from prepare_aligned_tickers
import sys
sys.path.append(str(Path(__file__).parent))
from prepare_aligned_tickers import aligned_rics


def resample_tick_to_ohlc(
    tick_data_path: str,
    output_dir: str,
    frequency: Literal["1d", "1h"] = "1d",
    ric_list: list[str] | None = None,
) -> None:
    """
    Resample tick data to daily or hourly OHLC (last value) data.
    
    Args:
        tick_data_path: Path to the tick data parquet file
        output_dir: Directory to save resampled data
        frequency: Resampling frequency ("1d" for daily, "1h" for hourly)
        ric_list: List of RICs to process. If None, uses aligned_rics
    """
    tick_data_path = Path(tick_data_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if ric_list is None:
        ric_list = aligned_rics
    
    print(f"Processing {len(ric_list)} RICs from {tick_data_path}")
    print(f"Resampling to {frequency} frequency")
    
    # Connect to DuckDB
    con = duckdb.connect()
    
    # Process each RIC one at a time
    for ric in tqdm(ric_list, desc="Processing RICs"):
        try:
            # Query only this RIC's data using DuckDB (no full data load)
            query = f"""
                SELECT *
                FROM read_parquet('{tick_data_path}')
                WHERE "#RIC" = '{ric}'
                ORDER BY "Date-Time"
            """
            
            # Convert DuckDB result to Polars DataFrame
            df_ric = con.execute(query).pl()
            
            if df_ric.height == 0:
                print(f"  No data found for RIC: {ric}")
                continue
            
            # Ensure Date-Time is datetime type
            if df_ric["Date-Time"].dtype != pl.Datetime:
                df_ric = df_ric.with_columns(
                    pl.col("Date-Time").str.to_datetime(time_zone="UTC")
                )
            
            # Resample to specified frequency (take last value in each period)
            df_resampled = (
                df_ric
                .sort("Date-Time")
                .group_by_dynamic("Date-Time", every=frequency)
                .agg([
                    pl.all().last()  # Take last value for all columns
                ])
            )
            
            # Save to parquet with RIC in filename
            safe_ric_name = ric.replace(".", "_").replace("=", "_")
            output_file = output_dir / f"{safe_ric_name}_{frequency}.parquet"
            df_resampled.write_parquet(output_file)
            
        except Exception as e:
            print(f"  Error processing RIC {ric}: {e}")
            continue
    
    con.close()
    print(f"Completed! Output saved to {output_dir}")


def resample_tick_to_single_file(
    tick_data_path: str,
    output_file: str,
    frequency: Literal["1d", "1h"] = "1d",
    ric_list: list[str] | None = None,
) -> None:
    """
    Resample tick data to daily or hourly data and save as a single parquet file.
    
    Args:
        tick_data_path: Path to the tick data parquet file
        output_file: Path to save the combined resampled data
        frequency: Resampling frequency ("1d" for daily, "1h" for hourly)
        ric_list: List of RICs to process. If None, uses aligned_rics
    """
    tick_data_path = Path(tick_data_path)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    if ric_list is None:
        ric_list = aligned_rics
    
    print(f"Processing {len(ric_list)} RICs from {tick_data_path}")
    print(f"Resampling to {frequency} frequency")
    
    # Connect to DuckDB
    con = duckdb.connect()
    
    all_resampled = []
    
    # Process each RIC one at a time
    for ric in tqdm(ric_list, desc="Processing RICs"):
        try:
            # Query only this RIC's data using DuckDB (no full data load)
            query = f"""
                SELECT *
                FROM read_parquet('{tick_data_path}')
                WHERE "#RIC" = '{ric}'
                ORDER BY "Date-Time"
            """
            
            # Convert DuckDB result to Polars DataFrame
            df_ric = con.execute(query).pl()
            
            if df_ric.height == 0:
                continue
            
            # Ensure Date-Time is datetime type
            if df_ric["Date-Time"].dtype != pl.Datetime:
                df_ric = df_ric.with_columns(
                    pl.col("Date-Time").str.to_datetime(time_zone="UTC")
                )
            
            # Resample to specified frequency (take last value in each period)
            df_resampled = (
                df_ric
                .sort("Date-Time")
                .group_by_dynamic("Date-Time", every=frequency)
                .agg([
                    pl.all().last()  # Take last value for all columns
                ])
            )
            
            all_resampled.append(df_resampled)
            
        except Exception as e:
            print(f"  Error processing RIC {ric}: {e}")
            continue
    
    # Combine all resampled data
    if all_resampled:
        combined_df = pl.concat(all_resampled)
        combined_df.write_parquet(output_file)
        print(f"Completed! Output saved to {output_file}")
        print(f"Total rows: {combined_df.height}")
    else:
        print("No data was processed!")
    
    con.close()

# %%
# if __name__ == "__main__":
#     # Example usage
#     tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2025.parquet"
    
#     # Option 1: Save each RIC to separate file
#     output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2025"
#     resample_tick_to_ohlc(
#         tick_data_path=tick_data_path,
#         output_dir=output_dir,
#         frequency="1d"
#     )

#     # Then concatenate all separated files into a single file
#     output_dir_path = Path(output_dir)
#     parquet_files = list(output_dir_path.glob("*.parquet"))
    
#     if parquet_files:
#         print(f"\nConcatenating {len(parquet_files)} files...")
#         combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
#         combined_output = output_dir_path / "resampled_daily_combined.parquet"
#         combined_df.write_parquet(combined_output)
#         print(f"Combined file saved to: {combined_output}")
#         print(f"Total rows: {combined_df.height}")
        
#         # Delete the separated files
#         print("\nDeleting separated files...")
#         for f in parquet_files:
#             f.unlink()
#         print(f"Deleted {len(parquet_files)} individual files")
#     else:
#         print("No parquet files found to concatenate")
    
    # Option 2: Save all RICs to a single file
    # output_file = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily_combined.parquet"
    # resample_tick_to_single_file(
    #     tick_data_path=tick_data_path,
    #     output_file=output_file,
    #     frequency="1d"
    # )
    
    # For hourly data, change frequency to "1h"
    # resample_tick_to_ohlc(
    #     tick_data_path=tick_data_path,
    #     output_dir="../../datastore/xtech-lseg/DATASCOPE/resampled_hourly",
    #     frequency="1h"
    # )

# # %%
# if __name__ == "__main__":
#     # Example usage
#     tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2024.parquet"
    
#     # Option 1: Save each RIC to separate file
#     output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2024"
#     resample_tick_to_ohlc(
#         tick_data_path=tick_data_path,
#         output_dir=output_dir,
#         frequency="1d"
#     )

#     # Then concatenate all separated files into a single file
#     output_dir_path = Path(output_dir)
#     parquet_files = list(output_dir_path.glob("*.parquet"))
    
#     if parquet_files:
#         print(f"\nConcatenating {len(parquet_files)} files...")
#         combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
#         combined_output = output_dir_path / "resampled_daily_combined.parquet"
#         combined_df.write_parquet(combined_output)
#         print(f"Combined file saved to: {combined_output}")
#         print(f"Total rows: {combined_df.height}")
        
#         # Delete the separated files
#         print("\nDeleting separated files...")
#         for f in parquet_files:
#             f.unlink()
#         print(f"Deleted {len(parquet_files)} individual files")
#     else:
#         print("No parquet files found to concatenate")

# %%
if __name__ == "__main__":
    # Example usage
    tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2023.parquet"
    
    # Option 1: Save each RIC to separate file
    output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2023"
    resample_tick_to_ohlc(
        tick_data_path=tick_data_path,
        output_dir=output_dir,
        frequency="1d"
    )

    # Then concatenate all separated files into a single file
    output_dir_path = Path(output_dir)
    parquet_files = list(output_dir_path.glob("*.parquet"))
    
    if parquet_files:
        print(f"\nConcatenating {len(parquet_files)} files...")
        combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
        combined_output = output_dir_path / "resampled_daily_combined.parquet"
        combined_df.write_parquet(combined_output)
        print(f"Combined file saved to: {combined_output}")
        print(f"Total rows: {combined_df.height}")
        
        # Delete the separated files
        print("\nDeleting separated files...")
        for f in parquet_files:
            f.unlink()
        print(f"Deleted {len(parquet_files)} individual files")
    else:
        print("No parquet files found to concatenate")
# %%
if __name__ == "__main__":
    # Example usage
    tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2022.parquet"
    
    # Option 1: Save each RIC to separate file
    output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2022"
    resample_tick_to_ohlc(
        tick_data_path=tick_data_path,
        output_dir=output_dir,
        frequency="1d"
    )

    # Then concatenate all separated files into a single file
    output_dir_path = Path(output_dir)
    parquet_files = list(output_dir_path.glob("*.parquet"))
    
    if parquet_files:
        print(f"\nConcatenating {len(parquet_files)} files...")
        combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
        combined_output = output_dir_path / "resampled_daily_combined.parquet"
        combined_df.write_parquet(combined_output)
        print(f"Combined file saved to: {combined_output}")
        print(f"Total rows: {combined_df.height}")
        
        # Delete the separated files
        print("\nDeleting separated files...")
        for f in parquet_files:
            f.unlink()
        print(f"Deleted {len(parquet_files)} individual files")
    else:
        print("No parquet files found to concatenate")

# %%
if __name__ == "__main__":
    # Example usage
    tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2021.parquet"
    
    # Option 1: Save each RIC to separate file
    output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2021"
    resample_tick_to_ohlc(
        tick_data_path=tick_data_path,
        output_dir=output_dir,
        frequency="1d"
    )

    # Then concatenate all separated files into a single file
    output_dir_path = Path(output_dir)
    parquet_files = list(output_dir_path.glob("*.parquet"))
    
    if parquet_files:
        print(f"\nConcatenating {len(parquet_files)} files...")
        combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
        combined_output = output_dir_path / "resampled_daily_combined.parquet"
        combined_df.write_parquet(combined_output)
        print(f"Combined file saved to: {combined_output}")
        print(f"Total rows: {combined_df.height}")
        
        # Delete the separated files
        print("\nDeleting separated files...")
        for f in parquet_files:
            f.unlink()
        print(f"Deleted {len(parquet_files)} individual files")
    else:
        print("No parquet files found to concatenate")

# %%
if __name__ == "__main__":
    # Example usage
    tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2020.parquet"
    
    # Option 1: Save each RIC to separate file
    output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2020"
    resample_tick_to_ohlc(
        tick_data_path=tick_data_path,
        output_dir=output_dir,
        frequency="1d"
    )

    # Then concatenate all separated files into a single file
    output_dir_path = Path(output_dir)
    parquet_files = list(output_dir_path.glob("*.parquet"))
    
    if parquet_files:
        print(f"\nConcatenating {len(parquet_files)} files...")
        combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
        combined_output = output_dir_path / "resampled_daily_combined.parquet"
        combined_df.write_parquet(combined_output)
        print(f"Combined file saved to: {combined_output}")
        print(f"Total rows: {combined_df.height}")
        
        # Delete the separated files
        print("\nDeleting separated files...")
        for f in parquet_files:
            f.unlink()
        print(f"Deleted {len(parquet_files)} individual files")
    else:
        print("No parquet files found to concatenate")

# %%
if __name__ == "__main__":
    # Example usage
    tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2019.parquet"
    
    # Option 1: Save each RIC to separate file
    output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2019"
    resample_tick_to_ohlc(
        tick_data_path=tick_data_path,
        output_dir=output_dir,
        frequency="1d"
    )

    # Then concatenate all separated files into a single file
    output_dir_path = Path(output_dir)
    parquet_files = list(output_dir_path.glob("*.parquet"))
    
    if parquet_files:
        print(f"\nConcatenating {len(parquet_files)} files...")
        combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
        combined_output = output_dir_path / "resampled_daily_combined.parquet"
        combined_df.write_parquet(combined_output)
        print(f"Combined file saved to: {combined_output}")
        print(f"Total rows: {combined_df.height}")
        
        # Delete the separated files
        print("\nDeleting separated files...")
        for f in parquet_files:
            f.unlink()
        print(f"Deleted {len(parquet_files)} individual files")
    else:
        print("No parquet files found to concatenate")

# %%
if __name__ == "__main__":
    # Example usage
    tick_data_path = "/Users/yuweiyan/Quant/Projects/CreditTrading/datastore/xtech-lseg/DATASCOPE/filtered_cbonds/Tick_History_Time_and_Sales_2018.parquet"
    
    # Option 1: Save each RIC to separate file
    output_dir = "../../datastore/xtech-lseg/DATASCOPE/resampled_daily/2018"
    resample_tick_to_ohlc(
        tick_data_path=tick_data_path,
        output_dir=output_dir,
        frequency="1d"
    )

    # Then concatenate all separated files into a single file
    output_dir_path = Path(output_dir)
    parquet_files = list(output_dir_path.glob("*.parquet"))
    
    if parquet_files:
        print(f"\nConcatenating {len(parquet_files)} files...")
        combined_df = pl.concat([pl.read_parquet(f) for f in parquet_files])
        
        combined_output = output_dir_path / "resampled_daily_combined.parquet"
        combined_df.write_parquet(combined_output)
        print(f"Combined file saved to: {combined_output}")
        print(f"Total rows: {combined_df.height}")
        
        # Delete the separated files
        print("\nDeleting separated files...")
        for f in parquet_files:
            f.unlink()
        print(f"Deleted {len(parquet_files)} individual files")
    else:
        print("No parquet files found to concatenate")

# %%
