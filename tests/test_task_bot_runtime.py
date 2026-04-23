from __future__ import annotations

from pathlib import Path

from thomas.core import task_bot_runtime


def test_write_json_retries_permission_error_and_uses_unique_temp_files(tmp_path, monkeypatch):
    path = tmp_path / "executions-summary.json"
    attempts: list[str] = []
    original_replace = Path.replace

    def flaky_replace(self: Path, target: Path):
        attempts.append(self.name)
        if len(attempts) == 1:
            raise PermissionError("busy")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    task_bot_runtime._write_json(path, {"ok": True})

    assert len(attempts) == 2
    assert attempts[0] != attempts[1]
    assert path.read_text(encoding="utf-8").strip() == '{\n  "ok": true\n}'
