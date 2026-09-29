"""
Clean merged panel by requiring spread and duration availability.

Inputs:
  - outputs/bond_panel_monthly_clean_with_spread_duration.parquet

Outputs:
  - outputs/bond_panel_monthly_clean_with_spread_duration_filtered.parquet
"""

from pathlib import Path
import pandas as pd


def main() -> None:
    # Resolve repo paths and output directory for reproducible runs
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    merged_path = out_dir / "bond_panel_monthly_clean_with_spread_duration.parquet"
    if not merged_path.exists():
        raise FileNotFoundError(f"Missing file: {merged_path}")

    # Load merged panel (fastparquet only)
    panel = pd.read_parquet(merged_path, engine="fastparquet")

    # Drop RICs that are 100% missing OAS/Duration
    missing_rate = (
        panel.assign(missing_oas=panel["OAS"].isna(), missing_dur=panel["Duration"].isna())
        .groupby("RIC")[["missing_oas", "missing_dur"]]
        .mean()
    )
    fully_missing_ric = missing_rate.index[missing_rate.max(axis=1) == 1]
    panel = panel[~panel["RIC"].isin(fully_missing_ric)].copy()

    # Fill within each RIC (time order) for partial gaps
    panel = panel.sort_values(["RIC", "month_end"])
    panel[["OAS", "Duration"]] = (
        panel.groupby("RIC")[["OAS", "Duration"]].transform(lambda s: s.ffill().bfill())
    )
    panel[["price", "yield"]] = (
        panel.groupby("RIC")[["price", "yield"]].transform(lambda s: s.ffill().bfill())
    )

    # Drop any remaining missing fields we rely on
    panel = panel.dropna(subset=["OAS", "Duration", "price", "yield"]).copy()

    output_path = out_dir / "bond_panel_monthly_clean_with_spread_duration_filtered.parquet"
    panel.to_parquet(output_path, index=False)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
