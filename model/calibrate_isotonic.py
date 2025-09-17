from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy.stats import beta


@dataclass
class CalibrationConfig:
    alpha: float = 0.05
    neighborhood: float = 0.05
    min_count: int = 2


@dataclass
class _BucketModel:
    prices: np.ndarray
    outcomes: np.ndarray
    xp: np.ndarray
    yp: np.ndarray

    def predict_mean(self, price: float) -> float:
        return float(np.interp(price, self.xp, self.yp, left=self.yp[0], right=self.yp[-1]))


def _pav(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Pool-adjacent-violators algorithm for isotonic regression."""
    y = y.astype(float)
    w = w.astype(float)
    n = len(y)
    solution = y.copy()
    weight = w.copy()

    i = 0
    while i < n - 1:
        if solution[i] > solution[i + 1]:
            total_weight = weight[i] + weight[i + 1]
            avg = (solution[i] * weight[i] + solution[i + 1] * weight[i + 1]) / total_weight
            solution[i] = solution[i + 1] = avg
            weight[i] = weight[i + 1] = total_weight
            j = i
            while j > 0 and solution[j - 1] > solution[j]:
                total_weight = weight[j - 1] + weight[j]
                avg = (solution[j - 1] * weight[j - 1] + solution[j] * weight[j]) / total_weight
                solution[j - 1] = solution[j] = avg
                weight[j - 1] = weight[j] = total_weight
                j -= 1
            i = max(j - 1, 0)
        else:
            i += 1
    return solution


def _fit_bucket(prices: np.ndarray, outcomes: np.ndarray) -> _BucketModel:
    order = np.argsort(prices)
    x = prices[order]
    y = outcomes[order]
    w = np.ones_like(y)

    fitted = _pav(y, w)
    df = pd.DataFrame({"price": x, "fitted": fitted})
    aggregated = df.groupby("price", as_index=False)["fitted"].mean()
    xp = aggregated["price"].to_numpy()
    yp = aggregated["fitted"].to_numpy()

    return _BucketModel(prices=x, outcomes=y, xp=xp, yp=yp)


class IsotonicCalibrator:
    def __init__(self, config: Optional[CalibrationConfig] = None) -> None:
        self.config = config or CalibrationConfig()
        self._models: Dict[str, _BucketModel] = {}

    def fit(self, data: pd.DataFrame) -> None:
        if data.empty:
            raise ValueError("Training data is empty")

        if {"price", "outcome", "tau_bucket"} - set(data.columns):
            raise ValueError("Training data missing required columns")

        for bucket, bucket_df in data.groupby("tau_bucket", observed=False):
            prices = bucket_df["price"].to_numpy()
            outcomes = bucket_df["outcome"].to_numpy()
            if len(prices) == 0:
                continue
            self._models[str(bucket)] = _fit_bucket(prices, outcomes)

        if not self._models:
            raise ValueError("No bucket models were fitted")

    def _lower_bound(self, model: _BucketModel, price: float) -> float:
        config = self.config
        window = config.neighborhood
        prices = model.prices
        outcomes = model.outcomes

        distances = np.abs(prices - price)
        mask = distances <= window
        while mask.sum() < config.min_count and window < 0.1:
            window *= 1.5
            mask = distances <= window

        count = mask.sum()
        if count == 0:
            return float("nan")

        successes = outcomes[mask].sum()
        failures = count - successes
        lb = beta.ppf(config.alpha, successes + 0.5, failures + 0.5)
        return float(lb)

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        if not self._models:
            raise RuntimeError("Calibrator has not been fitted")

        required = {"price", "tau_bucket"}
        if missing := (required - set(data.columns)):
            raise ValueError(f"Missing columns for transform: {missing}")

        predictions = []
        lowers = []
        sample_counts = []

        for _, row in data.iterrows():
            bucket_key = str(row["tau_bucket"])
            model = self._models.get(bucket_key)
            if model is None:
                predictions.append(np.nan)
                lowers.append(np.nan)
                sample_counts.append(0)
                continue

            mean = model.predict_mean(row["price"])
            lb = self._lower_bound(model, row["price"])
            if np.isnan(lb):
                lb = mean
                count = 0
            else:
                lb = min(lb, mean)
                distances = np.abs(model.prices - row["price"])
                count = int((distances <= self.config.neighborhood).sum())
            predictions.append(mean)
            lowers.append(lb)
            sample_counts.append(count)

        result = data.copy()
        result["q_hat"] = predictions
        result["q_lower"] = lowers
        result["sample_count"] = sample_counts
        return result
