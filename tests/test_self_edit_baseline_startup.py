"""Existing startup configuration is trusted only at its exact source baseline."""

import subprocess

import pytest

from thomas.forge.anvil import forge_code_self_edit as isolation


@pytest.fixture
def startup_candidate(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "sitecustomize.py").write_text("import sys\nsys.dont_write_bytecode = True\n")
    (source / "feature.py").write_text("VALUE = 1\n")
    (source / "tests").mkdir()
    (source / "tests/test_feature.py").write_text(
        "# Regression for feature.py\nfrom feature import VALUE\ndef test_value():\n    assert VALUE == 2\n"
    )
    return source, tmp_path / "candidates"


def test_unchanged_baseline_startup_allows_real_verification(startup_candidate):
    source, parent = startup_candidate
    candidate = isolation.prepare_candidate(source, parent)
    (candidate.candidate_root / "feature.py").write_text("VALUE = 2\n")
    commands, uncovered = isolation.plan_candidate_checks(candidate, ["feature.py"])
    assert commands and not uncovered
    receipt = isolation.verify_candidate_checks(candidate, commands)
    assert receipt.checks_passed


@pytest.mark.parametrize("operation", ["add", "modify", "delete"])
def test_startup_hook_cannot_change(startup_candidate, operation):
    source, parent = startup_candidate
    if operation == "add":
        (source / "sitecustomize.py").unlink()
    candidate = isolation.prepare_candidate(source, parent)
    hook = candidate.candidate_root / "sitecustomize.py"
    if operation == "delete":
        hook.unlink()
    else:
        hook.write_text("raise SystemExit(0)\n")
    with pytest.raises(isolation.SelfEditSnapshotError):
        isolation.plan_candidate_checks(candidate, ["feature.py"])


def test_existing_fake_pytest_is_still_a_runner_shadow(startup_candidate):
    source, parent = startup_candidate
    (source / "pytest.py").write_text("raise SystemExit(0)\n")
    candidate = isolation.prepare_candidate(source, parent)
    with pytest.raises(isolation.SelfEditSnapshotError, match="shadows"):
        isolation.plan_candidate_checks(candidate, ["feature.py"])
