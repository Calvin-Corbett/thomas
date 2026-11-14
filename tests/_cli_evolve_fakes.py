"""Seeded repos and a fake verifier panel, shared by the evolve CLI tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _seed_locked_corpus(root: Path) -> None:
    corpus = root / "evolve_corpus"
    cases = corpus / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    case_file = cases / "known_good_minimal.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "known_good_minimal",
                "expected_supervisor_outcome": "eligible_for_decision_gate",
                "session": {
                    "status": "ready",
                    "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
                    "verification": [{"source": "generated", "returncode": 0}],
                    "policy_violations": [],
                    "session_rejections": [],
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(case_file.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    (corpus / "LOCK.json").write_text(
        json.dumps({"version": 1, "files": {"cases/known_good_minimal.json": digest}}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seed_repo(root: Path) -> None:
    (root / "thomas").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
    (root / "thomas" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    (root / "tests" / "test_architecture.py").write_text(
        "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n",
        encoding="utf-8",
    )
    _seed_locked_corpus(root)


class _FakeVerifierPanelResult:
    def __init__(
        self,
        *,
        ok: bool,
        pass_count: int,
        quorum: int = 4,
        critical_dissent_count: int = 0,
        votes: list[dict[str, str]] | None = None,
    ) -> None:
        self.ok = ok
        self.pass_count = pass_count
        self.quorum = quorum
        self.critical_dissent_count = critical_dissent_count
        self.votes = (
            votes
            if votes is not None
            else [
                {"role": f"role_{idx}", "status": "pass", "reason": "ok", "severity": "advisory"}
                for idx in range(pass_count)
            ]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "quorum": self.quorum,
            "pass_count": self.pass_count,
            "critical_dissent_count": self.critical_dissent_count,
            "votes": self.votes,
        }
