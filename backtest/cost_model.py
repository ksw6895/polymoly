from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass
class CostBreakdown:
    execution_price: float
    filled_size: float
    slippage_cost: float
    taker_fee_cost: float
    gas_cost: float
    borrow_cost: float

    @property
    def notional(self) -> float:
        return self.execution_price * self.filled_size

    @property
    def transaction_cost(self) -> float:
        return self.slippage_cost + self.taker_fee_cost + self.gas_cost

    @property
    def total_cost(self) -> float:
        return self.transaction_cost + self.borrow_cost

    @property
    def per_share_cost(self) -> float:
        if self.filled_size == 0:
            return 0.0
        return self.total_cost / self.filled_size


class CostModel:
    def __init__(
        self,
        taker_fee: float = 0.0,
        gas_cost: float = 0.25,
        borrow_rate: float = 0.05,
    ) -> None:
        self.taker_fee = taker_fee
        self.gas_cost = gas_cost
        self.borrow_rate = borrow_rate

    def _compute_vwap(self, asks: pd.DataFrame, size: float) -> tuple[float, float]:
        remaining = size
        total_cost = 0.0
        filled = 0.0
        for _, row in asks.sort_values("price").iterrows():
            available = float(row["size"])
            take = min(remaining, available)
            total_cost += take * float(row["price"])
            filled += take
            remaining -= take
            if remaining <= 1e-9:
                break
        if filled == 0:
            return float("nan"), 0.0
        return total_cost / filled, filled

    def estimate_cost(
        self,
        book_snapshot: pd.DataFrame,
        target_size: float,
        tau_days: float,
    ) -> CostBreakdown:
        asks = book_snapshot[book_snapshot["side"] == "ask"]
        if asks.empty:
            raise ValueError("No ask liquidity available")

        best_ask = float(asks.loc[asks["level"].idxmin(), "price"])
        vwap, filled = self._compute_vwap(asks, target_size)
        if filled == 0:
            raise ValueError("Unable to fill order with available liquidity")

        slippage_cost = max(0.0, (vwap - best_ask) * filled)
        taker_fee_cost = self.taker_fee * vwap * filled
        borrow_cost = max(tau_days, 0.0) / 365.0 * self.borrow_rate * vwap * filled
        gas_cost = self.gas_cost

        return CostBreakdown(
            execution_price=vwap,
            filled_size=filled,
            slippage_cost=slippage_cost,
            taker_fee_cost=taker_fee_cost,
            gas_cost=gas_cost,
            borrow_cost=borrow_cost,
        )
