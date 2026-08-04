from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lilith.mt5_terminal import configured_terminal_path, initialize_terminal, terminal_identity


class FakeMT5:
    def __init__(self, initialized: bool = True) -> None:
        self.initialized = initialized
        self.calls: list[dict[str, object]] = []

    def initialize(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return self.initialized

    @staticmethod
    def last_error() -> tuple[int, str]:
        return (-10001, "IPC send failed")


def test_configured_terminal_path_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MT5_TERMINAL_PATH", raising=False)
    assert configured_terminal_path() is None


def test_initialize_uses_explicit_terminal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "terminal64.exe"
    executable.write_bytes(b"")
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(executable))
    mt5 = FakeMT5()
    assert initialize_terminal(mt5) == executable
    assert mt5.calls == [{"path": str(executable)}]


def test_initialize_rejects_missing_terminal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MT5_TERMINAL_PATH", str(tmp_path / "missing.exe"))
    with pytest.raises(RuntimeError, match="does not exist"):
        initialize_terminal(FakeMT5())


def test_initialize_surfaces_ipc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MT5_TERMINAL_PATH", raising=False)
    with pytest.raises(RuntimeError, match="IPC send failed"):
        initialize_terminal(FakeMT5(initialized=False))


def test_terminal_identity_contains_non_secret_runtime_fields() -> None:
    terminal = SimpleNamespace(name="MetaTrader 5", company="Exness", build=5000, connected=True, trade_allowed=True)
    identity = terminal_identity(terminal, Path("C:/Exness/terminal64.exe"))
    assert identity["terminal_company"] == "Exness"
    assert identity["terminal_connected"] is True
    assert "password" not in identity
