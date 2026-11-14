"""A changed file whose name many files share selects the tests that read that one, not every file of that name.

A test reads a page or a document by its name, so a changed file that is not Python selects the tests that name it.
On 2026-11-10 a change of 28 files, five new plugin modules with their tests and some documents, was checked with
235 test files for 25 minutes on 16 processes: 229 of them were chosen by ``extensions/README.md`` alone. The checkout
holds 50 files called ``README.md`` and 131 test files say that name. That check and ten before it used about 124
processor-hours in two days.

A name only one file has still selects by the name. A name several files share selects a test only when the test also
names the folder the changed one is in.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from thomas.server.proof import selection

ARCHITECTURE = {"tests/test_architecture.py": "def test_sizes() -> None:\n    pass\n"}
READS_ANOTHER_README = (
    "from pathlib import Path\n\n"
    "def test_docs() -> None:\n"
    "    assert 'Install' in (Path('docs') / 'README.md').read_text()\n"
)
READS_THIS_README = (
    "from pathlib import Path\n\n"
    "def test_extensions() -> None:\n"
    "    assert 'Standard' in (Path('extensions') / 'README.md').read_text()\n"
)
TEXTS = {
    **ARCHITECTURE,
    "tests/test_docs.py": READS_ANOTHER_README,
    "tests/test_extensions.py": READS_THIS_README,
}


def test_a_shared_name_selects_only_the_tests_that_name_its_folder_too() -> None:
    chosen = selection.select_from(TEXTS, ["extensions/README.md"], shared_names={"README.md"}).files

    assert "tests/test_extensions.py" in chosen
    assert "tests/test_docs.py" not in chosen


def test_a_name_only_one_file_has_still_selects_by_the_name() -> None:
    reads = "def test_p() -> None:\n    assert open('settings.plugins-panel.js').read()\n"
    texts = {**ARCHITECTURE, "tests/test_panel.py": reads}

    chosen = selection.select_from(
        texts, ["thomas/server/web/settings.plugins-panel.js"], shared_names={"README.md"}
    ).files

    assert "tests/test_panel.py" in chosen


def test_a_shared_name_at_the_top_of_the_checkout_selects_by_the_name() -> None:
    """There is no folder to ask for: the README beside pyproject.toml is named bare by the tests that read it."""
    chosen = selection.select_from(TEXTS, ["README.md"], shared_names={"README.md"}).files

    assert "tests/test_docs.py" in chosen and "tests/test_extensions.py" in chosen


def test_a_helper_that_names_another_readme_does_not_pull_in_its_importers() -> None:
    helper = "from pathlib import Path\n\nDOCS = Path('docs') / 'README.md'\n"
    user = "from tests.docs_helper import DOCS\n\ndef test_d() -> None:\n    assert DOCS\n"
    texts = {**ARCHITECTURE, "tests/docs_helper.py": helper, "tests/test_uses_helper.py": user}

    chosen = selection.select_from(texts, ["extensions/README.md"], shared_names={"README.md"}).files

    assert "tests/test_uses_helper.py" not in chosen


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


def test_select_learns_which_names_are_shared_from_the_checkout_itself(tmp_path: Path) -> None:
    for rel, text in {**TEXTS, "docs/README.md": "Install\n", "extensions/README.md": "Standard\n"}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")

    chosen = selection.select(tmp_path, ["extensions/README.md"]).files

    assert "tests/test_extensions.py" in chosen
    assert "tests/test_docs.py" not in chosen


def test_a_folder_that_is_not_a_git_checkout_selects_by_the_name_as_before(tmp_path: Path) -> None:
    for rel, text in TEXTS.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    chosen = selection.select(tmp_path, ["extensions/README.md"]).files

    assert "tests/test_docs.py" in chosen and "tests/test_extensions.py" in chosen
