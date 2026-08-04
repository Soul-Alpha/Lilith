# Edith MT5 Demo High-Grade Spread Override

Edith keeps the normal MT5 demo spread gate at `EDITH_MT5_MAX_SPREAD_POINTS=80`. That value remains the default protection for ordinary entry-eligible signals, so a moderately wider XAUUSDm spread does not become acceptable by default.

The high-grade override is a narrow execution-quality exception for MT5 demo mode only. It is available when a signal score is at least `EDITH_MT5_HIGH_GRADE_SCORE=85`, the directional regime latch is armed, and the measured spread stays inside both caps:

- hard cap: `EDITH_MT5_HIGH_GRADE_MAX_SPREAD_POINTS=260`
- ATR-relative cap: `EDITH_MT5_HIGH_GRADE_MAX_SPREAD_ATR_FRACTION=0.07`

The ATR-relative cap prevents a fixed 260-point allowance from being used when current market movement is too small to justify it. The runtime calculates `atr * fraction / point` and uses the smaller of that value and the hard cap. The effective limit is never allowed below the normal 80-point gate, so high-grade calculation cannot make ordinary spread protection stricter.

A score of 85 is not an 85% win probability. It is Edith's internal ATR-normalised confidence score from the fast/slow SMA signal engine. The signal engine's periods, score formula, direction logic, 60-point entry eligibility threshold, completed-candle processing, and signal key format are unchanged.

## One-Per-Regime Latch

The override is available once per directional regime: `BUY` or `SELL`. The latch rearms when direction changes, or when the same direction's score falls below `EDITH_MT5_HIGH_GRADE_REARM_SCORE=70` and later recovers. A high-grade override is consumed only after MT5 accepts an order that used the extended spread allowance.

The latch is not consumed by projected cash-risk rejection, equity risk rejection, daily loss limits, drawdown limits, margin limits, open-position or pending-order protection, failed `order_check`, failed `order_send`, or temporary terminal and symbol-data errors.

The latch state is persisted in `data/mt5_runtime_state.json` with additive fields, so restarts preserve whether the current directional override was already consumed. Legacy state files without those fields still load with safe defaults.

## Demo-Only Governance

This override does not enable live-account execution. Edith still requires `LILITH_EXECUTION_MODE=mt5-demo`, `EDITH_MT5_CONFIRM_DEMO=YES`, a demo MT5 account, matching login and server, terminal connectivity, algorithmic-trading permission, symbol availability, all risk limits, broker filling mode, `order_check`, `order_send`, duplicate-candle protection, runtime locking, forensic reconciliation, portfolio intelligence, and the daily risk ledger.

Every order-attempt record includes structured spread metadata: measured spread, normal limit, hard cap, ATR cap, effective limit, signal score, gate mode, override state, and rejection category/reason when applicable. Spread rejections are classified as `market_quality`, not portfolio risk.
