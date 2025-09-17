from __future__ import annotations

import numpy as np
import pandas as pd

from model.calibrate_isotonic import IsotonicCalibrator


def test_isotonic_monotonic():
    prices = np.linspace(0.8, 0.99, 20)
    outcomes = (prices > 0.9).astype(float)
    tau_bucket = ["1-3d"] * len(prices)
    df = pd.DataFrame({"price": prices, "outcome": outcomes, "tau_bucket": tau_bucket})

    calibrator = IsotonicCalibrator()
    calibrator.fit(df)
    preds = calibrator.transform(df)
    q_hat = preds["q_hat"].to_numpy()
    assert np.all(np.diff(q_hat) >= -1e-8)
