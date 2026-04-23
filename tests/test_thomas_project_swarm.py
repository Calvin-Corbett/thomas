from __future__ import annotations

import json
from pathlib import Path

from scripts import thomas_project_swarm

from thomas.demo.project_swarm_contracts import evaluate_baseline_product


def _workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- none\n\n"
        "## Active Tasks\n\n"
        "- none\n\n"
        "## Issues / Blockers\n\n"
        "- none\n\n"
        "## Up For Grabs\n\n"
        "- none\n\n"
        "## Agent Message Traffic\n\n"
        "- none\n",
        encoding="utf-8",
    )
    return path


def test_mock_project_swarm_builds_integrated_pacman(tmp_path: Path, capsys) -> None:
    rc = thomas_project_swarm.run(
        [
            "--run-id",
            "project-swarm-test",
            "--lanes",
            "5",
            "--max-concurrency",
            "5",
            "--repo-root",
            str(tmp_path),
            "--workboard",
            str(_workboard(tmp_path)),
            "--mock",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    root = Path(payload["thomas"]["root"])

    assert rc == 0
    assert payload["thomas"]["passed"] == 1
    assert payload["thomas"]["evaluator"]["failed"] == 0
    assert payload["thomas"]["lines"]["nonblank"] > 0
    assert (root / "product" / "src" / "game.mjs").exists()
    assert len(list((root / "product" / "src" / "modules").glob("lane-*.mjs"))) == 5


def test_baseline_evaluator_requires_pacman_game_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "index.html").write_text("<canvas></canvas>", encoding="utf-8")
    (tmp_path / "src" / "styles.css").write_text("canvas{display:block}", encoding="utf-8")
    (tmp_path / "src" / "game.mjs").write_text(
        "addEventListener('keydown',()=>{}); const ghosts=[]; const pellets=[]; "
        "let power = true; requestAnimationFrame(()=>{});",
        encoding="utf-8",
    )

    result = evaluate_baseline_product(tmp_path)

    assert result["failed"] == 0
