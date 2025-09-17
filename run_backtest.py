from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple

import pandas as pd

from backtest.cost_model import CostModel
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.risk import RiskManager
from feature.make_features import compute_features
from feature.make_labels import attach_labels
from ingest.clob_books_loader import load_order_books
from ingest.clob_prices_loader import load_prices_history
from ingest.dataapi_trades_loader import load_trades
from ingest.gamma_markets_loader import load_gamma_markets
from ingest.subgraph_resolutions import load_resolutions
from model.calibrate_isotonic import IsotonicCalibrator
from report.metrics import brier_score, compute_calibration, compute_monthly_breakdown, compute_summary


def _build_book_lookup(books: pd.DataFrame) -> Dict[Tuple[str, pd.Timestamp], pd.DataFrame]:
    lookup: Dict[Tuple[str, pd.Timestamp], pd.DataFrame] = {}
    for (token, ts), group in books.groupby(["token_id", "timestamp"]):
        lookup[(token, ts)] = group.copy()
    return lookup


def run_backtest(data_dir: Path | None = None) -> Dict[str, object]:
    base = Path(__file__).resolve().parent
    data_dir = data_dir or base / "data"

    markets = load_gamma_markets(data_dir / "gamma_markets_sample.json")
    resolutions = load_resolutions(data_dir / "subgraph_resolutions.csv")
    trades = load_trades(data_dir / "dataapi_trades.csv")
    books = load_order_books(data_dir / "clob_books.csv")
    prices = load_prices_history(data_dir / "prices_history.csv")

    labeled_trades = attach_labels(trades, resolutions)
    features = compute_features(labeled_trades, markets, books, prices)

    book_lookup = _build_book_lookup(books)

    def calibrator_factory() -> IsotonicCalibrator:
        return IsotonicCalibrator()

    cost_model = CostModel(taker_fee=0.0, gas_cost=0.25, borrow_rate=0.05)
    risk_manager = RiskManager()
    config = BacktestConfig(initial_capital=100_000.0, min_ev=0.0)

    splits: Iterable[Tuple[pd.Timestamp, pd.Timestamp]] = [
        (
            pd.Timestamp("2024-01-01T00:00:00Z"),
            pd.Timestamp("2024-12-31T23:59:59Z"),
        ),
        (
            pd.Timestamp("2024-12-31T23:59:59Z"),
            pd.Timestamp("2025-12-31T23:59:59Z"),
        ),
    ]

    engine = BacktestEngine(calibrator_factory, cost_model, risk_manager, config, book_lookup)
    backtest_result = engine.run(features, splits)

    executed_trades = backtest_result["executed_trades"]
    summary = compute_summary(executed_trades, config.initial_capital)
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


if __name__ == "__main__":
    output = run_backtest()
    print("=== Backtest Summary ===")
    for key, value in output["summary"].items():
        print(f"{key}: {value}")
    print(f"Brier score: {output['brier_score']}")
