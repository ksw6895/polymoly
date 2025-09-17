from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class LabelConfig:
    """Configuration controlling label generation."""

    time_cut_hours: float = 4.0


def apply_time_cut(
    trades: pd.DataFrame, resolutions: pd.DataFrame, config: Optional[LabelConfig] = None
) -> pd.DataFrame:
    """Drop trades that violate the look-ahead cut."""
    if config is None:
        config = LabelConfig()

    merged = trades.merge(
        resolutions[["condition_id", "resolve_ts"]], on="condition_id", how="left"
    )

    if merged["resolve_ts"].isnull().any():
        missing = merged.loc[merged["resolve_ts"].isnull(), "condition_id"].unique()
        raise ValueError(f"Missing resolution timestamp for: {missing}")

    cutoff = merged["resolve_ts"] - pd.to_timedelta(config.time_cut_hours, unit="h")
    mask = merged["timestamp"] <= cutoff
    return merged.loc[mask, trades.columns]


def attach_labels(
    trades: pd.DataFrame, resolutions: pd.DataFrame, config: Optional[LabelConfig] = None
) -> pd.DataFrame:
    """Append binary resolution outcomes to each trade."""
    if config is None:
        config = LabelConfig()

    filtered = apply_time_cut(trades, resolutions, config)

    labeled = filtered.merge(
        resolutions[["condition_id", "resolved_outcome", "resolve_ts", "dispute_flag"]],
        on="condition_id",
        how="left",
    )

    labeled["outcome"] = labeled["resolved_outcome"].str.lower().map({"yes": 1, "no": 0})
    if labeled["outcome"].isnull().any():
        raise ValueError("Unknown resolved outcome encountered")

    labeled.sort_values("timestamp", inplace=True)
    labeled.reset_index(drop=True, inplace=True)
    return labeled
