"""
Merge monthly spread/duration into the cleaned hedged panel.

Inputs:
  - outputs/bond_panel_monthly_clean.parquet
  - outputs/yieldbook_spread_duration_monthly.parquet

Outputs:
  - outputs/bond_panel_monthly_clean_with_spread_duration.parquet
"""

from pathlib import Path
import pandas as pd


def main() -> None:
    # Resolve repo paths and output directory for reproducible runs
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_path = out_dir / "bond_panel_monthly_clean.parquet"
    spread_path = out_dir / "yieldbook_spread_duration_monthly.parquet"

    if not clean_path.exists():
        raise FileNotFoundError(f"Missing file: {clean_path}")
    if not spread_path.exists():
        raise FileNotFoundError(f"Missing file: {spread_path}")

    # Load inputs (fastparquet only)
    panel = pd.read_parquet(clean_path, engine="fastparquet")
    spread = pd.read_parquet(spread_path, engine="fastparquet")

    # Merge on RIC + month_end
    merged = panel.merge(
        spread[["RIC", "month_end", "OAS", "Duration"]],
        on=["RIC", "month_end"],
        how="left",
    )

    output_path = out_dir / "bond_panel_monthly_clean_with_spread_duration.parquet"
    merged.to_parquet(output_path, index=False)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
