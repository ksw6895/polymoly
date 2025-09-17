from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_order_books(path: Path) -> pd.DataFrame:
    """Load snapshot order book data exported as CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Order book file not found: {path}")

    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame.sort_values(["token_id", "timestamp", "side", "level"], inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame
