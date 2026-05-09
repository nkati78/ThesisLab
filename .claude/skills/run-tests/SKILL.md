---
name: run-tests
description: Run the project's tests and validation checks. Use when the user asks to run tests, verify changes, type-check, or smoke-test after editing.
---

When the user asks to test, verify, or validate changes, run the relevant checks below. Always run a check before declaring code "done."

## Type checks (always run after edits)

| Layer | Command |
|---|---|
| Python (whole modified file) | `python -m py_compile path/to/file.py` |
| Frontend | `cd frontend && npx tsc --noEmit` |

These catch syntax errors, type errors, and most refactor breakage. Never report "done" without running them when applicable.

## Pytest (when tests exist)

The project does not yet have a formal test suite under `tests/`. If/when tests are added, run:

```bash
python -m pytest
python -m pytest tests/test_vertical_spread.py -v   # specific file
python -m pytest -k "iron_condor"                    # match name
```

If invoked and `tests/` is empty, say so explicitly rather than reporting a pass.

## Engine smoke test (most common verification)

Build a provider, run a small backtest, assert basic invariants. Useful after touching `thesislab/strategies/`, `thesislab/engine/`, or `thesislab/data/`.

```python
from datetime import date
from thesislab.data.fake_provider import FakeDataProvider
from thesislab.engine.backtester import Backtester, BacktestConfig
from thesislab.strategies.vertical_spread import VerticalSpread, SpreadDirection

provider = FakeDataProvider(ticker="AAPL", start_price=450)
config = BacktestConfig(
    ticker="AAPL", start_date=date(2023, 1, 3), end_date=date(2023, 3, 1),
    starting_cash=100_000,
)
strategy = VerticalSpread(direction=SpreadDirection.BULL, short_delta=0.25, spread_width=5)
result = Backtester(config=config, provider=provider, strategies=[strategy]).run()

assert len(result.closed_positions) > 0, "expected at least one trade"
print(f"trades={len(result.closed_positions)}, P&L=${result.total_pnl:.2f}")
```

For ThetaData-backed checks, use a SHORT range to avoid long fetches:

```python
from datetime import date
from thesislab.data.thetadata_provider import ThetaDataProvider

p = ThetaDataProvider(
    ticker="SPX",
    start_date=date(2024, 1, 2), end_date=date(2024, 1, 12),
    dte_window=(4, 4),
)
chain = p.get_chain("SPX", date(2024, 1, 8))
assert chain is not None and len(chain.contracts) > 0
```

## API smoke test (full end-to-end)

After backend changes, hit the running uvicorn:

```bash
curl -s -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","start_date":"2023-01-03","end_date":"2023-03-01","starting_cash":100000,"commission":0,"strategy":{"type":"short_put_spread","min_dte":25,"max_dte":45,"short_delta":0.25,"spread_width":5,"max_positions":1,"contracts_per_trade":1,"close_at_profit_pct":0.5,"close_at_loss_pct":2.0,"close_at_dte":7,"close_at_profit_enabled":false,"close_at_loss_enabled":false,"close_at_dte_enabled":false,"close_on_short_breach":false,"entry_dow":"any","put_delta":-0.2,"wing_width":5},"advanced_filters":{"time_of_day":{"enabled":false,"entry_start":"09:30","entry_end":"16:00","exit_start":"09:30","exit_end":"16:00"},"rsi":{"enabled":false,"rsi_min":20,"rsi_max":80,"rsi_zone":"any"},"bollinger":{"enabled":false,"position":"any","use_pct_b":false,"pct_b_min":0,"pct_b_max":0.2},"moving_average":{"enabled":false,"sma_20":"ignore","sma_50":"ignore","sma_200":"ignore","ema_9":"ignore","ema_21":"ignore","sma_cross":"ignore"},"vwap":{"enabled":false,"direction":"above"}},"data_source":"synthetic","synthetic_config":{"start_price":450,"daily_drift":0.0003,"base_iv":0.25,"seed":42}}' \
  | python -c "import sys,json; d=json.load(sys.stdin); print(f'trades={d[\"total_trades\"]}, P&L=${d[\"total_pnl\"]:.2f}, win_rate={d[\"win_rate\"]:.1f}%')"
```

Use `data_source: "synthetic"` for CI-safe checks (no API calls). Switch to `"thetadata"` only when explicitly testing the live data path.

## Frontend visual checks

There is no automated UI test suite. After UI changes, instead:
1. Run `cd frontend && npx tsc --noEmit` (must compile clean).
2. Confirm Vite is serving (`http://localhost:5177` or whatever port is current).
3. Tell the user what to click — don't claim a UI change works without browser verification.

## Reporting results

- ✅ Compile + tsc + smoke test all pass → "verified, ready to ship."
- ❌ Anything fails → quote the error, do not gloss over it.
- ⚠️  No automated test exists for the change → say so explicitly rather than claiming success.
