# Lilith

Lilith is an experimental MetaTrader 5 scalping prototype currently implemented in `edith.ipynb`.

> [!CAUTION]
> **Edith governance status: QUARANTINED FOR LIVE EXECUTION.**
>
> The repository is not approved for unattended or capital-bearing operation. The current notebook combines credentials, mutable configuration, signal analysis, risk calculations, runtime state, and broker execution in one stateful environment. Repository hardening must be completed before live use is reconsidered.

## Current repository state

The repository currently consists primarily of a single Jupyter notebook. There are no isolated Python application modules, automated tests, dependency lockfiles, CI workflows, durable state services, or independent execution and risk boundaries.

This README documents the remediation programme. It does **not** certify the strategy, expected return, win rate, or safety of live operation.

## Immediate security incident response

A broker credential was committed directly inside the notebook. Because the repository is public, the credential must be treated as compromised.

Complete these steps before any further operation:

1. Rotate the affected MetaTrader 5 password immediately.
2. Review broker login, order, and account history for unauthorized activity.
3. Disable or remove the exposed credential from every active runtime.
4. Remove the secret from the notebook.
5. Rewrite Git history to purge the secret from previous commits.
6. Invalidate old clones or deployments that contain the credential.
7. Introduce repository and pre-commit secret scanning.

Adding `.gitignore` prevents future local secret files from being committed, but it does not remove secrets already present in Git history.

## Non-negotiable safety policy

Until the remediation gates below pass:

- Live execution must remain disabled.
- The repository may be used only for read-only analysis, controlled simulation, architecture extraction, and test development.
- No unattended notebook execution is permitted.
- No additional capital should be allocated to Lilith.
- Only one runtime instance may access a configured account.
- Exceptions in risk, market-data, or broker validation paths must fail closed.
- Strategy behaviour must not be changed while safety and architecture extraction are being performed unless separately reviewed and approved.

## Critical findings

| Priority | Finding | Required outcome |
|---|---|---|
| P0 | Plaintext MT5 credentials committed | Rotate credentials and purge repository history |
| P0 | Live order placement enabled in notebook configuration | Default to simulation and require external live approval |
| P0 | Risk limits can permit account-threatening loss | Add independent cash-risk, drawdown, exposure, and margin gates |
| P0 | No duplicate-instance prevention | Add process lock, runtime identity, and broker reconciliation |
| P1 | Strategy, risk, and order execution share one function/runtime | Extract stable interfaces without changing trading rules |
| P1 | Runtime state is stored in notebook globals | Add durable session and execution-event state |
| P1 | Exceptions return plausible trading fallbacks | Fail closed when data, risk, configuration, or broker checks fail |
| P1 | Documentation contradicts executable dependencies/configuration | Make code, configuration, and operating documentation consistent |
| P2 | No automated tests | Add unit, contract, integration, and safety tests |
| P2 | No dependency manifest or version lock | Add `pyproject.toml` and a reproducible lock strategy |
| P2 | No GitHub Actions | Add CI, security scanning, and notebook checks |
| P3 | No institutional validation evidence | Add replay, walk-forward, cost, stress, and Monte Carlo validation |

## Remediation roadmap

### Phase 0 — Contain the current exposure

**Exit gate:** exposed credentials are invalid, Git history has been cleaned, and live execution cannot be activated accidentally.

- Rotate the broker password.
- Remove credentials from notebook cells and outputs.
- Purge the credential from Git history using an approved history-rewrite procedure.
- Set live execution to disabled by default.
- Add an explicit account allowlist and symbol allowlist.
- Establish a broker-side and process-side kill switch.
- Add a singleton process lock to prevent duplicate execution loops.
- Preserve a forensic snapshot before cleanup, stored securely outside the public repository.

### Phase 1 — Add a safety envelope without modifying strategy logic

**Exit gate:** every proposed order passes an independent, testable risk decision before reaching the broker adapter.

Introduce externally configured and validated controls for:

- maximum cash risk per trade
- maximum aggregate open risk
- daily realized and unrealized loss
- equity drawdown
- margin utilization
- maximum lot size and position count
- stale market data
- duplicate signals and orders
- unsupported account, symbol, or execution mode
- consecutive losses and order frequency

All risk, data, and broker validation failures must reject execution rather than substitute generic stop, target, or lot values.

### Phase 2 — Extract the notebook into governed components

**Exit gate:** the notebook becomes an optional research/operator interface and no longer owns credentials, execution state, or direct broker order construction.

Target structure:

