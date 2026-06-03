"""Tests for the post-write import-probe injection guard in agent verification.

``verify_after_tool`` used to run ``python -c f"import {module_name}"`` where
``module_name`` derived from a model-controlled filename, so a stem containing
``;`` injected a second statement that the interpreter would execute. The probe
now (a) only runs for a valid dotted module name and (b) passes the name as argv
data to ``importlib.import_module`` instead of splicing it into source.
"""

from __future__ import annotations

import asyncio

from thomas.agent.verification import _MODULE_NAME_RE, verify_after_tool


def test_module_name_regex_accepts_valid_modules():
    for good in ["pkg.mod", "a.b.c", "_private.mod_2", "thomas.agent.verification", "x"]:
        assert _MODULE_NAME_RE.fullmatch(good), good


def test_module_name_regex_rejects_injection_and_junk():
    for bad in [
        "pkg.x;import os",
        "x;open('p','w').close()",
        "a b",
        ".pkg.mod",
        "pkg.",
        "pkg..m",
        "1mod",
        "",
        "pkg.mod, os",
    ]:
        assert _MODULE_NAME_RE.fullmatch(bad) is None, bad


def test_verify_after_tool_does_not_execute_injected_filename(tmp_path):
    # A package whose member filename embeds a second statement that, under the
    # old f-string probe, would create a sentinel file when "imported".
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    sentinel = tmp_path / "PWNED"
    evil = pkg / "x;open('PWNED','w').close().py"
    evil.write_text("# benign\n", encoding="utf-8")

    issues = asyncio.run(verify_after_tool("fs.write", {"path": str(evil)}, True, sandbox_root=str(tmp_path)))
    assert isinstance(issues, list)
    assert not sentinel.exists()  # the injected statement must never run
