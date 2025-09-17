from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from ingest.polymarket_api import (
    BackfillWindow,
    PolymarketAPIClient,
    PolymarketAPISettings,
)
from ingest.clob_books_loader import load_order_books
from ingest.clob_prices_loader import load_prices_history
from ingest.dataapi_trades_loader import load_trades
from ingest.gamma_markets_loader import load_gamma_markets
from ingest.subgraph_resolutions import load_resolutions


@dataclass
class BacktestDataBundle:
    """Container holding all inputs required by the backtest."""

    markets: pd.DataFrame
    resolutions: pd.DataFrame
    trades: pd.DataFrame
    books: pd.DataFrame
    prices: pd.DataFrame


def load_local_bundle(data_dir: Path) -> BacktestDataBundle:
    """Load the synthetic CSV/JSON fixtures from ``data/``.

    Parameters
    ----------
    data_dir:
        Directory containing the canonical fixtures.
    """

    markets = load_gamma_markets(data_dir / "gamma_markets_sample.json")
    resolutions = load_resolutions(data_dir / "subgraph_resolutions.csv")
    trades = load_trades(data_dir / "dataapi_trades.csv")
    books = load_order_books(data_dir / "clob_books.csv")
    prices = load_prices_history(data_dir / "prices_history.csv")
    return BacktestDataBundle(markets, resolutions, trades, books, prices)


def _fallback_resolutions_from_markets(markets: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in markets.iterrows():
        outcome = row.get("resolved_outcome")
        resolve_ts = row.get("end_date")
        if outcome is None:
            continue
        records.append(
            {
                "condition_id": row["condition_id"],
                "resolved_outcome": outcome,
                "resolve_ts": resolve_ts,
                "dispute_flag": False,
            }
        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame
    frame["resolve_ts"] = pd.to_datetime(frame["resolve_ts"], utc=True)
    frame.sort_values("resolve_ts", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def download_bundle_from_api(
    *,
    settings: Optional[PolymarketAPISettings] = None,
    condition_filter: Optional[Iterable[str]] = None,
    window: Optional[BackfillWindow] = None,
    depth: int = 5,
) -> BacktestDataBundle:
    """Download a complete dataset from the public APIs.

    Notes
    -----
    The public surfaces do not currently expose historical order-book snapshots.
    To approximate execution costs, the implementation collects the live book for
    each token and reuses it for all historical trades of that token.  For
    production-grade backtests users should archive book states alongside trades
    and replace this approximation with actual snapshots.
    """

    client = PolymarketAPIClient(settings)
    markets = client.fetch_gamma_markets()
    if condition_filter:
        condition_filter = set(condition_filter)
        markets = markets.loc[markets["condition_id"].isin(condition_filter)]
    if window and window.end is not None:
        markets = markets.loc[markets["end_date"] <= window.end]
    markets = markets.dropna(subset=["condition_id"]).reset_index(drop=True)

    token_map: Dict[str, str] = {}
    for _, row in markets.iterrows():
        yes_token = row.get("clob_token_yes")
        if yes_token:
            token_map[yes_token] = row["condition_id"]

    trades_frames = []
    for token_id, condition_id in token_map.items():
        trades = client.fetch_trades(token_id, window=window)
        if trades.empty:
            continue
        if "condition_id" not in trades or trades["condition_id"].isnull().all():
            trades["condition_id"] = condition_id
        else:
            trades["condition_id"].fillna(condition_id, inplace=True)
        trades_frames.append(trades)

    if trades_frames:
        trades = pd.concat(trades_frames, ignore_index=True)
    else:
        trades = pd.DataFrame()
    if trades.empty:
        raise RuntimeError("No trades were downloaded for the requested window")

    if "trade_id" not in trades.columns:
        trades["trade_id"] = pd.NA
    if trades["trade_id"].isnull().any():
        trades["trade_id"] = trades.apply(
            lambda row: f"{row['token_id']}_{int(row['timestamp'].timestamp())}",
            axis=1,
        )
    trades.sort_values("timestamp", inplace=True)
    trades.reset_index(drop=True, inplace=True)

    price_frames = []
    for token_id in sorted(trades["token_id"].unique()):
        history = client.fetch_prices_history(token_id, window=window)
        if history.empty:
            continue
        price_frames.append(history)
    if price_frames:
        prices = pd.concat(price_frames, ignore_index=True)
    else:
        prices = pd.DataFrame()

    books_frames = []
    for token_id, token_trades in trades.groupby("token_id"):
        snapshot = client.fetch_order_book(token_id, depth=depth)
        if snapshot.empty:
            continue
        expanded = pd.concat(
            [
                snapshot.assign(timestamp=ts)
                for ts in token_trades["timestamp"].tolist()
            ],
            ignore_index=True,
        )
        books_frames.append(expanded)
    if books_frames:
        books = pd.concat(books_frames, ignore_index=True)
    else:
        books = pd.DataFrame()

    if client.settings.goldsky_url:
        resolutions = client.fetch_resolutions(markets["condition_id"].unique())
    else:
        resolutions = _fallback_resolutions_from_markets(markets)

    if resolutions.empty:
        raise RuntimeError("Failed to download resolution data; configure Goldsky URL")

    return BacktestDataBundle(markets, resolutions, trades, books, prices)
