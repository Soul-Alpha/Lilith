from __future__ import annotations

import os

import pytest

from lilith.mt5_demo import RuntimeLock
from lilith.reconciled_runtime import OwnershipAwareRuntimeLock


def test_rejected_runtime_cannot_release_another_runtime_lock(tmp_path) -> None:
    path = tmp_path / "edith_mt5.lock"
    first = OwnershipAwareRuntimeLock(RuntimeLock(path))
    second = OwnershipAwareRuntimeLock(RuntimeLock(path))

    first.acquire()
    try:
        with pytest.raises(RuntimeError) as captured:
            second.acquire()

        message = str(captured.value)
        assert "Another Edith runtime appears active" in message
        assert f"pid={os.getpid()}" in message
        assert "Stop the previous Edith notebook kernel/process" in message
        assert second.acquired is False

        # MT5DemoRuntime.run() calls release() in a finalizer even when connect
        # failed. A rejected runtime must not remove the active owner's lock.
        second.release()
        assert path.exists()
    finally:
        first.release()

    assert not path.exists()


def test_owned_runtime_lock_release_is_idempotent(tmp_path) -> None:
    path = tmp_path / "edith_mt5.lock"
    guarded = OwnershipAwareRuntimeLock(RuntimeLock(path))

    guarded.acquire()
    assert guarded.acquired is True
    assert path.exists()

    guarded.release()
    guarded.release()

    assert guarded.acquired is False
    assert not path.exists()
