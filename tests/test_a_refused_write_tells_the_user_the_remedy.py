"""A file-access POLICY refusal already carries its remedy — the user must see it.

Measured (gauntlet g-desktopfile, live 2026-08-05): asking chat to write a file
on the Desktop was refused by the file-access ladder. The tool refusal text
literally contained the lever the user controls — "Raise the file-access level
(e.g. to 'Your PC') to write here" (thomas/core/file_access.py) — but the
user-facing reply only said the environment "can only write inside its
workspace", with no mention that a user-settable setting exists.

These tests pin the sight path: the ladder's refusal is recognisable as policy,
its remedy sentence is extractable, and the composed delegation result carries
that sentence through to the user. No gate anywhere — nothing here can pass or
fail a run; it only words what already happened.
"""

import inspect
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from thomas.core.file_access import (
    READ_ONLY,
    WORKSPACE,
    authorize_write,
    file_access_refusal_remedy,
    is_file_access_refusal,
)
from thomas.server import chat_delegation as cd
from thomas.server.chat_delegation_result_policy import result_with_policy_remedy


def _outside_scope_refusal(tmp: Path) -> str:
    """The REAL ladder wording for a workspace-confined write aimed at the Desktop."""
    workspace = tmp / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    outside = tmp / "Desktop" / "notes.txt"
    allowed, reason = authorize_write(WORKSPACE, outside, workspace_root=workspace)
    assert not allowed, "test setup: the write must be refused"
    return reason


