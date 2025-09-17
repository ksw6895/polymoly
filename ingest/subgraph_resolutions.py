from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_resolutions(path: Path) -> pd.DataFrame:
    """Load resolution outcomes from a CSV export."""
    if not path.exists():
        raise FileNotFoundError(f"Resolutions file not found: {path}")

    frame = pd.read_csv(path)
    frame["resolve_ts"] = pd.to_datetime(frame["resolve_ts"], utc=True)
    frame.sort_values("resolve_ts", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame
