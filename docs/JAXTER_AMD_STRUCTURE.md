# Jaxter AMD-Structure Entry Model

Jaxter is an additive, isolated strategy-assistant research engine. It does not import or modify Edith runtime, broker, risk, execution, governance, or adaptation components.

## Strategy contract

1. Accumulation: map the Asian range.
2. Manipulation: require a sharp London sweep and reclaim/rejection of the Asian boundary.
3. Structure: observe CHoCH, then require a displacement BOS.
4. Confluence: require overlap between the final opposing candle order block and a three-candle fair-value gap.
5. Entry: midpoint of the overlap zone, strictly after the BOS candle has closed.
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

## Upload through Edith Command Centre

Open the **Jaxter · Strategy Assistant** section and expand **Run a new Jaxter historical study**.

1. Upload the CSV.
2. Select XAUUSD symbol naming, M5 or M15 timeframe, 3–6 month lookback and 0.5–1.0% research-risk assumption.
3. Review the validated candle count and date span.
4. Select **Run AMD-Structure research**.

The upload is used only by Jaxter's research runner. It is not passed to Edith's runtime or broker components.

## Command-line historical run

```bash
python scripts/run_jaxter_amd_backtest.py data/xauusd_m5.csv --months 6 --symbol XAUUSD --timeframe M5
```

Each run is preserved under an immutable run directory:

```text
data/jaxter/runs/<run_id>/report.json
data/jaxter/runs/<run_id>/trades.jsonl
```

Dashboard-compatible latest-result snapshots are also maintained:

```text
data/jaxter/amd_structure_report.json
data/jaxter/amd_structure_trades.jsonl
```

Reports include the run ID, creation time, source filename, dataset hash, configuration hash and timing/ambiguity policies.

The runner accepts only 3–6 month windows. Entry eligibility begins strictly after the BOS confirmation candle. When stop and target are both touched inside one candle, the conservative baseline counts the stop first.

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
