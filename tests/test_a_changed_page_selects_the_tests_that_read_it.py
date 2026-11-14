"""A changed page, script or style sheet selects the tests that read it.

The check before your card runs the tests that import a changed module. A page has no importers: a test reads it by
its name. On 2026-09-27 a web-size change moved the Model Setup markup out of ``thomas/server/web/index.html`` and
broke ``tests/test_web_chat_surface_contract.py``, which reads that file; the check never ran it, and the card said
"no failure this change causes". A test that names a changed file that is not Python is chosen too, after every real
importer, so the cap still keeps the importers first. A Python module is still chosen by what imports it, never by a
word.
"""

from __future__ import annotations

from thomas.server.proof import selection

ARCHITECTURE = {"tests/test_architecture.py": "def test_sizes() -> None:\n    pass\n"}
READS_THE_PAGE = (
    "from pathlib import Path\n\n"
    "def test_setup() -> None:\n"
    "    assert 'setupProviderPickerBtn' in (Path('thomas/server/web') / 'index.html').read_text()\n"
)


def test_a_test_that_reads_a_changed_page_is_chosen() -> None:
    texts = {
        **ARCHITECTURE,
        "tests/test_surface.py": READS_THE_PAGE,
        "tests/test_other.py": "def test_y():\n    pass\n",
    }

    chosen = selection.select_from(texts, ["thomas/server/web/index.html"]).files

    assert "tests/test_surface.py" in chosen
    assert "tests/test_other.py" not in chosen


def test_real_importers_come_before_a_test_that_only_names_a_page() -> None:
    importer = "from thomas.core import widget\n\ndef test_w() -> None:\n    assert widget\n"
    texts = {**ARCHITECTURE, "tests/test_surface.py": READS_THE_PAGE, "tests/test_widget.py": importer}

    chosen = selection.select_from(texts, ["thomas/server/web/index.html", "thomas/core/widget.py"], cap=2).files

    assert chosen == ("tests/test_architecture.py", "tests/test_widget.py")
