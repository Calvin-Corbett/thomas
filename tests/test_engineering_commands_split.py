"""The git analysis and project stats tools moved; every old import still works."""

from __future__ import annotations

from thomas.tools import engineering, engineering_commands


def test_moved_tools_are_reexported_from_engineering() -> None:
    assert engineering.GitAnalysisTool is engineering_commands.GitAnalysisTool
    assert engineering.ProjectStatsTool is engineering_commands.ProjectStatsTool


def test_moved_tools_keep_their_names() -> None:
    assert engineering_commands.GitAnalysisTool.name == "eng.git_analysis"
    assert engineering_commands.ProjectStatsTool.name == "eng.project_stats"
