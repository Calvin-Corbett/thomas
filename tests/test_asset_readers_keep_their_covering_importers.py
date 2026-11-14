"""Asset-reading helpers and fixture scopes retain their covering tests."""

import pytest

from thomas.server.proof import selection


@pytest.mark.parametrize("cap", [0, 1, 360])
@pytest.mark.parametrize("reader", ["tests/support.py", "pkg/assets.py"])
def test_asset_reader_importers_remain_in_the_execution_set(cap: int, reader: str) -> None:
    module = reader[:-3].replace("/", ".")
    texts = {
        reader: 'value = read("browser_search.css")',
        "tests/test_consumer.py": f"from {module} import value",
        "tests/sub/conftest.py": f"from {module} import value",
        "tests/sub/test_fixture.py": "def test_fixture(): pass",
        "tests/other/test_unrelated.py": "def test_unrelated(): pass",
    }
    selected = selection.select_from(texts, ["thomas/server/web/css/browser_search.css"], cap=cap)
    assert set(selected.files + selected.left_out) == {
        "tests/test_consumer.py",
        "tests/sub/test_fixture.py",
    }


def test_direct_asset_reading_conftest_selects_only_its_scope() -> None:
    texts = {
        "tests/ui/conftest.py": 'asset = read("browser_search.css")',
        "tests/ui/test_page.py": "def test_page(): pass",
        "tests/other/test_unrelated.py": "def test_unrelated(): pass",
    }
    assert selection.select_from(texts, ["web/browser_search.css"]).files == ("tests/ui/test_page.py",)
