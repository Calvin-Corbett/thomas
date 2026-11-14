"""A remediation pass never builds a contract from its own prompt.

When the rules of the road fail, the loop runs again with Thomas's own message as the prompt: "Quality gate failed.
Continue working now and fix the required checks below ... Monolith guard ran after code edits: Run `python
scripts/forge/gates/monolith_guard.py` after code mutations." A remediation pass keeps the contract its first pass
built, but only when the first pass had one. On 2026-09-27 a Thomas project's first pass had nothing to check, so the
remediation pass read Thomas's message as the request, and the whole-repository guard it names became a command that
must exit 0. It cannot while dev carries oversized files the project never touched, so the project could not finish.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from thomas.agent import acceptance_runtime
from thomas.core.rules_of_road import build_remediation_prompt

REMEDIATION = build_remediation_prompt(
    {
        "passed": False,
        "job_type": "coding",
        "checks": [
            {
                "id": "coding_monolith_guard",
                "label": "Monolith guard ran after code edits",
                "required": True,
                "passed": False,
                "detail": "Run `python scripts/forge/gates/monolith_guard.py` after code mutations.",
            }
        ],
    }
)


def _loop(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(tools=SimpleNamespace(sandbox_path=tmp_path)),
        llm=SimpleNamespace(config=SimpleNamespace(reasoning_effort="high")),
    )


def test_a_remediation_pass_with_no_contract_builds_none_from_thomass_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    assert "monolith_guard.py" in REMEDIATION  # the ruler: the message names the whole-repository guard
    loop = _loop(tmp_path)

    block = acceptance_runtime.begin_contract(loop, prompt_text=REMEDIATION, route_path="coding", attempt=1)

    assert block == ""
    assert getattr(loop, "_acceptance_state", None) is None


def test_a_first_pass_still_builds_its_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    loop = _loop(tmp_path)

    acceptance_runtime.begin_contract(loop, prompt_text="Create js/game.js.", route_path="coding", attempt=0)

    assert [item.item_id for item in loop._acceptance_state["items"] if item.kind == "output_path"] == [
        "output:js/game.js"
    ]
