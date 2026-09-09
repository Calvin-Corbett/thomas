"""git tools outside a repository: one clear refusal, not a fatal the model retries.

TB-4.0 run 3 (bun-sourcemap-leak, 2026-09-04): git.status in /app (no .git)
returned ``fatal: not a git repository`` three times and the loop's stability
guard then killed a 128-iteration run. The tool must say where it looked and
what to use instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.tools.git import GitStatusTool


def test_git_status_outside_a_repo_names_the_folder_and_the_alternative(tmp_path: Path) -> None:
    result = asyncio.run(GitStatusTool(tmp_path).execute({}))

    assert result.ok is False
    assert str(tmp_path.resolve()) in str(result.error)
    assert "not a git repository" in str(result.error)
    assert "fs.list_dir" in str(result.error)
    assert "git" in str(result.error)
