"""A failed run must not throw away what it produced.

Live P0: a two-file task left a valid one-page PDF in its workspace, and the
run was reported as producing nothing. The workspace sweep ran in exactly one
place -- the success finaliser -- so every non-success path discarded the
evidence along with the run.

Salvaged files are deliberately NOT proof. Proof means "this is the verified
answer"; these mean "this is what was on disk when it stopped", and the
distinction is what keeps a failed run from reading as a completed one.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.core import task_bot_runtime
from thomas.server.chat_delegation_workspace import snapshot_workspace_files


class SalvagedArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _execution(self) -> str:
        record = task_bot_runtime.create_execution(
            session_id="s-salvage",
            summary="make me a one page report",
            task_id="t-salvage",
            bot_id="john",
            repo_root=self.root,
        )
        return str(record["execution_id"])

    def test_a_failed_run_keeps_the_files_it_produced(self):
        exec_id = self._execution()
        work = self.root / "workspace"
        work.mkdir()
        (work / "report.pdf").write_bytes(b"%PDF-1.4 real output")

        task_bot_runtime.fail_execution(
            exec_id,
            summary="Cancelled by user.",
            blocker="cancelled",
            salvaged_artifacts=snapshot_workspace_files(work),
            repo_root=self.root,
        )

        row = task_bot_runtime.get_execution(exec_id, self.root) or {}
        self.assertEqual(row["state"], "failed")
        self.assertIn("report.pdf", row.get("salvaged_artifacts") or [])

    def test_salvage_is_not_recorded_as_proof(self):
        """A surface that reads proof must not see a failed run's leftovers."""
        exec_id = self._execution()
        work = self.root / "workspace"
        work.mkdir()
        (work / "half-done.md").write_text("draft", encoding="utf-8")

        task_bot_runtime.fail_execution(
            exec_id,
            summary="Timed out.",
            blocker="provider_native_timeout",
            salvaged_artifacts=snapshot_workspace_files(work),
            repo_root=self.root,
        )

        row = task_bot_runtime.get_execution(exec_id, self.root) or {}
        self.assertEqual(row.get("proof_status"), "failed")
        self.assertNotIn("half-done.md", str(row.get("proof") or ""))

    def test_failing_with_nothing_on_disk_is_still_fine(self):
        exec_id = self._execution()

        task_bot_runtime.fail_execution(
            exec_id, summary="Nothing produced.", blocker="cancelled", repo_root=self.root
        )

        row = task_bot_runtime.get_execution(exec_id, self.root) or {}
        self.assertEqual(row["state"], "failed")
        self.assertFalse(row.get("salvaged_artifacts"))

    def test_hidden_files_are_not_salvaged(self):
        work = self.root / "ws"
        (work / ".git").mkdir(parents=True)
        (work / ".git" / "HEAD").write_text("ref: x", encoding="utf-8")
        (work / "output.txt").write_text("real", encoding="utf-8")

        self.assertEqual(snapshot_workspace_files(work), ["output.txt"])


if __name__ == "__main__":
    unittest.main()
