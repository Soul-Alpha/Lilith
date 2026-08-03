# Edith Daily Portfolio Risk Ledger

The daily risk ledger is the first implementation sprint of Portfolio Intelligence Phase 2.
It is additive, advisory, and cannot alter signal generation, position sizing, orders, stops,
targets, or execution configuration.

## Daily accounting contract

Consumed risk is defined as:

```text
absolute realised trading losses today
+ projected stop-risk on currently open Edith positions
```

Realised winning trades do not restore the daily risk budget. Deposits, withdrawals, and
other external account adjustments are excluded from trading PnL and reported separately.

The ledger keeps cash and R accounting separate:

- configured daily cash budget
- configured daily R budget
- realised trading profit and loss
- realised losing R
- current open stop-risk
- consumed risk
- remaining risk
- floating PnL
- current consecutive-loss count

## Evidence behavior

The ledger will not claim available risk when open-position risk cannot be reconciled.
Instead it writes `null` for consumed and remaining risk and records explicit evidence reasons.

Reconciliation checks include:

- current runtime open-position count versus reconstructed open positions
- accepted-order risk evidence for every open position
- current position snapshot evidence
- complete versus partial position closes
- forensic PnL versus runtime daily realised PnL
- closed broker positions awaiting forensic reconciliation
- duplicate and conflicting source identifiers

## Persistence

Append-only history:

```text
data/portfolio/daily_risk_snapshots.jsonl
```

Atomic latest snapshot for Edith Command Centre:

```text
data/portfolio/latest_daily_risk.json
```

Identical evidence produces the same deterministic report ID and is not appended twice.
Every snapshot includes schema version, policy version, source record IDs, configuration hash,
evidence status, and generation time.

## Configuration

```text
EDITH_PORTFOLIO_DAILY_BUDGET_CASH=5.00
EDITH_PORTFOLIO_DAILY_BUDGET_R=2.0
EDITH_PORTFOLIO_CURRENCY=USD
```

If the cash budget is omitted, the runtime uses the existing MT5 maximum daily-loss amount as
the advisory ledger budget. These settings are observational only during Portfolio Intelligence
Phase 2.

## Command Centre

`dashboard_portfolio.py` displays:

- daily budget
- realised PnL
- realised losses
- open stop-risk
- risk consumed
- risk remaining
- open portfolio heat
- floating PnL
- closed trades, open positions, and current loss streak
- reconciliation exceptions and source lineage

Missing or conflicting evidence is shown as `Awaiting`, never as a false zero.
