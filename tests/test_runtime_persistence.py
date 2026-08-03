import json
from pathlib import Path

from lilith.mt5_demo import write_json


def test_write_json_falls_back_when_replace_is_denied(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "runtime_status.json"
    path.write_text("{}", encoding="utf-8")

    original_replace = Path.replace

    def fail_replace(self: Path, target: Path) -> None:
        if self.name == "runtime_status.json.tmp" and target == path:
            raise PermissionError("access denied")
        original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    write_json(path, {"heartbeat_at": "2026-01-01T00:00:00Z"})

    assert json.loads(path.read_text(encoding="utf-8"))["heartbeat_at"] == "2026-01-01T00:00:00Z"
    assert not (tmp_path / "runtime_status.json.tmp").exists()
