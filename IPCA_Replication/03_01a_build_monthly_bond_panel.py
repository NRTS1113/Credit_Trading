"""
Build a monthly bond panel from Datascope EOD data.

Inputs (expected under src/data):
  - datascope_price_eod.parquet
  - datascope_yield_eod.parquet

Outputs (written under notebooks/IPCA_paper_replication/outputs):
  - bond_panel_monthly.parquet
"""

from pathlib import Path
import pandas as pd


def _pick_first_existing(columns, candidates):
    """Return the first candidate that exists in a column list."""
    for name in candidates:
        if name in columns:
            return name
    return None


def _month_end(dt_series: pd.Series) -> pd.Series:
    """Convert a datetime series to month-end timestamps."""
    return dt_series.dt.to_period("M").dt.to_timestamp("M")


def main() -> None:
    # Resolve repo paths and output directory for reproducible runs
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "src" / "data"
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    price_path = data_dir / "datascope_price_eod.parquet"
    yield_path = data_dir / "datascope_yield_eod.parquet"

    if not price_path.exists():
        raise FileNotFoundError(f"Missing file: {price_path}")
    if not yield_path.exists():
        raise FileNotFoundError(f"Missing file: {yield_path}")

    # Load raw daily EOD price/yield data (fastparquet only)
    price_df = pd.read_parquet(price_path, engine="fastparquet")
    yield_df = pd.read_parquet(yield_path, engine="fastparquet")

    if "Trade Date" not in price_df.columns or "RIC" not in price_df.columns:
        raise ValueError("Price data must include 'RIC' and 'Trade Date'.")
    if "Trade Date" not in yield_df.columns or "RIC" not in yield_df.columns:
        raise ValueError("Yield data must include 'RIC' and 'Trade Date'.")

    # Normalize date types before resampling
    price_df["Trade Date"] = pd.to_datetime(price_df["Trade Date"])
    yield_df["Trade Date"] = pd.to_datetime(yield_df["Trade Date"])

    # Select a reasonable proxy for "price" if multiple columns exist
    price_col = _pick_first_existing(
        price_df.columns,
        [
            "Universal Close Price",
            "Average of Bid and Ask",
            "Ask",
            "Bid",
        ],
    )
    if not price_col:
        raise ValueError("No usable price column found in datascope_price_eod.parquet.")

    # Select a reasonable proxy for "yield" if multiple columns exist
    yield_col = _pick_first_existing(
        yield_df.columns,
        [
            "Close Yield",
            "Bid Yield",
            "Ask Yield",
            "Open Yield",
            "High Yield",
            "Low Yield",
        ],
    )
    if not yield_col:
        raise ValueError("No usable yield column found in datascope_yield_eod.parquet.")

    # Keep only the identifiers and the chosen numeric series
    price_df = price_df[["RIC", "Trade Date", price_col]].rename(columns={price_col: "price"})
    yield_df = yield_df[["RIC", "Trade Date", yield_col]].rename(columns={yield_col: "yield"})

    # Collapse to month-end timestamps for each RIC
    price_df["month_end"] = _month_end(price_df["Trade Date"])
    yield_df["month_end"] = _month_end(yield_df["Trade Date"])

    # Use last available trading day per month
    price_df = price_df.sort_values(["RIC", "Trade Date"]).drop_duplicates(
        subset=["RIC", "month_end"], keep="last"
    )
    yield_df = yield_df.sort_values(["RIC", "Trade Date"]).drop_duplicates(
        subset=["RIC", "month_end"], keep="last"
    )

    # Merge price and yield on the monthly panel key
    panel = price_df.merge(
        yield_df[["RIC", "month_end", "yield"]],
        on=["RIC", "month_end"],
        how="left",
    )

    # Compute simple price returns (monthly percent change)
    panel = panel.sort_values(["RIC", "month_end"])
    panel["price_return"] = panel.groupby("RIC")["price"].pct_change()

    output_path = out_dir / "bond_panel_monthly.parquet"
    panel.to_parquet(output_path, index=False)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
