"""A green copy writes its ~7,000 files with parallel workers: on Windows that took the checkout from 5-8s to under 3s."""

from pathlib import Path

import pytest

from tests.ratchet_support import make_repo
from thomas.server import green_checkout


def test_the_green_checkout_asks_git_for_parallel_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    seen: list[list[str]] = []
    real = green_checkout._run

    def spy(args, *, cwd):
        seen.append(list(args))
        return real(args, cwd=cwd)

    monkeypatch.setattr(green_checkout, "_run", spy)
    green = green_checkout.create_green(repo, "parallel-copy-test")
    checkouts = [args for args in seen if "checkout" in args]
    assert len(checkouts) == 1
    assert "checkout.workers=8" in checkouts[0]
    assert "checkout.thresholdForParallelism=100" in checkouts[0]
    # The copy is the same tree: nothing is modified or missing against the commit it was made from.
    status = green_checkout.git(green, "status", "--porcelain")
    assert status.returncode == 0 and status.stdout.strip() == ""
    green_checkout.remove_green(green)
