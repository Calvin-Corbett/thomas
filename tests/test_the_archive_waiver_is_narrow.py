"""The claim gates waive only the monthly board archive files: the whole path, digits for the month, exact case, lower-case .txt.

Nothing else under the archive folder is waived, including loose names that a "?" wildcard would have let through.
"""

from __future__ import annotations

import pytest
from scripts.forge.gates import workboard_agent_claim, workboard_changed_files

WAIVED = ["plans/thomas/archive/messages-2026-06.txt", "plans/thomas/archive/messages-2027-01.txt"]
NOT_WAIVED = [
    "plans/thomas/archive/notes.txt",
    "plans/thomas/archive/messages-2026-06.md",
    "plans/thomas/archive/messages-2026-6.txt",
    "plans/thomas/archive/sub/messages-2026-06.txt",
    "plans/thomas/archive/big.bin",
    "plans/thomas/other/messages-2026-06.txt",
    "plans/thomas/archive/messages-abcd-ef.txt",
    "plans/thomas/archive/messages-a/b/-cd.txt",
    "plans/thomas/archive/messages-x/y/-ab.txt",
    "plans/thomas/archive/messages-2026-10.TXT",
    "plans/thomas/archive/Messages-2026-10.txt",
    "plans/thomas/archive/messages-2026-06.txt/inner",
    "plans/thomas/archive/messages-2026-123.txt",
]


@pytest.mark.parametrize("path", WAIVED)
def test_the_monthly_archive_files_are_waived(path: str) -> None:
    assert workboard_changed_files._matches_ignore(path, workboard_changed_files.DEFAULT_IGNORE_PATTERNS)
    assert workboard_agent_claim._is_ignored_path(path, workboard_agent_claim.DEFAULT_STAGED_SCOPE_IGNORE)


@pytest.mark.parametrize("path", NOT_WAIVED)
def test_nothing_else_under_the_archive_folder_is_waived(path: str) -> None:
    assert not workboard_changed_files._matches_ignore(path, workboard_changed_files.DEFAULT_IGNORE_PATTERNS)
    assert not workboard_agent_claim._is_ignored_path(path, workboard_agent_claim.DEFAULT_STAGED_SCOPE_IGNORE)