class TestRefusalRecognition(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def test_outside_scope_refusal_is_policy_and_names_its_remedy(self):
        reason = _outside_scope_refusal(self.tmp)
        self.assertTrue(is_file_access_refusal(reason))
        self.assertEqual(
            file_access_refusal_remedy(reason),
            "Raise the file-access level (e.g. to 'Your PC') to write here.",
        )

    def test_read_only_refusal_is_policy_and_names_its_remedy(self):
        workspace = self.tmp / "ws"
        workspace.mkdir(parents=True, exist_ok=True)
        allowed, reason = authorize_write(READ_ONLY, workspace / "a.txt", workspace_root=workspace)
        self.assertFalse(allowed)
        self.assertTrue(is_file_access_refusal(reason))
        self.assertEqual(
            file_access_refusal_remedy(reason),
            "Raise Thomas's file-access level to let it write files.",
        )

    def test_an_ordinary_error_is_not_a_policy_refusal(self):
        self.assertFalse(is_file_access_refusal("PermissionError: disk full"))
        self.assertEqual(file_access_refusal_remedy("PermissionError: disk full"), "")
        self.assertFalse(is_file_access_refusal(""))


class TestResultCarriesRemedy(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.refusal = _outside_scope_refusal(Path(self._tmp.name).resolve())

    def test_remedy_is_appended_when_the_summary_omits_it(self):
        summary = "I couldn't create the file because this environment can only write inside its workspace."
        out = result_with_policy_remedy(summary, [self.refusal])
        self.assertIn(summary, out)
        self.assertIn("Raise the file-access level (e.g. to 'Your PC') to write here.", out)

    def test_remedy_is_not_duplicated_when_the_worker_already_said_it(self):
        summary = "I couldn't write there. Raise the file-access level (e.g. to 'Your PC') to write here."
        self.assertEqual(result_with_policy_remedy(summary, [self.refusal]), summary)

    def test_no_refusals_means_no_change(self):
        self.assertEqual(result_with_policy_remedy("All done.", []), "All done.")
        self.assertEqual(result_with_policy_remedy("All done.", None), "All done.")

    def test_a_refusal_without_a_remedy_sentence_changes_nothing(self):
        # The OS-system-dir refusal is deterministic too, but the ladder offers
        # no user lever for it — appending nothing is the honest move.
        out = result_with_policy_remedy(
            "Done elsewhere.",
            ["BLOCKED: 'C:/Windows/x' is an OS system directory — never writable by Thomas at any access level."],
        )
        self.assertEqual(out, "Done elsewhere.")


def _model_runtime_event() -> dict[str, object]:
    return {
        "type": "model_runtime",
        "runtime": {
            "requested": {"profile": "test", "provider": "fixture", "model": "test-model"},
            "active": {"profile": "test", "provider": "fixture", "model": "test-model"},
            "attempts": [{"profile": "test", "provider": "fixture", "model": "test-model", "status": "success"}],
        },
    }


class _FakeEmitter:
    def __init__(self) -> None:
        self.completed_text: str | None = None
        self.failed_text: str | None = None
        self.progress_texts: list[str] = []

    async def progress(self, record, *, specialist_id, bot, text) -> None:
        self.progress_texts.append(text)

    async def completed(self, record, *, specialist_id, bot, text="") -> None:
        self.completed_text = text

    async def failed(self, record, *, specialist_id, bot, text) -> None:
        self.failed_text = text


class TestDelegationReplySurfacesTheRemedy(unittest.IsolatedAsyncioTestCase):
    """End to end through the runner: refusal in, remedy out — attached to the
    same announcement that carries the worker's honest answer."""

    def setUp(self) -> None:
        self._repo_root_tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._repo_root_tmpdir.cleanup)
        self.repo_root = Path(self._repo_root_tmpdir.name).resolve()
        self.refusal = _outside_scope_refusal(self.repo_root)

    async def test_the_reply_names_the_user_settable_lever(self):
        emitter = _FakeEmitter()
        bot = types.SimpleNamespace(name="Taylor", id="taylor")
        scripts = [
            [
                {"type": "tool_start", "name": "fs.write_file"},
                {"type": "tool_output", "name": "fs.write_file", "ok": False, "result_text": self.refusal},
                {
                    "type": "text",
                    "text": (
                        "I couldn't create the file because this environment can only write inside its workspace."
                    ),
                },
                {"type": "done"},
            ]
        ]
        state = {"calls": 0, "closed": 0}

        async def gen(app, **kwargs):  # noqa: ANN001, ANN003
            idx = state["calls"]
            state["calls"] += 1
            try:
                yield _model_runtime_event()
                for event in scripts[min(idx, len(scripts) - 1)]:
                    yield event
            finally:
                state["closed"] += 1

        with (
            patch.object(cd, "run_agent_worker_events", new=gen),
            patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e", "summary": "s"}),
            patch.object(cd.task_bot_runtime, "complete_execution", lambda *a, **k: None),
            patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
            patch.object(cd, "_snapshot_workspace_files", lambda *a, **k: []),
            patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
        ):
            await cd._run_agent_worker(
                None,
                execution_id="e",
                prompt="Write hello.txt on my Desktop.",
                specialist_id="coding",
                bot=bot,
                emitter=emitter,
                instructions="inst",
                repo_root=self.repo_root,
                work_dir=None,
                profile="test",
                model_id="test-model",
                autonomy_level=4,
            )
        final_text = emitter.completed_text or emitter.failed_text or ""
        self.assertIn(
            "Raise the file-access level (e.g. to 'Your PC') to write here.",
            final_text,
            "the announcement must carry the remedy the refusal already contained",
        )
        # The worker's honest answer survives alongside the remedy.
        self.assertIn("couldn't create the file", final_text)


class TestWorkerPromptTeachesRemedyRepetition(unittest.TestCase):
    def test_the_clause_exists_and_is_used_in_both_instruction_blocks(self):
        clause = cd._POLICY_REFUSAL_CLAUSE
        low = clause.lower()
        self.assertIn("remedy", low)
        self.assertIn("repeat", low)
        self.assertIn("identical", low)
        src = inspect.getsource(cd)
        # One definition plus a use in the normal-worker AND live-repo blocks.
        self.assertGreaterEqual(src.count("_POLICY_REFUSAL_CLAUSE"), 3)


if __name__ == "__main__":
    unittest.main()
