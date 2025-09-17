from __future__ import annotations

from typing import List

import pandas as pd

TAU_BINS = [0, 1, 3, 7, 30, 10_000]
TAU_LABELS = ["0-1d", "1-3d", "3-7d", "7-30d", ">30d"]


def assign_tau_bucket(tau_days: pd.Series) -> pd.Series:
    return pd.cut(tau_days, bins=TAU_BINS, labels=TAU_LABELS, right=True, include_lowest=True)


def _prepare_order_book_features(books: pd.DataFrame) -> pd.DataFrame:
    """Aggregate best bid/ask and depth information."""
    ask_level1 = (
        books.query("side == 'ask' and level == 1")
        .rename(columns={"price": "best_ask", "size": "best_ask_size"})
        [["token_id", "timestamp", "best_ask", "best_ask_size"]]
    )
    bid_level1 = (
        books.query("side == 'bid' and level == 1")
        .rename(columns={"price": "best_bid", "size": "best_bid_size"})
        [["token_id", "timestamp", "best_bid", "best_bid_size"]]
    )
    depth = (
        books.groupby(["token_id", "timestamp", "side"], as_index=False)["size"].sum()
        .pivot(index=["token_id", "timestamp"], columns="side", values="size")
        .rename(columns={"ask": "ask_depth", "bid": "bid_depth"})
        .reset_index()
    )

    order_features = ask_level1.merge(bid_level1, on=["token_id", "timestamp"], how="inner")
    order_features = order_features.merge(depth, on=["token_id", "timestamp"], how="left")
    return order_features


def compute_features(
    trades: pd.DataFrame,
    markets: pd.DataFrame,
    books: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """Create model and backtest features."""
    markets_subset = markets[[
        "condition_id",
        "slug",
        "category",
        "end_date",
        "clob_token_yes",
        "neg_risk_group",
    ]]
    enriched = trades.merge(
        markets_subset,
        left_on="condition_id",
        right_on="condition_id",
        how="left",
        validate="many_to_one",
    )
    if enriched["end_date"].isnull().any():
        missing = enriched.loc[enriched["end_date"].isnull(), "condition_id"].unique()
        raise ValueError(f"Missing market metadata for: {missing}")

    enriched["time_to_event_days"] = (
        (enriched["end_date"].dt.tz_convert("UTC") - enriched["timestamp"])
        .dt.total_seconds()
        / (3600 * 24)
    )
    enriched = enriched.loc[enriched["time_to_event_days"] > 0].copy()
    enriched["tau_bucket"] = assign_tau_bucket(enriched["time_to_event_days"])

    order_features = _prepare_order_book_features(books)
    enriched = enriched.merge(
        order_features,
        on=["token_id", "timestamp"],
        how="left",
    )

    if enriched[["best_ask", "best_bid"]].isnull().any().any():
        raise ValueError("Missing order book snapshots for some trades")

    enriched["spread"] = enriched["best_ask"] - enriched["best_bid"]
    enriched["midpoint"] = (enriched["best_ask"] + enriched["best_bid"]) / 2
    enriched["relative_spread"] = enriched["spread"] / enriched["midpoint"]
    enriched["price_vs_mid"] = enriched["price"] - enriched["midpoint"]

    # Merge price history for simple momentum style features.
    prices_sorted = prices.sort_values(["token_id", "timestamp"])
    enriched = enriched.sort_values(["token_id", "timestamp"]).reset_index(drop=True)
    previous_prices = pd.merge_asof(
        enriched,
        prices_sorted,
        on="timestamp",
        by="token_id",
        direction="backward",
        allow_exact_matches=False,
    )
    enriched["prev_price"] = previous_prices["price_y"]
    enriched["prev_price"] = enriched["prev_price"].fillna(enriched["midpoint"] - 0.01)
    enriched["price_change"] = enriched["price"] - enriched["prev_price"]

    enriched["year"] = enriched["timestamp"].dt.year
    enriched["month"] = enriched["timestamp"].dt.month

    columns: List[str] = [
        "trade_id",
        "token_id",
        "condition_id",
        "timestamp",
        "price",
        "size",
        "outcome",
        "time_to_event_days",
        "tau_bucket",
        "best_ask",
        "best_bid",
        "spread",
        "relative_spread",
        "ask_depth",
        "bid_depth",
        "price_vs_mid",
        "price_change",
        "category",
        "neg_risk_group",
        "slug",
        "resolve_ts",
    ]

    return enriched[columns].sort_values("timestamp").reset_index(drop=True)
