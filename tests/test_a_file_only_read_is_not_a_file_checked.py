"""The static verifier must not count a file it only decoded as a file it checked.

`_VERIFY_SRC` in build_verify.py has a real arm per extension it understands --
`py_compile` for .py, `node --check` for .js, an HTML parse, a JSON parse and so
on -- and a fallback arm for everything else that does nothing but
`raw.decode('utf-8')`. That fallback passes for any text file and cannot fail for
a reason anyone cares about, yet whole languages landed in it: .ts, .go, .rs,
.sh, .sql, .md.

Those files were being counted in `STATIC_VERIFY_OK: N files checked`, so a run
that produced one syntactically broken TypeScript file reported
"1 files checked" and a passing validation. Measured before the change: a file
containing `const x: number = ;;; broken(((` verified clean.

The per-file lines were always honest -- `compiled` / `parsed` / `checked` for the
real arms and `read` for the fallback -- so only the total lied. This is the same
shape as a skipped browser smoke reading as a pass: a check that could not have
found anything, reported as one that found nothing wrong.

Deliberately still exits 0. Reading a text asset is a weak check, not a failure,
and failing the run would break every task that legitimately emits a .md
alongside its code. The count is what was wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

BROKEN_TS = "const x: number = ;;; broken(((\n"


def _verify(tmp_path: Path, files: dict[str, str]) -> str:
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    events: list[dict] = []
    ok, rc, summary = verify_python_changes(tmp_path, list(files), events.append)
    assert ok is True and rc == 0, f"expected a clean exit, got ok={ok} rc={rc}: {summary}"
    line = next((s for s in summary.splitlines() if "STATIC_VERIFY_OK" in s), "")
    assert line, f"no STATIC_VERIFY_OK line in: {summary!r}"
    return line.strip()


def test_a_language_with_no_real_check_is_reported_as_read_only(tmp_path) -> None:
    """The regression. This TypeScript does not parse in any dialect."""
    line = _verify(tmp_path, {"app.ts": BROKEN_TS})

    assert "0 files checked" in line, f"a file nothing checked was counted as checked: {line}"
    assert "1 read only" in line, line


def test_a_file_with_a_real_check_is_still_counted_as_checked(tmp_path) -> None:
    """The control. If everything became "read only" the distinction would carry
    no information, and .py must keep counting as genuinely checked."""
    line = _verify(tmp_path, {"tool.py": "VALUE = 1 + 1\n"})

    assert "1 files checked" in line, line
    assert "read only" not in line, f"a byte-compiled file was demoted to read-only: {line}"


def test_a_mixed_change_separates_the_two(tmp_path) -> None:
    line = _verify(tmp_path, {"tool.py": "VALUE = 2\n", "notes.md": "# hello\n"})

    assert "1 files checked" in line, line
    assert "1 read only" in line, line


def test_a_broken_python_file_still_fails_the_run(tmp_path) -> None:
    """Guards the direction that matters most: making the count honest must not
    have softened a real syntax error into a pass."""
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    events: list[dict] = []

    ok, rc, summary = verify_python_changes(tmp_path, ["bad.py"], events.append)

    assert ok is False and rc != 0, f"a syntax error verified clean: {summary!r}"
    assert "STATIC_VERIFY_OK" not in summary


@pytest.mark.parametrize("extension", [".ts", ".go", ".rs", ".sh", ".sql"])
def test_every_unhandled_language_lands_in_the_read_only_count(tmp_path, extension) -> None:
    """Named explicitly so adding a real check for one of these is a deliberate
    act that turns a test red, rather than a silent change in what "checked"
    means."""
    line = _verify(tmp_path, {f"thing{extension}": "this is not valid in any of these\n"})

    assert "0 files checked" in line, f"{extension} was counted as checked: {line}"
    assert "1 read only" in line, line
