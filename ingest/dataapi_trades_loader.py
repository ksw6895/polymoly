from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_trades(path: Path) -> pd.DataFrame:
    """Load trade history exported from the Data API."""
    if not path.exists():
        raise FileNotFoundError(f"Trades file not found: {path}")

    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame.sort_values("timestamp", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame
