# Jaxter AMD-Structure Entry Model

Jaxter is an additive, isolated strategy-assistant research engine. It does not import or modify Edith runtime, broker, risk, execution, governance, or adaptation components.

## Strategy contract

1. Accumulation: map the Asian range.
2. Manipulation: require a sharp London sweep and reclaim/rejection of the Asian boundary.
3. Structure: observe CHoCH, then require a displacement BOS.
4. Confluence: require overlap between the final opposing candle order block and a three-candle fair-value gap.
5. Entry: midpoint of the overlap zone.
6. Invalidation: beyond the manipulation wick plus a small ATR buffer.
7. Target: configurable R target, default 2R and never below 1.5R.
8. Quality: one setup per session; no Asian-session entries; weak or grinding sweeps are rejected.

## Safety boundary

- observational output only
- no order placement
- no Edith signal mutation
- no broker dependency
- no automatic promotion
- research risk assumption limited to 0.5–1.0% per setup
- historical evidence does not authorize execution

## Required data

Completed intraday OHLC candles with columns:

```text
timestamp,open,high,low,close
```

M5 or M15 XAUUSD data is recommended. Timestamps are parsed as UTC by default. Session windows are configurable through `AMDStructureConfig`.

## Historical run

```bash
python scripts/run_jaxter_amd_backtest.py data/xauusd_m5.csv --months 6 --symbol XAUUSD --timeframe M5
```

Outputs:

```text
data/jaxter/amd_structure_report.json
data/jaxter/amd_structure_trades.jsonl
```

The runner accepts only 3–6 month windows and uses conservative bar semantics: when stop and target are both touched inside one candle, the stop is counted first.

## Minimum validation before assistant promotion

Jaxter must remain research-only until a separate governance review defines and passes minimum evidence for:

- sample size
- out-of-sample performance
- win rate and expectancy
- profit factor
- maximum drawdown
- session and regime stability
- spread and slippage sensitivity
- parameter sensitivity
- walk-forward stability
- Monte Carlo trade-order perturbation

Promotion should create a new integration contract. It must not convert this research engine into an implicit execution dependency.
