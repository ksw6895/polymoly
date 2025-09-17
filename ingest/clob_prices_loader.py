from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_prices_history(path: Path) -> pd.DataFrame:
    """Load `/prices-history` samples stored as CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Prices history file not found: {path}")

    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame.sort_values(["token_id", "timestamp"], inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame
