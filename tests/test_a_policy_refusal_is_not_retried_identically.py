"""A file-access policy refusal is deterministic — retrying the identical call is waste.

Measured (gauntlet g-desktopfile, live 2026-08-05): after the file-access
ladder refused a Desktop write, the worker retried the IDENTICAL write six
seconds later. Policy refusals are not transient: the same call gets the same
refusal every time.

Two sight-level protections, no gate:

* the tool result handed back to the model gains a recovery note naming the
  refusal as deterministic policy, telling it not to repeat the identical call
  and to carry the refusal's remedy to the user instead;
* the existing retry-same-signature tracker counts a policy refusal as a
  stronger signal, so the loop's stability stop (>= 3) fires on the SECOND
  identical attempt instead of the third — while a DIFFERENT path attempt is a
  different signature and starts fresh, exactly as before.
"""

import tempfile
import unittest
from pathlib import Path

from thomas.agent.loop_tool_protocol import _record_failed_tool, _tool_result_with_recovery
from thomas.core.file_access import WORKSPACE, authorize_write


def _refusal_for(target: Path, workspace: Path) -> str:
    allowed, reason = authorize_write(WORKSPACE, target, workspace_root=workspace)
    assert not allowed, "test setup: the write must be refused"
    return reason


class _RefusalFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name).resolve()
        self.workspace = tmp / "ws"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.desktop_target = tmp / "Desktop" / "hello.txt"
        self.refusal = _refusal_for(self.desktop_target, self.workspace)


class TestRecoveryNoteNamesDeterminism(_RefusalFixture):
    def test_refusal_result_gains_a_do_not_retry_recovery_note(self):
        out = _tool_result_with_recovery("fs.write_file", self.refusal)
        self.assertIn(self.refusal, out, "the original refusal text must survive untouched")
        low = out.lower()
        self.assertIn("policy", low)
        self.assertIn("do not retry", low)
        # The remedy the refusal carries is repeated so the model can hand it on.
        self.assertIn("Raise the file-access level (e.g. to 'Your PC') to write here.", out)

    def test_the_note_applies_whatever_tool_hit_the_ladder(self):
        out = _tool_result_with_recovery("fs.write_protected_file", self.refusal)
        self.assertIn("do not retry", out.lower())

    def test_an_ordinary_failure_is_untouched(self):
        self.assertEqual(_tool_result_with_recovery("fs.write_file", "disk full"), "disk full")

    def test_the_missing_file_read_recovery_is_preserved(self):
        out = _tool_result_with_recovery("fs.read_file", "Error: file not found: x.txt")
        self.assertIn("Recovery: this file does not exist", out)


class TestIdenticalRefusalStopsSooner(_RefusalFixture):
    """The loop stops an identical failing call at count >= 3 (loop_execution).
    A policy refusal must reach that on its second identical attempt; anything
    with different args keeps its own fresh counter — no gate on new paths."""

    def test_second_identical_policy_refusal_crosses_the_stop_threshold(self):
        counts: dict[str, int] = {}
        args = {"path": str(self.desktop_target), "content": "hi"}
        first = _record_failed_tool(counts, "fs.write_file", args, self.refusal)
        self.assertLess(first, 3, "the first refusal is surfaced, not stopped")
        second = _record_failed_tool(counts, "fs.write_file", args, self.refusal)
        self.assertGreaterEqual(second, 3, "the identical retry of a deterministic refusal must trip the stop")

    def test_a_transient_failure_still_takes_three_identical_attempts(self):
        counts: dict[str, int] = {}
        args = {"command": "python build.py"}
        for expected in (1, 2):
            self.assertEqual(_record_failed_tool(counts, "shell.exec", args, "flaky network"), expected)
        self.assertGreaterEqual(_record_failed_tool(counts, "shell.exec", args, "flaky network"), 3)

    def test_a_different_path_attempt_starts_fresh(self):
        counts: dict[str, int] = {}
        _record_failed_tool(counts, "fs.write_file", {"path": str(self.desktop_target), "content": "hi"}, self.refusal)
        # Same tool, different target: its own signature, its own fresh count —
        # trying an allowed location after a refusal must never be impeded.
        other_refusal = _refusal_for(self.desktop_target.parent / "other.txt", self.workspace)
        count = _record_failed_tool(
            counts, "fs.write_file", {"path": str(self.desktop_target.parent / "other.txt")}, other_refusal
        )
        self.assertLess(count, 3)


if __name__ == "__main__":
    unittest.main()
