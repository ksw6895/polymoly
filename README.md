# Polymoly — Polymarket Favorites Backtest

This repository packages a minimal but end-to-end implementation of the "favorites"
strategy described in `1stguide.md`.  It ingests public Polymarket exports, builds
probabilistic features for individual fills, calibrates prices with an isotonic
Jeffreys lower-bound model, and simulates liquidity-aware execution with Kelly-style
risk caps.  The goal is to let a researcher reproduce a local walk-forward
backtest, inspect calibration quality, and iterate on signal design without needing
access to the live APIs.

The code base is intentionally small: each module mirrors a step in the operating
protocol so it can be swapped with production-grade components once real data
pipelines are wired up.

## Repository layout

```
backtest/               # Execution cost model, risk controls, and walk-forward engine
feature/                # Feature engineering and labeling utilities
ingest/                 # CSV / JSON loaders that mimic Polymarket API payloads
model/                  # Isotonic calibrator with Jeffreys lower bounds
report/                 # Helper metrics for PnL summaries and calibration tables
data/                  # Synthetic Polymarket-style bundle used by the tests
run_backtest.py         # Driver that stitches the full pipeline together
tests/                  # Pytest coverage for the calibrator and pipeline sanity
```

Refer to `1stguide.md` for the original specification and motivation.

## Sample data bundle

The `data/` directory ships a synthetic slice of the sources referenced in the
specification.  The schema mirrors the real endpoints so that production ingestion
code can later be dropped in with minimal adaptation:

| File | Description |
| ---- | ----------- |
| `gamma_markets_sample.json` | Market metadata (condition id, slug, category, end date, token ids, neg-risk group). |
| `subgraph_resolutions.csv` | Resolution outcome, timestamp, and dispute flag per market. |
| `dataapi_trades.csv` | YES trade history pulled from the Data API with executed price/size. |
| `clob_books.csv` | Order-book snapshots (bid/ask ladder) aligned to trade timestamps. |
| `prices_history.csv` | `/prices-history` extracts for simple momentum and reference features. |

All timestamps are stored in ISO format and parsed as timezone-aware UTC
`pandas.Timestamp` objects by the loaders.

## Getting started

1. **Create a virtual environment** (Python 3.11+ recommended) and install the
   scientific stack:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Run the example backtest**.  The script trains the isotonic calibrator on the
   first split, applies it on the second, estimates execution costs from the order
   book, and prints a compact performance summary:

   ```bash
   python run_backtest.py
   ```

   The returned dictionary includes:

   * `summary`: aggregate trade and performance statistics keyed by the field names
     documented in `report/metrics.py`.
   * `monthly`: a `DataFrame` grouped by resolution month with PnL and turnover.
   * `calibration`: bin-wise predicted vs. empirical outcome comparison.
   * `brier_score`: scalar calibration error metric for the executed trades.
   * `backtest`: raw engine output containing capital history and trade objects.

3. **Execute the test suite** to ensure the calibrator monotonicity and the
   pipeline wiring remain intact:

   ```bash
   pytest -q
   ```

## How the pipeline fits together

1. **Ingestion (`ingest/`)** — lightweight loaders convert the CSV/JSON artifacts
   into canonical `pandas` frames.  They sort by timestamp and raise when a file is
   missing so failures surface early.
2. **Labeling (`feature/make_labels.py`)** — applies a configurable look-ahead cut
   (defaults to 4 hours) before joining the resolved YES/NO outcome, ensuring the
   training set does not peek beyond the chosen trading horizon.
3. **Feature engineering (`feature/make_features.py`)** — enriches each labeled
   trade with Gamma metadata, time-to-event buckets, order-book depth, spreads, and
   simple price momentum features sourced from `/prices-history`.
4. **Calibration (`model/calibrate_isotonic.py`)** — fits a monotonic isotonic
   regression per time-to-event bucket and derives Jeffreys prior lower bounds to
   guard against sparse neighborhoods.
5. **Execution (`backtest/`)** — the engine sizes trades via a damped Kelly rule,
   enforces category / neg-risk / market caps, replays fills against the
   order-book snapshots, and debits gas and borrow costs before adding positions to
   the book.
6. **Reporting (`report/metrics.py`)** — aggregates PnL, PnL per month, and
   calibration diagnostics that mirror the validation checkpoints in the spec.

## Extending the prototype

* Swap the CSV loaders with API clients once credentials and rate limits are
  available.  The rest of the pipeline only expects the `DataFrame` schemas
  described above.
* The `IsotonicCalibrator` exposes a `CalibrationConfig`; adjust `neighborhood` or
  `min_count` when working with denser historical datasets.
* Replace the naive cost model with exchange-specific gas, bridging, or dynamic
  slippage assumptions if you have access to richer book snapshots.
* Additional metrics or plots can be implemented under `report/` without touching
  the core engine.

## Troubleshooting

* **Missing metadata errors** usually mean the condition id in the trades file is
  not present in the Gamma market snapshot.  Ensure the datasets were exported on
  compatible dates.
* **No liquidity warnings** occur when an order-book snapshot lacks ask levels for
  the targeted timestamp.  Either rebuild the snapshot export or relax the
  filters in `_prepare_order_book_features`.
* **Empty backtests** indicate all trades were filtered by the time cut or by the
  minimum EV threshold.  Check the `min_ev` parameter in `BacktestConfig` and the
  label configuration.

## License

No license is provided.  Treat this repository as internal research material.
