# Agent Guidelines for `polymoly`

These instructions apply to the entire repository.

## Coding style

- Target **Python 3.11** or newer.
- Keep modules small and composable.  Prefer pure functions and `@dataclass`
  containers over ad-hoc dictionaries for structured data.
- Type annotate all new function signatures and public class attributes.  Use
  `pandas.Timestamp` objects for times and always store them as timezone-aware UTC.
- Document non-trivial functions with short docstrings explaining inputs,
  outputs, and side effects.  Inline comments should focus on clarifying domain
  reasoning (calibration, execution, or risk logic).
- Follow the existing formatting conventions (88 column target, black-style
  spacing).  Do **not** add blanket try/except blocks around imports or large code
  regions.

## Data & modeling conventions

- Treat the CSV/JSON fixtures under `data/` as canonical examples.  When adding
  new columns or files, update the README table and keep schemas backward
  compatible.
- Preserve determinism for backtests and calibrators.  If randomness is
  unavoidable, expose the seed in the relevant configuration dataclass.
- When introducing new metrics or configuration, wire them through the existing
  dataclass-based configs (`BacktestConfig`, `RiskConfig`, etc.) instead of using
  globals.

## Testing and validation

- Run `pytest -q` before committing.  Add or update tests alongside behavioural
  changes to ingest, feature engineering, modeling, backtesting, or reporting code.
- For documentation-only changes you may skip pytest locally, but note that CI will
  still execute it.

## Documentation expectations

- Keep `README.md` aligned with the real execution steps and data columns.  Update
  it whenever command syntax, configuration defaults, or data schemas change.
- Prefer Markdown tables for schema descriptions and numbered lists for workflow
  checklists.

## Pull request summaries

When preparing a PR message, summarize functional changes and any data/schema
updates.  Always list the exact test commands that were run.
