"""
Approximate credit excess returns by subtracting Treasury returns.

Inputs:
  - outputs/bond_panel_monthly.parquet
  - src/data/wrds_eod_us_treasury_monthly.parquet (optional)

Outputs:
  - outputs/treasury_monthly_return.parquet
  - outputs/bond_panel_monthly_with_treasury.parquet
"""

from pathlib import Path
import pandas as pd


def _pick_first_existing(columns, candidates):
    """Return the first candidate that exists in a column list."""
    for name in candidates:
        if name in columns:
            return name
    return None


def _compute_treasury_monthly_return(treasury_df: pd.DataFrame) -> pd.DataFrame:
    # Pick likely date/price/ID columns from WRDS treasury data
    date_col = _pick_first_existing(treasury_df.columns, ["TDATDT", "date", "Date"])
    price_col = _pick_first_existing(treasury_df.columns, ["TMNOMPRC", "price", "PRICE", "Close", "close"])
    id_col = _pick_first_existing(treasury_df.columns, ["TCUSIP", "CUSIP", "KYTREASNO"])

    if not date_col or not price_col:
        raise ValueError("Treasury file missing required date/price columns.")

    # Keep only needed columns and normalize date dtype
    df = treasury_df[[date_col, price_col] + ([id_col] if id_col else [])].copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values([id_col, date_col]) if id_col else df.sort_values([date_col])

    # Compute within-security price returns where possible
    if id_col:
        df["treasury_ret"] = df.groupby(id_col)[price_col].pct_change()
    else:
        df["treasury_ret"] = df[price_col].pct_change()

    # Collapse to month-end and average across treasuries
    df["month_end"] = df[date_col].dt.to_period("M").dt.to_timestamp("M")
    monthly = df.groupby("month_end", as_index=False)["treasury_ret"].mean()
    return monthly


def main() -> None:
    # Resolve repo paths and output directory for reproducible runs
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "src" / "data"
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    panel_path = out_dir / "bond_panel_monthly.parquet"
    if not panel_path.exists():
        raise FileNotFoundError(f"Missing file: {panel_path}")

    # Load monthly bond panel (fastparquet only)
    panel = pd.read_parquet(panel_path, engine="fastparquet")
    if "month_end" not in panel.columns or "price_return" not in panel.columns:
        raise ValueError("Panel must include 'month_end' and 'price_return'.")

    treasury_path = data_dir / "wrds_eod_us_treasury_monthly.parquet"
    if treasury_path.exists():
        # Compute monthly Treasury returns for hedging
        treasury_df = pd.read_parquet(treasury_path, engine="fastparquet")
        treasury_monthly = _compute_treasury_monthly_return(treasury_df)
        treasury_out = out_dir / "treasury_monthly_return.parquet"
        treasury_monthly.to_parquet(treasury_out, index=False)
        # Merge hedge returns and compute credit excess returns
        panel = panel.merge(treasury_monthly, on="month_end", how="left")
        panel["credit_excess_return"] = panel["price_return"] - panel["treasury_ret"]
        print(f"Saved: {treasury_out}")
    else:
        # If Treasury data is missing, leave hedge fields as NA
        panel["treasury_ret"] = pd.NA
        panel["credit_excess_return"] = pd.NA
        print(f"Missing Treasury file: {treasury_path}")
        print("Proceeding without hedge (credit_excess_return left as NA).")

    # Save panel with hedge information
    output_path = out_dir / "bond_panel_monthly_with_treasury.parquet"
    panel.to_parquet(output_path, index=False)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
