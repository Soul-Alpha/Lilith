from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def configured_terminal_path() -> Path | None:
    """Return the explicitly configured MT5 terminal executable, when supplied."""
    value = os.getenv("MT5_TERMINAL_PATH", "").strip().strip('"')
    return Path(value).expanduser() if value else None


def initialize_terminal(mt5: Any) -> Path | None:
    """Initialize MT5 against the configured terminal and fail closed on bad paths."""
    terminal_path = configured_terminal_path()
    if terminal_path is not None:
        if not terminal_path.is_file():
            raise RuntimeError(f"Configured MT5 terminal does not exist: {terminal_path}")
        initialized = mt5.initialize(path=str(terminal_path))
    else:
        initialized = mt5.initialize()
    if not initialized:
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    return terminal_path


def terminal_identity(terminal: Any, terminal_path: Path | None) -> dict[str, object]:
    """Build non-secret terminal telemetry suitable for runtime status and diagnostics."""
    return {
        "terminal_path": None if terminal_path is None else str(terminal_path),
        "terminal_name": str(getattr(terminal, "name", "")),
        "terminal_company": str(getattr(terminal, "company", "")),
        "terminal_build": int(getattr(terminal, "build", 0) or 0),
        "terminal_connected": bool(getattr(terminal, "connected", False)),
        "terminal_trade_allowed": bool(getattr(terminal, "trade_allowed", False)),
    }
