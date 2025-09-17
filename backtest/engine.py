from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import pandas as pd

from backtest.cost_model import CostModel
from backtest.risk import RiskManager
from model.calibrate_isotonic import IsotonicCalibrator


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    min_ev: float = 0.0


@dataclass
class TradeResult:
    trade_id: str
    condition_id: str
    timestamp: pd.Timestamp
    resolve_ts: pd.Timestamp
    category: str
    neg_risk_group: str
    price: float
    execution_price: float
    shares: float
    notional: float
    q_hat: float
    q_lower: float
    ev_lower: float
    total_cost: float
    payout: float
    pnl: float


class BacktestEngine:
    def __init__(
        self,
        calibrator_factory,
        cost_model: CostModel,
        risk_manager: RiskManager,
        config: BacktestConfig,
        book_lookup: Dict[Tuple[str, pd.Timestamp], pd.DataFrame],
    ) -> None:
        self.calibrator_factory = calibrator_factory
        self.cost_model = cost_model
        self.risk_manager = risk_manager
        self.config = config
        self.book_lookup = book_lookup

    def _settle_positions(
        self,
        current_time: pd.Timestamp,
        open_positions: List[Dict],
        capital: float,
        executed_trades: List[TradeResult],
        capital_history: List[Tuple[pd.Timestamp, float]],
    ) -> Tuple[List[Dict], float]:
        remaining = []
        for position in open_positions:
            if position["resolve_ts"] <= current_time:
                payout = position["outcome"] * position["shares"]
                capital += payout
                pnl = payout - position["notional"] - position["breakdown"].total_cost
                trade_result = TradeResult(
                    trade_id=position["trade_id"],
                    condition_id=position["condition_id"],
                    timestamp=position["timestamp"],
                    resolve_ts=position["resolve_ts"],
                    category=position["category"],
                    neg_risk_group=position["neg_risk_group"],
                    price=position["price"],
                    execution_price=position["breakdown"].execution_price,
                    shares=position["shares"],
                    notional=position["notional"],
                    q_hat=position["q_hat"],
                    q_lower=position["q_lower"],
                    ev_lower=position["ev_lower"],
                    total_cost=position["breakdown"].total_cost,
                    payout=payout,
                    pnl=pnl,
                )
                executed_trades.append(trade_result)
                self.risk_manager.release_position(
                    position["category"], position["neg_risk_group"], position["condition_id"], position["notional"]
                )
                capital_history.append((position["resolve_ts"], capital))
            else:
                remaining.append(position)
        return remaining, capital

    def run(
        self,
        data: pd.DataFrame,
        splits: Iterable[Tuple[pd.Timestamp, pd.Timestamp]],
    ) -> Dict[str, object]:
        capital = self.config.initial_capital
        open_positions: List[Dict] = []
        executed_trades: List[TradeResult] = []
        capital_history: List[Tuple[pd.Timestamp, float]] = []

        data = data.sort_values("timestamp").reset_index(drop=True)

        for train_end, test_end in splits:
            train_mask = data["timestamp"] <= train_end
            test_mask = (data["timestamp"] > train_end) & (data["timestamp"] <= test_end)
            train_df = data.loc[train_mask]
            test_df = data.loc[test_mask]
            if test_df.empty:
                continue

            calibrator: IsotonicCalibrator = self.calibrator_factory()
            calibrator.fit(train_df[["price", "outcome", "tau_bucket"]])
            predictions = calibrator.transform(test_df[["price", "tau_bucket"]])
            test_with_pred = test_df.copy()
            test_with_pred["q_hat"] = predictions["q_hat"].to_numpy()
            test_with_pred["q_lower"] = predictions["q_lower"].to_numpy()

            for _, row in test_with_pred.iterrows():
                open_positions, capital = self._settle_positions(
                    row["timestamp"], open_positions, capital, executed_trades, capital_history
                )

                if capital <= 0:
                    continue

                book_key = (row["token_id"], row["timestamp"])
                book_snapshot = self.book_lookup.get(book_key)
                if book_snapshot is None:
                    continue

                q_hat = float(row["q_hat"])
                q_lower = float(row["q_lower"])
                if pd.isna(q_lower) or pd.isna(q_hat):
                    continue

                fraction = self.risk_manager.kelly_fraction(q_hat, row["price"])
                if fraction <= 0:
                    continue

                available_notional = self.risk_manager.available_notional(
                    capital,
                    row.get("category"),
                    row.get("neg_risk_group"),
                    row["condition_id"],
                )
                if available_notional <= 0:
                    continue

                target_notional = min(capital * fraction, available_notional)
                if target_notional <= 0:
                    continue

                available_liquidity = float(book_snapshot.loc[book_snapshot["side"] == "ask", "size"].sum())
                if available_liquidity <= 0:
                    continue

                tentative_size = min(available_liquidity, target_notional / row["price"])
                breakdown = self.cost_model.estimate_cost(
                    book_snapshot, tentative_size, row["time_to_event_days"]
                )
                if breakdown.notional > target_notional and breakdown.filled_size > 0:
                    adjusted_size = target_notional / breakdown.execution_price
                    breakdown = self.cost_model.estimate_cost(
                        book_snapshot, adjusted_size, row["time_to_event_days"]
                    )

                if breakdown.filled_size == 0:
                    continue

                if breakdown.notional + breakdown.total_cost > capital:
                    continue

                ev_lower = q_lower - breakdown.execution_price - breakdown.per_share_cost
                if ev_lower <= self.config.min_ev:
                    continue

                capital -= breakdown.notional
                capital -= breakdown.total_cost
                capital_history.append((row["timestamp"], capital))

                position = {
                    "trade_id": row["trade_id"],
                    "condition_id": row["condition_id"],
                    "timestamp": row["timestamp"],
                    "resolve_ts": row["resolve_ts"],
                    "category": row.get("category"),
                    "neg_risk_group": row.get("neg_risk_group"),
                    "price": row["price"],
                    "shares": breakdown.filled_size,
                    "notional": breakdown.notional,
                    "breakdown": breakdown,
                    "q_hat": q_hat,
                    "q_lower": q_lower,
                    "ev_lower": ev_lower,
                    "outcome": row["outcome"],
                }
                open_positions.append(position)
                self.risk_manager.register_position(
                    row.get("category"), row.get("neg_risk_group"), row["condition_id"], breakdown.notional
                )

        open_positions, capital = self._settle_positions(
            pd.Timestamp.max.tz_localize("UTC"), open_positions, capital, executed_trades, capital_history
        )

        capital_history.append((pd.Timestamp.max.tz_localize("UTC"), capital))

        return {
            "capital_history": capital_history,
            "executed_trades": executed_trades,
            "ending_capital": capital,
        }
