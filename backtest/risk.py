from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RiskConfig:
    kelly_lambda: float = 0.4
    max_fraction: float = 0.25
    category_cap: float = 0.4
    neg_risk_cap: float = 0.4
    market_cap: float = 0.5


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()
        self._category_exposure: Dict[str, float] = defaultdict(float)
        self._neg_risk_exposure: Dict[str, float] = defaultdict(float)
        self._market_exposure: Dict[str, float] = defaultdict(float)

    def kelly_fraction(self, q_hat: float, price: float) -> float:
        edge = q_hat - price
        if edge <= 0 or price >= 1:
            return 0.0
        raw = edge / (1.0 - price)
        return max(0.0, min(self.config.max_fraction, self.config.kelly_lambda * raw))

    def available_notional(
        self,
        capital: float,
        category: Optional[str],
        neg_risk_group: Optional[str],
        market: str,
    ) -> float:
        caps = [capital]
        if category:
            caps.append(max(0.0, self.config.category_cap * capital - self._category_exposure[category]))
        if neg_risk_group:
            caps.append(
                max(0.0, self.config.neg_risk_cap * capital - self._neg_risk_exposure[neg_risk_group])
            )
        caps.append(max(0.0, self.config.market_cap * capital - self._market_exposure[market]))
        return max(0.0, min(caps))

    def register_position(
        self,
        category: Optional[str],
        neg_risk_group: Optional[str],
        market: str,
        notional: float,
    ) -> None:
        if category:
            self._category_exposure[category] += notional
        if neg_risk_group:
            self._neg_risk_exposure[neg_risk_group] += notional
        self._market_exposure[market] += notional

    def release_position(
        self,
        category: Optional[str],
        neg_risk_group: Optional[str],
        market: str,
        notional: float,
    ) -> None:
        if category:
            self._category_exposure[category] = max(0.0, self._category_exposure[category] - notional)
        if neg_risk_group:
            self._neg_risk_exposure[neg_risk_group] = max(
                0.0, self._neg_risk_exposure[neg_risk_group] - notional
            )
        self._market_exposure[market] = max(0.0, self._market_exposure[market] - notional)
