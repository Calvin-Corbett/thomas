from __future__ import annotations

from pathlib import Path

import pytest

from thomas.bootdoctor.__main__ import (
    BootDoctorPathPolicy,
    RestrictedTool,
    _extract_patch_targets,
)
from thomas.tools.base import Tool, ToolResult


class _DummyWriteTool(Tool):
    name = "fs.write_file"
    category = "filesystem"
    description = "dummy write"
    parameters = {"type": "object"}

    async def execute(self, args):
        return ToolResult(ok=True, data=args.get("path", ""))


def _seed_boot_layout(root: Path) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "thomas" / "bootdoctor").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "boot_doctor").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "run-ui.ps1").write_text("# test\n", encoding="utf-8")


def test_bootdoctor_path_policy_scopes(tmp_path: Path) -> None:
    _seed_boot_layout(tmp_path)
    policy = BootDoctorPathPolicy(tmp_path)

    assert policy.is_read_allowed((tmp_path / "scripts" / "run-ui.ps1").resolve())
    assert policy.is_write_allowed((tmp_path / "scripts" / "run-ui.ps1").resolve())
    assert not policy.is_write_allowed((tmp_path / "README.md").resolve())


@pytest.mark.asyncio
async def test_restricted_tool_blocks_out_of_scope_write(tmp_path: Path) -> None:
    _seed_boot_layout(tmp_path)
    policy = BootDoctorPathPolicy(tmp_path)
    guarded = RestrictedTool(_DummyWriteTool(), policy)

    blocked = await guarded.execute({"path": "README.md", "content": "x"})
    assert not blocked.ok
    assert "blocked write outside boot scope" in str(blocked.error or "")

    allowed = await guarded.execute({"path": "scripts/run-ui.ps1", "content": "x"})
    assert allowed.ok


def test_extract_patch_targets_handles_git_prefixes() -> None:
    patch = "--- a/scripts/run-ui.ps1\n" "+++ b/scripts/run-ui.ps1\n" "@@ -1,1 +1,1 @@\n" "-old\n" "+new\n"
    assert _extract_patch_targets(patch) == ["scripts/run-ui.ps1"]
