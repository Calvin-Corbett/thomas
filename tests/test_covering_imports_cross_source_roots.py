"""An importer outside the changed source's top-level folder is followed when its text is passed in.

``select`` reads only ``tests/`` (2026-10-27: reading the whole checkout made one selection take 20 to 83 minutes);
``select_from`` still follows a production module in another source root that a caller passes.
"""

from thomas.server.proof import selection

SOURCES = {
    "thomas/value.py": "value = 1",
    "extensions/bridge.py": "from thomas.value import value",
    "tests/test_bridge.py": "from extensions.bridge import value",
    "tests/test_unrelated.py": "def test_other(): pass",
}


def test_importer_closure_reads_other_source_roots():
    result = selection.select_from(SOURCES, ["thomas/value.py"])
    assert result.files == ("tests/test_bridge.py",)
    assert not result.left_out


def test_a_checkout_is_read_only_under_tests(tmp_path):
    for rel, text in {**SOURCES, "node_modules/vendor/test_hidden.py": "from thomas.value import value"}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert selection.select(tmp_path, ["thomas/value.py"]).files == ()
