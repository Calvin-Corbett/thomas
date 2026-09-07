from __future__ import annotations

from pathlib import Path

from thomas.core.praxis_scaffold import ensure_praxis
from thomas.server.routes.local_projects_boards import boards_index


def test_index_lists_the_users_board_first_and_a_board_per_registry_entry(tmp_path: Path) -> None:
    data = tmp_path / "ThomasData"
    repo = tmp_path / "someones-app"
    pdf_job = tmp_path / "ThomasData" / "workspaces" / "exec-7"
    for folder in (data, repo, pdf_job):
        folder.mkdir(parents=True)
    ensure_praxis(repo)  # the repo has had a task; the deliverable has not

    index = boards_index(
        [
            {"id": "p1", "name": "someones-app", "kind": "node_app", "root_path": str(repo)},
            {"id": "g1", "name": "a pdf", "kind": "generated", "root_path": str(pdf_job)},
            {"id": "x", "name": "no root", "kind": "static_site", "root_path": ""},
        ],
        user_root=data,
    )

    assert index["user_board"]["board"] == str(data / "plans" / "thomasdata" / "WORKBOARD.md")
    assert [row["id"] for row in index["projects"]] == ["p1", "g1"]
    assert index["projects"][0]["exists"] is True
    assert index["projects"][1]["exists"] is False
    assert index["projects"][1]["board"] == str(pdf_job / "plans" / "exec-7" / "WORKBOARD.md")
