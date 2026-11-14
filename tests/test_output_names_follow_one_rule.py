"""Output names distinguish whole paths, bare file names, bundles, and libraries."""

from pathlib import Path

import pytest

from thomas.core.acceptance_contract import KIND_OUTPUT_PATH, build_contract
from thomas.core.acceptance_paths import named_paths


def _outputs(text: str, workspace: Path) -> list[str]:
    return [item.item_id for item in build_contract(text, workspace) if item.kind == KIND_OUTPUT_PATH]


@pytest.mark.parametrize(
    "name",
    [
        "document.querySelector",
        "window.localStorage",
        "Array.prototype",
        "pytest.mark.parametrize",
        "numpy.concatenate",
        "scene.background",
        "datetime.timedelta",
        "time.monotonic",
    ],
)
@pytest.mark.parametrize("prefix", ["", "Add "])
def test_backticked_code_names_are_not_files(tmp_path: Path, name: str, prefix: str) -> None:
    assert _outputs(f"{prefix}`{name}`", tmp_path) == []


@pytest.mark.parametrize(
    "name",
    [
        "logging.py",
        "window.js",
        "document.html",
        "np.py",
        "application.properties",
        "x.safetensors",
        "site.webmanifest",
        "App.entitlements",
        "Main.storyboard",
        "report.custom",
    ],
)
def test_backticked_file_names_are_outputs(tmp_path: Path, name: str) -> None:
    assert _outputs(f"Write `{name}`", tmp_path) == [f"output:{name}"]


@pytest.mark.parametrize(
    "name",
    [
        "config/application.properties",
        "models/x.safetensors",
        "site/site.webmanifest",
        "ios/App.entitlements",
        "ios/Main.storyboard",
        "config/custom.verylongextension",
    ],
)
@pytest.mark.parametrize("line", ["", ":42"])
def test_qualified_names_are_read_whole_without_line_numbers(tmp_path: Path, name: str, line: str) -> None:
    text = f"Write {name}{line}"
    assert named_paths(text) == [name]
    assert _outputs(text, tmp_path) == [f"output:{name}"]


@pytest.mark.parametrize("bundle", ["xcodeproj", "xcworkspace", "xcassets"])
def test_apple_bundle_is_read_whole_but_not_a_file(tmp_path: Path, bundle: str) -> None:
    name = f"ios/Example.{bundle}"
    assert named_paths(f"Use {name}:9") == [name]
    assert _outputs(f"Write {name}:9", tmp_path) == []
    assert _outputs(f"Write `Example.{bundle}`", tmp_path) == []


@pytest.mark.parametrize(
    "name",
    [
        "three.js",
        "node.js",
        "Next.js",
        "Vue.js",
        "socket.io",
        "jQuery.js",
        "React.js",
        "Angular.js",
        "Svelte.js",
        "Ember.js",
        "Alpine.js",
        "Leaflet.js",
        "Plotly.js",
        "Moment.js",
        "Preact.js",
        "Backbone.js",
        "p5.js",
        "pixi.js",
        "babylon.js",
        "phaser.js",
        "matter.js",
        "cannon.js",
        "tone.js",
        "lodash.js",
        "d3.js",
        "chart.js",
        "axios.js",
        "anime.js",
    ],
)
def test_backticked_library_names_are_not_missing_outputs(tmp_path: Path, name: str) -> None:
    assert _outputs(f"Use `{name}`", tmp_path) == []


def test_existing_library_file_is_still_recognized(tmp_path: Path) -> None:
    (tmp_path / "three.js").write_text("// local library", encoding="utf-8")
    assert named_paths("Use `three.js`", tmp_path) == ["three.js"]
    assert _outputs("Use `three.js`", tmp_path) == []  # existing files are inputs, not missing outputs


def test_a_long_unknown_bare_extension_is_not_a_file(tmp_path: Path) -> None:
    assert named_paths("Write `report.unknownextension`", tmp_path) == []
    assert _outputs("Write `report.unknownextension`", tmp_path) == []


def test_qualified_library_name_and_plain_file_remain_outputs(tmp_path: Path) -> None:
    assert _outputs("Write vendor/three.js and report.json", tmp_path) == [
        "output:vendor/three.js",
        "output:report.json",
    ]
