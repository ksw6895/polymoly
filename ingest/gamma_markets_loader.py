from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


def load_gamma_markets(path: Path) -> pd.DataFrame:
    """Load Gamma market metadata from a JSON file.

    The sample file mirrors the shape of
    ``GET https://gamma-api.polymarket.com/markets``.
    """
    if not path.exists():
        raise FileNotFoundError(f"Gamma markets file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    records = []
    for entry in payload:
        records.append(
            {
                "condition_id": entry["condition_id"],
                "slug": entry.get("slug"),
                "category": entry.get("category"),
                "end_date": pd.to_datetime(entry.get("end_date")),
                "clob_token_yes": entry.get("clob_token_yes"),
                "clob_token_no": entry.get("clob_token_no"),
                "neg_risk_group": entry.get("neg_risk_group"),
            }
        )

    frame = pd.DataFrame.from_records(records)
    frame.sort_values("end_date", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def subset_by_condition_ids(
    markets: pd.DataFrame, condition_ids: Optional[Iterable[str]] = None
) -> pd.DataFrame:
    """Return a filtered markets DataFrame.

    Parameters
    ----------
    markets:
        The markets DataFrame returned by :func:`load_gamma_markets`.
    condition_ids:
        Optional iterable of condition identifiers to keep.  If omitted the
        DataFrame is returned unchanged.
    """
    if condition_ids is None:
        return markets.copy()

    condition_ids = set(condition_ids)
    mask = markets["condition_id"].isin(condition_ids)
    return markets.loc[mask].reset_index(drop=True)
