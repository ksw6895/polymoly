from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from backtest.engine import TradeResult


def compute_summary(trades: Iterable[TradeResult], initial_capital: float) -> dict:
    trades_list = list(trades)
    total_pnl = sum(t.pnl for t in trades_list)
    total_notional = sum(t.notional for t in trades_list)
    total_cost = sum(t.total_cost for t in trades_list)
    win_rate = (
        sum(1 for t in trades_list if t.payout >= t.notional) / len(trades_list)
        if trades_list
        else 0.0
    )
    average_return = (
        np.mean([t.pnl / t.notional for t in trades_list if t.notional > 0])
        if trades_list
        else 0.0
    )
    volatility = (
        np.std([t.pnl / t.notional for t in trades_list if t.notional > 0], ddof=1)
        if len(trades_list) > 1
        else 0.0
    )
    sharpe_like = average_return / volatility if volatility > 1e-9 else 0.0

    return {
        "trades": len(trades_list),
        "total_pnl": total_pnl,
        "total_notional": total_notional,
        "total_cost": total_cost,
        "win_rate": win_rate,
        "average_return": average_return,
        "sharpe_like": sharpe_like,
        "absolute_return": total_pnl / initial_capital if initial_capital else 0.0,
        "ending_capital": initial_capital + total_pnl,
    }


def compute_monthly_breakdown(trades: Iterable[TradeResult]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["month", "pnl", "notional", "count"])

    df = pd.DataFrame(
        {
            "resolve_ts": [t.resolve_ts for t in trades],
            "pnl": [t.pnl for t in trades],
            "notional": [t.notional for t in trades],
        }
    )
    df["month"] = df["resolve_ts"].dt.tz_convert(None).dt.to_period("M")
    grouped = df.groupby("month").agg({"pnl": "sum", "notional": "sum", "resolve_ts": "count"})
    grouped.rename(columns={"resolve_ts": "count"}, inplace=True)
    return grouped.reset_index()


def compute_calibration(trades: Iterable[TradeResult], n_bins: int = 5) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["bin", "mean_prediction", "empirical", "count"])

    df = pd.DataFrame(
        {
            "prediction": [t.q_hat for t in trades],
            "outcome": [1.0 if t.payout > 0 else 0.0 for t in trades],
        }
    )
    bins = np.linspace(0.5, 1.0, n_bins + 1)
    df["bin"] = pd.cut(df["prediction"], bins=bins, include_lowest=True)
    grouped = df.groupby("bin", observed=False).agg(
        mean_prediction=("prediction", "mean"),
        empirical=("outcome", "mean"),
        count=("outcome", "size"),
    )
    return grouped.reset_index()


def brier_score(trades: Iterable[TradeResult]) -> float:
    trades_list = list(trades)
    if not trades_list:
        return 0.0
    errors = [(t.q_hat - (1.0 if t.payout > 0 else 0.0)) ** 2 for t in trades_list]
    return float(np.mean(errors))
