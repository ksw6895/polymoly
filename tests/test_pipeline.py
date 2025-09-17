from __future__ import annotations

import pandas as pd

from run_backtest import (
    PipelineConfig,
    _coerce_timestamp,
    _synthesise_books,
    run_backtest,
)


def test_run_backtest_pipeline():
    result = run_backtest(PipelineConfig(source="local"))
    summary = result["summary"]
    assert summary["trades"] > 0
    assert summary["ending_capital"] > 0
    assert isinstance(result["monthly"], pd.DataFrame)
    assert isinstance(result["calibration"], pd.DataFrame)


def test_coerce_timestamp_returns_utc():
    ts = _coerce_timestamp("2024-01-01T00:00:00Z")
    assert isinstance(ts, pd.Timestamp)
    assert ts.tzinfo is not None
    assert ts.tz_convert("UTC") == ts


def test_synthesise_books_creates_bid_ask():
    trades = pd.DataFrame(
        {
            "token_id": ["token-a"],
            "timestamp": [pd.Timestamp("2024-01-01T00:00:00Z")],
            "price": [0.95],
            "size": [100.0],
        }
    )
    books = _synthesise_books(trades, levels=2)
    assert not books.empty
    assert {"ask", "bid"}.issubset(set(books["side"].unique()))
    assert books["level"].max() == 2
