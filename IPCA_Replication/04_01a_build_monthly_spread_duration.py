"""
Build a monthly spread/duration panel from YieldBook.

Inputs:
  - src/data/yieldbook_price_yield.parquet

Outputs:
  - outputs/yieldbook_spread_duration_monthly.parquet
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

    yieldbook_path = data_dir / "yieldbook_price_yield.parquet"
    if not yieldbook_path.exists():
        raise FileNotFoundError(f"Missing file: {yieldbook_path}")

    # Load YieldBook data (fastparquet only)
    df = pd.read_parquet(yieldbook_path, engine="fastparquet")

    # Resolve column names
    ric_col = _pick_first_existing(df.columns, ["RIC", "ric"])
    date_col = _pick_first_existing(df.columns, ["PricingDate", "pricingDate", "Date", "date"])
    spread_col = _pick_first_existing(df.columns, ["OAS", "oas", "Spread", "spread"])
    duration_col = _pick_first_existing(df.columns, ["Duration", "duration", "EffectiveDuration", "effectiveDuration"])

    if not ric_col or not date_col:
        raise ValueError("YieldBook data must include RIC and PricingDate/Date.")
    if not spread_col or not duration_col:
        raise ValueError("YieldBook data must include OAS (spread) and Duration.")

    # Keep only the relevant fields
    df = df[[ric_col, date_col, spread_col, duration_col]].copy()
    df.rename(
        columns={
            ric_col: "RIC",
            date_col: "PricingDate",
            spread_col: "OAS",
            duration_col: "Duration",
        },
        inplace=True,
    )

    # Normalize dates and collapse to month-end
    df["PricingDate"] = pd.to_datetime(df["PricingDate"])
    df["month_end"] = _month_end(df["PricingDate"])

    # Use last available observation in each month per RIC
    df = df.sort_values(["RIC", "PricingDate"]).drop_duplicates(
        subset=["RIC", "month_end"], keep="last"
    )

    output_path = out_dir / "yieldbook_spread_duration_monthly.parquet"
    df.to_parquet(output_path, index=False)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
