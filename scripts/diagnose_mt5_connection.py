from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from lilith.mt5_terminal import initialize_terminal, terminal_identity


def main() -> int:
    """Run a read-only MT5/Exness connectivity diagnostic. No orders are created."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print(json.dumps({"status": "error", "message": "Install MT5 support with: python -m pip install -e .[mt5]"}, indent=2))
        return 2

    login_text = os.getenv("MT5_LOGIN", "").strip()
    password = os.getenv("MT5_PASSWORD", "").strip()
    server = os.getenv("MT5_SERVER", "").strip()
    symbol = os.getenv("EDITH_MT5_SYMBOL", "XAUUSDm").strip()
    required = [name for name, value in (("MT5_LOGIN", login_text), ("MT5_PASSWORD", password), ("MT5_SERVER", server)) if not value]
    if required:
        print(json.dumps({"status": "error", "message": f"Missing required environment variables: {required}"}, indent=2))
        return 2

    report: dict[str, object] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only-diagnostic",
        "symbol": symbol,
        "server_expected": server,
    }
    try:
        terminal_path = initialize_terminal(mt5)
        if not mt5.login(int(login_text), password=password, server=server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError(f"MT5 account/terminal info unavailable: {mt5.last_error()}")
        selected = bool(mt5.symbol_select(symbol, True))
        info = mt5.symbol_info(symbol) if selected else None
        tick = mt5.symbol_info_tick(symbol) if selected else None
        report.update(terminal_identity(terminal, terminal_path))
        report.update({
            "status": "ok" if selected and info is not None and tick is not None else "degraded",
            "account_login": int(account.login),
            "account_server": str(account.server),
            "account_trade_mode": int(account.trade_mode),
            "account_balance": float(account.balance),
            "account_equity": float(account.equity),
            "symbol_selected": selected,
            "symbol_visible": bool(getattr(info, "visible", False)) if info is not None else False,
            "bid": None if tick is None else float(tick.bid),
            "ask": None if tick is None else float(tick.ask),
            "spread_points": None if tick is None or info is None or float(info.point) <= 0 else (float(tick.ask) - float(tick.bid)) / float(info.point),
            "last_error": mt5.last_error(),
        })
        if int(account.login) != int(login_text) or str(account.server) != server:
            report["status"] = "error"
            report["message"] = "Connected terminal identity does not match configured account/server."
            print(json.dumps(report, indent=2, sort_keys=True))
            return 1
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "ok" else 1
    except Exception as exc:
        report.update({"status": "error", "message": str(exc), "last_error": mt5.last_error()})
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
