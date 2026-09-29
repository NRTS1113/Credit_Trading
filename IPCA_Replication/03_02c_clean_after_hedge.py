"""
Clean the hedged monthly panel after Treasury adjustment.

Inputs:
  - outputs/bond_panel_monthly_with_treasury.parquet

Outputs:
  - outputs/bond_panel_monthly_clean.parquet
"""

from pathlib import Path
import pandas as pd


def _winsorize(series: pd.Series, lower_q: float, upper_q: float) -> pd.Series:
    """Clip a series to quantile bounds."""
    lower = series.quantile(lower_q)
    upper = series.quantile(upper_q)
    return series.clip(lower=lower, upper=upper)


def main() -> None:
    # Resolve repo paths and output directory for reproducible runs
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    panel_path = out_dir / "bond_panel_monthly_with_treasury.parquet"
    if not panel_path.exists():
        raise FileNotFoundError(f"Missing file: {panel_path}")

    # Load hedged panel (fastparquet only)
    panel = pd.read_parquet(panel_path, engine="fastparquet")

    # Drop rows without the target return
    panel = panel.dropna(subset=["credit_excess_return"]).copy()

    # Winsorize credit excess returns to reduce outlier influence
    panel["credit_excess_return"] = _winsorize(panel["credit_excess_return"], 0.01, 0.99)

    output_path = out_dir / "bond_panel_monthly_clean.parquet"
    panel.to_parquet(output_path, index=False)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
