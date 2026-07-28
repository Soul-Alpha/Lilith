# Edith Trade Forensics — Phase 1 Integration

This module is additive and does not modify Edith's signal, entry, stop-loss, take-profit, or lot-sizing rules.

## Runtime integration points

The notebook should construct an immutable `EntrySnapshot` only after the broker confirms the fill. Persist it before beginning position management.

On every position-management poll, append a `LifecycleSnapshot` using the executable mark price:

- BUY positions use bid for exit valuation.
- SELL positions use ask for exit valuation.

After broker history confirms closure, construct `RealisedOutcome` from the broker deal record. Gross profit, commission, swap, and fees must be copied separately. Do not derive realised PnL from account balance changes or console counters.

Call `TradeForensicsService.analyse(entry, lifecycle, outcome)` and persist the resulting `TradeForensicReport`.

## Required broker identifiers

The integration must preserve:

- internal trade ID
- signal ID
- broker order ID
- broker deal ID
- broker position ID
- runtime/session ID
- strategy version
- configuration hash

## Exit classification precedence

1. Explicit broker reason or reason code.
2. Explicit runtime action, such as manual close or timeout.
3. Price proximity to SL, TP, or entry within configured tolerance.
4. `UNKNOWN` when the evidence is insufficient.

Unknown exits must not be silently counted as TP, SL, or breakeven.

## Counterfactual analysis

`simulate_breakeven` and `simulate_atr_trailing` operate on recorded lifecycle snapshots. They are research-only and must not submit or modify broker orders.

Promote no trailing policy to live execution until replay and forward evidence show improvement in net expectancy, drawdown, profit factor, and protected-trade frequency after costs.

## Phase 1 acceptance conditions

- Every closed broker position has one reconciled realised outcome.
- Net realised PnL includes commission, swap, and fees.
- MFE and MAE are calculated from executable bid/ask prices.
- Stop-outs that first achieved meaningful positive excursion are identified.
- Unknown or incomplete broker data fails closed and remains visibly unresolved.
