from pathlib import Path

from scripts.forge.publish import private_markers

ROOT = Path(__file__).resolve().parent.parent


def test_public_exports_cover_publish_marker_contract() -> None:
    assert private_markers.__all__ == (
        "ACCEPTED_PRIVATE_MARKER_LINES",
        "DEFAULT_MAX_SCAN_BYTES",
        "MARKER_REFERENCE_PATHS",
        "PRIVATE_MARKER",
        "is_marker_reference_path",
        "line_has_private_marker",
        "path_has_private_marker",
    )


def test_line_has_private_marker_accepts_documented_whole_line_forms() -> None:
    for marker_line in private_markers.ACCEPTED_PRIVATE_MARKER_LINES:
        assert private_markers.line_has_private_marker(marker_line)
        assert private_markers.line_has_private_marker(f"  {marker_line}  ")
        assert private_markers.line_has_private_marker(f"\t{marker_line}\t")
        assert private_markers.line_has_private_marker(f"{marker_line}\r\n")


def test_line_has_private_marker_rejects_embedded_or_incomplete_markers() -> None:
    for rejected in (
        "",
        "THOMAS_TRASH",
        "thomas_private",
        "# thomas_private",
        "// Thomas_Private",
        "THOMAS_PRIVATE because this file is local-only",
        "prefix THOMAS_PRIVATE",
        "# THOMAS_PRIVATE because this file is local-only",
        "// THOMAS_PRIVATE because this file is local-only",
        "/* THOMAS_PRIVATE */ trailing text",
        "<!-- THOMAS_PRIVATE --> trailing text",
        "THOMAS_PRIVATE.md",
    ):
        assert not private_markers.line_has_private_marker(rejected)


def test_marker_reference_paths_exist_and_document_private_marker() -> None:
    assert isinstance(private_markers.MARKER_REFERENCE_PATHS, frozenset)
    assert private_markers.MARKER_REFERENCE_PATHS

    for reference_path in private_markers.MARKER_REFERENCE_PATHS:
        path = ROOT / reference_path

        assert path.is_file()
        assert private_markers.PRIVATE_MARKER in path.read_text(encoding="utf-8")


def test_is_marker_reference_path_normalizes_slashes_and_whitespace() -> None:
    assert private_markers.is_marker_reference_path("docs/trash_marker.md")
    assert private_markers.is_marker_reference_path("docs//trash_marker.md")
    assert private_markers.is_marker_reference_path(r" docs\trash_marker.md ")
    assert private_markers.is_marker_reference_path(r".\docs\trash_marker.md")
    assert private_markers.is_marker_reference_path(r".\.\docs\trash_marker.md")
    assert private_markers.is_marker_reference_path("./docs/trash_marker.md")
    assert private_markers.is_marker_reference_path("././docs/trash_marker.md")
    assert private_markers.is_marker_reference_path(Path("docs") / "trash_marker.md")

    assert not private_markers.is_marker_reference_path("")
    assert not private_markers.is_marker_reference_path("docs/other_marker_doc.md")


def test_path_has_private_marker_uses_shared_reference_exemptions(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    marker_reference = docs / "trash_marker.md"
    marker_reference.write_text("THOMAS_PRIVATE\n", encoding="utf-8")
    local_only = docs / "local_only.md"
    local_only.write_text("THOMAS_PRIVATE\n", encoding="utf-8")
    public = docs / "public.md"
    public.write_text("This public doc mentions THOMAS_PRIVATE in prose.\n", encoding="utf-8")

    assert not private_markers.path_has_private_marker(
        tmp_path,
        r"./docs\trash_marker.md",
        max_scan_bytes=100,
    )
    assert not private_markers.path_has_private_marker(
        tmp_path,
        r".\docs\trash_marker.md",
        max_scan_bytes=100,
    )
    assert not private_markers.path_has_private_marker(tmp_path, marker_reference, max_scan_bytes=100)
    assert private_markers.path_has_private_marker(tmp_path, "docs/local_only.md", max_scan_bytes=100)
    assert private_markers.path_has_private_marker(tmp_path, Path("docs") / "local_only.md", max_scan_bytes=100)
    assert not private_markers.path_has_private_marker(tmp_path, "docs/public.md", max_scan_bytes=100)
    assert not private_markers.path_has_private_marker(tmp_path, "docs/missing.md", max_scan_bytes=100)


def test_path_has_private_marker_uses_default_scan_limit(tmp_path: Path) -> None:
    local_only = tmp_path / "local_only.md"
    local_only.write_text("THOMAS_PRIVATE\n", encoding="utf-8")

    assert private_markers.DEFAULT_MAX_SCAN_BYTES == 2_000_000
    assert private_markers.path_has_private_marker(tmp_path, "local_only.md")


def test_path_has_private_marker_skips_files_over_scan_limit(tmp_path: Path) -> None:
    local_only = tmp_path / "local_only.md"
    local_only.write_text("THOMAS_PRIVATE\n", encoding="utf-8")

    assert not private_markers.path_has_private_marker(tmp_path, "local_only.md", max_scan_bytes=1)


def test_path_has_private_marker_scans_file_at_exact_limit(tmp_path: Path) -> None:
    local_only = tmp_path / "local_only.md"
    local_only.write_text("THOMAS_PRIVATE\n", encoding="utf-8")

    assert private_markers.path_has_private_marker(
        tmp_path,
        "local_only.md",
        max_scan_bytes=local_only.stat().st_size,
    )


def test_path_has_private_marker_refuses_paths_outside_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("THOMAS_PRIVATE\n", encoding="utf-8")

    assert not private_markers.path_has_private_marker(repo, "../outside.md", max_scan_bytes=100)
    assert not private_markers.path_has_private_marker(repo, outside, max_scan_bytes=100)


def test_path_has_private_marker_skips_directories(tmp_path: Path) -> None:
    private_dir = tmp_path / "THOMAS_PRIVATE"
    private_dir.mkdir()

    assert not private_markers.path_has_private_marker(tmp_path, "THOMAS_PRIVATE", max_scan_bytes=100)


def test_path_has_private_marker_ignores_invalid_utf8_bytes(tmp_path: Path) -> None:
    local_only = tmp_path / "local_only.md"
    local_only.write_bytes(b"\xff\xfe\nTHOMAS_PRIVATE\n")

    assert private_markers.path_has_private_marker(tmp_path, "local_only.md", max_scan_bytes=100)
