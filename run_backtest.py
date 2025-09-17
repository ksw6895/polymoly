from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Literal, Optional, Sequence, Tuple

import pandas as pd

from backtest.cost_model import CostModel
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.risk import RiskManager
from feature.make_features import compute_features
from feature.make_labels import attach_labels
from ingest.data_bundle import (
    BacktestDataBundle,
    download_bundle_from_api,
    load_local_bundle,
)
from ingest.polymarket_api import BackfillWindow, PolymarketAPISettings
from model.calibrate_isotonic import IsotonicCalibrator
from report.metrics import (
    brier_score,
    compute_calibration,
    compute_monthly_breakdown,
    compute_summary,
)


@dataclass
class PipelineConfig:
    """High-level configuration for the backtest run."""

    source: Literal["local", "api", "auto"] = "local"
    data_dir: Optional[Path] = None
    start: Optional[pd.Timestamp] = None
    end: Optional[pd.Timestamp] = None
    condition_ids: Optional[Sequence[str]] = None
    goldsky_url: Optional[str] = None
    order_book_depth: int = 5
    initial_capital: float = 100_000.0
    min_ev: float = 0.0

    def window(self) -> Optional[BackfillWindow]:
        if self.start is None and self.end is None:
            return None
        return BackfillWindow(start=self.start, end=self.end)


def _build_book_lookup(
    books: pd.DataFrame,
) -> Dict[Tuple[str, pd.Timestamp], pd.DataFrame]:
    lookup: Dict[Tuple[str, pd.Timestamp], pd.DataFrame] = {}
    for (token, ts), group in books.groupby(["token_id", "timestamp"]):
        lookup[(token, ts)] = group.copy()
    return lookup


