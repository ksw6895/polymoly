from __future__ import annotations

import pandas as pd

from run_backtest import run_backtest


def test_run_backtest_pipeline():
    result = run_backtest()
    summary = result["summary"]
    assert summary["trades"] > 0
    assert summary["ending_capital"] > 0
    assert isinstance(result["monthly"], pd.DataFrame)
    assert isinstance(result["calibration"], pd.DataFrame)