```text
lilith/
├── pyproject.toml
├── README.md
├── .env.example
├── src/lilith/
│   ├── configuration.py
│   ├── domain/
│   ├── market_data/
│   ├── strategy/
│   ├── risk/
│   ├── execution/
│   ├── portfolio/
│   ├── persistence/
│   └── observability/
├── notebooks/
├── tests/
└── .github/workflows/
```

Required boundaries:

```text
Market data → Features → Signal decision → Risk decision
→ Execution intent → Broker validation → Order submission
→ Execution event → Portfolio reconciliation
```

The first extraction pass should preserve observable strategy behaviour. Strategy changes belong in separate, explicitly reviewed work.

### Phase 3 — Reproducibility and automated verification

**Exit gate:** a clean machine can install, validate, and test the project without connecting to a live broker.

Add:

- `pyproject.toml` with explicit dependency constraints
- reproducible dependency locking
- unit tests for indicators, scoring, sizing, sessions, targets, and limits
- broker contract tests using an MT5 adapter mock
- integration tests for disconnection, stale data, rejection, margin failure, and invalid stops
- safety tests proving live mode is disabled by default
- static typing and linting
- structured test fixtures and recorded market-data replay

### Phase 4 — CI and repository governance

**Exit gate:** unsafe or unverifiable changes cannot be merged silently.

Recommended pull-request checks:

1. secret detection
2. Python and notebook syntax validation
3. reproducible dependency installation
4. linting and formatting checks
5. static type checks
6. automated tests and coverage
7. static security analysis
8. dependency vulnerability audit
9. notebook output and metadata checks
10. live-trading guard tests

CI must never connect to MT5 or submit orders.

### Phase 5 — Institutional validation

**Exit gate:** Edith records a formal approval decision based on reproducible evidence.

Required evidence includes:

- out-of-sample and walk-forward results
- realistic spread, commission, slippage, and rejection modelling
- Monte Carlo trade-order and execution perturbation
- parameter sensitivity and regime segmentation
- leakage checks
- risk-of-ruin and drawdown analysis
- paper-trading burn-in
- shadow-live comparison
- versioned strategy, feature, configuration, and dataset identifiers

## Proposed component contracts

The extracted system should represent decisions explicitly rather than passing loosely related globals.

```python
@dataclass(frozen=True)
class SignalDecision:
    symbol: str
    side: Literal["BUY", "SELL", "HOLD"]
    score: float
    strategy_version: str
    feature_timestamp: datetime
    reasons: tuple[str, ...]
```

```python
@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    lot_size: Decimal
    stop_price: Decimal | None
    target_price: Decimal | None
    projected_cash_risk: Decimal
    rejection_reasons: tuple[str, ...]
```

```python
@dataclass(frozen=True)
class ExecutionIntent:
    intent_id: UUID
    account_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: Decimal
    stop_price: Decimal
    target_price: Decimal
    strategy_version: str
    configuration_hash: str
```

## Required audit records

Every execution lifecycle should produce durable, structured records for:

- bot session and runtime identity
- market-data freshness
- signal decision and reasons
- risk decision and rejected checks
- execution intent
- broker request and response
- position snapshots and reconciliation
- circuit-breaker events
- strategy and configuration versions
- realized outcome

Console output alone is not an institutional audit trail.

## Secret and local configuration policy

Secrets must never be committed. Use an external secret provider or environment variables loaded from an untracked local file.

An eventual `.env.example` may document names only, for example:

```dotenv
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
LILITH_EXECUTION_MODE=simulation
LILITH_ALLOWED_ACCOUNT=
LILITH_ALLOWED_SYMBOL=XAUUSDm
```

Do not place real values in `.env.example`, notebook outputs, screenshots, logs, tests, issues, or pull-request descriptions.

## Development principles

- Preserve historical evidence and source attribution.
- Separate research, simulation, paper, and live environments.
- Make changes additive and reviewable.
- Do not alter trading logic during architecture-only work.
- Fail closed for missing or stale data.
- Use deterministic configuration and immutable decision records.
- Require evidence before strategy promotion.
- Treat capital preservation and auditability as system requirements.

## Current approval matrix

| Activity | Status |
|---|---|
| Read-only inspection | Approved |
| Credential remediation | Approved and urgent |
| Architecture extraction | Approved |
| Unit and safety test development | Approved |
| Controlled simulation | Approved after credential removal |
| Paper trading | Requires Phase 1 safety gates |
| Shadow live | Requires Phases 1–4 |
| Unattended live execution | Not approved |
| Additional capital allocation | Not approved |

## Disclaimer

Lilith is experimental software. Nothing in this repository or README constitutes financial advice, a profit guarantee, or evidence that the strategy is suitable for live capital. Trading leveraged instruments can result in substantial or total loss.
