# Lilith / Edith Command Centre

Lilith is a governed MetaTrader 5 research, telemetry, demo-execution, and strategy-assistance repository for Edith. The current codebase includes packaged Python modules, automated tests, Streamlit dashboards, Jaxter research tooling, portfolio/adaptation intelligence, notebook validation, secret scanning, and MT5 forensic reconciliation.

> [!IMPORTANT]
> **Live execution remains quarantined.** The supported broker runtime is explicitly `mt5-demo`; it rejects non-demo accounts. Jaxter is research-only and cannot place or authorize orders.

## Repository layout

- `src/lilith/` — governed runtime, MT5 reconciliation, intelligence services, and Jaxter research engine.
- `dashboard_app.py` — unified Edith Command Centre entry point.
- `dashboard.py` — core operational dashboard.
- `dashboard_portfolio.py` — advisory portfolio-risk evidence.
- `dashboard_adaptation.py` — adaptation intelligence.
- `dashboard_jaxter.py` — isolated Jaxter strategy-assistant research interface.
- `scripts/diagnose_mt5_connection.py` — read-only Windows/MT5 connectivity diagnostic.
- `tests/` — unit, contract, reconciliation, Jaxter, and safety tests.
- `.github/workflows/` — Linux/Python CI, notebook/security checks, dashboard smoke test, and Windows contract validation.

## Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,mt5]"
```

Copy `.env.example` to an untracked local `.env` or configure the variables in the process environment. Never commit real credentials.

## Local Exness / MT5 binding

Set an explicit terminal executable when more than one MT5 installation exists:

```dotenv
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
EDITH_MT5_SYMBOL=XAUUSDm
```

The runtime fails closed when the path does not exist, MT5 initialization fails, login/server identity changes, the account is not demo, the terminal is disconnected, or algorithmic trading is disabled.

Run the read-only connectivity check before starting Edith:

```bash
python scripts/diagnose_mt5_connection.py
```

The diagnostic reports terminal identity, build, connection state, configured account/server match, symbol availability, bid/ask, spread, and `last_error()`. It contains no order submission calls.

## Running the Command Centre

```bash
python -m streamlit run dashboard_app.py
```

The unified application renders the operational dashboard followed by Portfolio Intelligence, Adaptation Intelligence, and Jaxter. Jaxter accepts validated OHLC CSV data and persists research evidence without modifying execution behavior.

## Running the governed MT5 demo runtime

Required controls:

```dotenv
LILITH_EXECUTION_MODE=mt5-demo
EDITH_MT5_CONFIRM_DEMO=YES
```

Start through the sanitized Edith notebook launcher or directly:

```bash
python -c "from lilith.reconciled_runtime import run_from_environment; run_from_environment()"
```

Only one runtime may be active for the configured data directory. Runtime status records include account identity, server, terminal identity, terminal build, connection state, telemetry, risk evidence, and reconciliation timestamps.

## Validation

```bash
python -m compileall -q src tests scripts dashboard.py dashboard_app.py dashboard_adaptation.py dashboard_jaxter.py dashboard_portfolio.py
python -m pytest --cov=lilith --cov-report=term-missing --cov-fail-under=65
python scripts/sanitize_notebook.py
```

GitHub Actions additionally validates Python 3.11/3.12, notebook safety, secret scanning, unified Streamlit startup, Windows compilation, and MT5 terminal-binding contracts. CI never connects to a broker and cannot prove local Exness availability; the local diagnostic is the required machine-level evidence.

## Operational approval matrix

| Activity | Status |
|---|---|
| Read-only inspection and analytics | Approved |
| Jaxter historical research | Approved |
| Controlled simulation | Approved |
| Governed MT5 demo operation | Requires green CI and successful local diagnostic |
| Paper/shadow-live promotion | Requires separate evidence review |
| Live capital execution | Not approved |

## Security and evidence policy

- Secrets must remain external to Git and notebook outputs.
- Runtime, broker, risk, and market-data failures must fail closed.
- Jaxter and advisory intelligence must not become execution dependencies.
- Historical evidence is additive and source-attributed.
- A PR description is not validation evidence; current green checks and reproducible command output are required.
- Strategy behavior changes require separate review from infrastructure and safety changes.

Lilith is experimental trading software. Nothing in this repository is financial advice or a guarantee of profitability.