def _synthesise_books(trades: pd.DataFrame, *, levels: int = 3) -> pd.DataFrame:
    """Generate a conservative synthetic book when snapshots are unavailable."""

    records = []
    for _, row in trades.iterrows():
        price = float(row["price"])
        size = float(row.get("size", 0.0) or 1.0)
        token_id = row["token_id"]
        timestamp = row["timestamp"]
        tick = max(0.002, price * 0.01)
        for level in range(1, levels + 1):
            offset = tick * level
            depth = max(size * (1.0 - 0.25 * (level - 1)), size * 0.25)
            records.append(
                {
                    "token_id": token_id,
                    "timestamp": timestamp,
                    "side": "ask",
                    "level": level,
                    "price": min(0.999, price + offset),
                    "size": depth,
                }
            )
            records.append(
                {
                    "token_id": token_id,
                    "timestamp": timestamp,
                    "side": "bid",
                    "level": level,
                    "price": max(0.001, price - offset),
                    "size": depth,
                }
            )
    frame = pd.DataFrame.from_records(records)
    frame.sort_values(["token_id", "timestamp", "side", "level"], inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def _ensure_books(bundle: BacktestDataBundle) -> pd.DataFrame:
    if bundle.books is not None and not bundle.books.empty:
        return bundle.books
    return _synthesise_books(bundle.trades)


def _ensure_prices(bundle: BacktestDataBundle) -> pd.DataFrame:
    if bundle.prices is not None and not bundle.prices.empty:
        return bundle.prices
    return bundle.trades[["token_id", "timestamp", "price"]].copy()


def _coerce_timestamp(value: Optional[str]) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _resolve_source(config: PipelineConfig, default_dir: Path) -> str:
    if config.source != "auto":
        return config.source
    data_dir = config.data_dir or default_dir
    sample_file = data_dir / "gamma_markets_sample.json"
    return "local" if sample_file.exists() else "api"


def run_backtest(config: Optional[PipelineConfig] = None) -> Dict[str, object]:
    base = Path(__file__).resolve().parent
    data_dir = base / "data"
    config = config or PipelineConfig(source="local", data_dir=data_dir)
    source = _resolve_source(config, data_dir)

    if source == "local":
        bundle = load_local_bundle(config.data_dir or data_dir)
    else:
        settings = PolymarketAPISettings(
            goldsky_url=config.goldsky_url or os.getenv("POLYMOLY_GOLDSKY_URL"),
        )
        bundle = download_bundle_from_api(
            settings=settings,
            condition_filter=config.condition_ids,
            window=config.window(),
            depth=config.order_book_depth,
        )

    books = _ensure_books(bundle)
    prices = _ensure_prices(bundle)

    labeled_trades = attach_labels(bundle.trades, bundle.resolutions)
    features = compute_features(labeled_trades, bundle.markets, books, prices)

    book_lookup = _build_book_lookup(books)

    def calibrator_factory() -> IsotonicCalibrator:
        return IsotonicCalibrator()

    cost_model = CostModel(taker_fee=0.0, gas_cost=0.25, borrow_rate=0.05)
    risk_manager = RiskManager()
    config_bt = BacktestConfig(
        initial_capital=config.initial_capital, min_ev=config.min_ev
    )

    if features.empty:
        raise RuntimeError("No features computed; verify ingestion configuration")

    timeline = features["timestamp"].sort_values().unique()
    if len(timeline) < 2:
        raise RuntimeError("Not enough data points to create walk-forward splits")
    start_ts = timeline.min()
    end_ts = timeline.max()
    midpoint = start_ts + (end_ts - start_ts) / 2
    splits: Iterable[Tuple[pd.Timestamp, pd.Timestamp]] = [
        (
            pd.Timestamp(midpoint).tz_convert("UTC"),
            pd.Timestamp(end_ts).tz_convert("UTC"),
        ),
    ]

    engine = BacktestEngine(
        calibrator_factory,
        cost_model,
        risk_manager,
        config_bt,
        book_lookup,
    )
    backtest_result = engine.run(features, splits)

    executed_trades = backtest_result["executed_trades"]
    summary = compute_summary(executed_trades, config_bt.initial_capital)
    monthly = compute_monthly_breakdown(executed_trades)
    calibration = compute_calibration(executed_trades)
    brier = brier_score(executed_trades)

    result = {
        "summary": summary,
        "monthly": monthly,
        "calibration": calibration,
        "brier_score": brier,
        "backtest": backtest_result,
    }

    return result


def _parse_args() -> PipelineConfig:
    parser = argparse.ArgumentParser(description="Run the Polymoly backtest")
    parser.add_argument(
        "--source",
        choices=["local", "api", "auto"],
        default="auto",
        help="Data source: use local fixtures, live APIs, or auto-detect",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory containing local data fixtures",
    )
    parser.add_argument(
        "--start",
        help="UTC start timestamp (e.g. 2024-01-01T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        help="UTC end timestamp (e.g. 2024-06-30T23:59:59Z)",
    )
    parser.add_argument(
        "--condition",
        action="append",
        dest="condition_ids",
        help="Optional condition_id filters (repeat flag to add more)",
    )
    parser.add_argument(
        "--goldsky-url",
        help="Override Goldsky GraphQL endpoint for resolution data",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=5,
        help="Order-book depth to request from the API",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100_000.0,
        help="Initial capital for the backtest",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.0,
        help="Minimum EV lower-bound threshold required to trade",
    )
    args = parser.parse_args()

    return PipelineConfig(
        source=args.source,
        data_dir=args.data_dir,
        start=_coerce_timestamp(args.start),
        end=_coerce_timestamp(args.end),
        condition_ids=args.condition_ids,
        goldsky_url=args.goldsky_url,
        order_book_depth=args.depth,
        initial_capital=args.initial_capital,
        min_ev=args.min_ev,
    )


if __name__ == "__main__":
    config = _parse_args()
    output = run_backtest(config)
    print("=== Backtest Summary ===")
    for key, value in output["summary"].items():
        print(f"{key}: {value}")
    print(f"Brier score: {output['brier_score']}")
