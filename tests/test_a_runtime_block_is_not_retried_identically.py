"""Runtime-protection blocks are the OTHER deterministic ladder. Treat them as one.

Measured 2026-09-19 by driving the Thomas UI in a browser. A chat task card asked
to split thomas/agent/loop_execution.py. The agent reasoned well, decided to create
thomas/agent/loop_provider_limits.py, and the write was blocked - correctly, since
an ordinary chat worker may not edit Thomas's own runtime.

Then the run continued for ten more minutes behind an "On it - working on this"
spinner, surfaced nothing to the person, and wrote nothing. The logs record a
single block; what the model did afterwards is not recorded, so this file does NOT
claim a retry loop was observed. Two defects found by reading the code, both fixed:

1. `is_file_access_refusal` only knows the FILE-ACCESS ladder's vocabulary, so a
   runtime-protection block scored as a transient failure in `_record_failed_tool`
   (increment 1, not 2) and the stability stop never tripped.
2. The block text said what was forbidden and not what to do, so the model had
   nothing to escalate to - though `fs.write_protected_file` was registered the
   whole time and Redesign existed.

`tests/test_a_policy_refusal_is_not_retried_identically.py` already pinned this for
the file-access ladder. This is the same guarantee for the second one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.agent.loop_tool_protocol import _record_failed_tool
from thomas.core.file_access import is_deterministic_policy_refusal, is_file_access_refusal
from thomas.server.chat_delegation_result_policy import result_with_policy_remedy
from thomas.tools import runtime_protection_paths as protection

RUNTIME_BLOCK = (
    "BLOCKED: 'thomas/agent/loop_provider_limits.py' is inside protected runtime "
    "directory 'thomas/agent/'. Agent-spawned tools cannot modify Thomas's own runtime code."
)


def test_a_runtime_block_is_deterministic_even_though_it_is_not_a_ladder_refusal() -> None:
    assert is_file_access_refusal(RUNTIME_BLOCK) is False, "it is genuinely a different ladder"
    assert is_deterministic_policy_refusal(RUNTIME_BLOCK) is True


def test_a_transient_error_is_still_counted_as_transient() -> None:
    """The widened recogniser must not swallow real retryable failures."""
    assert is_deterministic_policy_refusal("Connection reset by peer") is False
    assert is_deterministic_policy_refusal("") is False
    assert is_deterministic_policy_refusal(None) is False


def test_the_second_identical_blocked_write_stops_the_spin() -> None:
    """Counting double means attempt two reaches the stability stop, not attempt three."""
    counts: dict[str, int] = {}
    args = {"path": "thomas/agent/loop_provider_limits.py", "content": "x = 1\n"}

    first = _record_failed_tool(counts, "fs.write_file", args, RUNTIME_BLOCK)
    second = _record_failed_tool(counts, "fs.write_file", args, RUNTIME_BLOCK)

    assert first == 2, "a deterministic refusal counts double on the first hit"
    assert second >= 3, "the second identical attempt must reach the loop's stability stop"


def test_a_different_attempt_keeps_its_own_fresh_count() -> None:
    """Trying an ALLOWED path must never be impeded by the blocked one's count."""
    counts: dict[str, int] = {}
    blocked = {"path": "thomas/agent/loop_provider_limits.py", "content": "x = 1\n"}
    allowed = {"path": "docs/notes.md", "content": "x = 1\n"}

    _record_failed_tool(counts, "fs.write_file", blocked, RUNTIME_BLOCK)
    other = _record_failed_tool(counts, "fs.write_file", allowed, "Disk full")

    assert other == 1, "a different signature starts fresh"


@pytest.mark.parametrize(
    "target",
    ["thomas/agent/loop_provider_limits.py", "agent_safety.toml", ".git/hooks/pre-commit"],
)
def test_every_block_names_a_route_that_works(tmp_path: Path, target: str) -> None:
    """Rule 0: Thomas does not stop at a wall it will not name."""
    (tmp_path / "thomas" / "agent").mkdir(parents=True)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / "agent_safety.toml").write_text("[protected_files]\n", encoding="utf-8")
    protection.anchor_runtime_protection(tmp_path)

    reason = protection._is_protected_runtime_path(tmp_path, tmp_path / target)

    assert reason, f"{target} should be blocked"
    assert "fail the same way" in reason, "must say a retry is futile"
    assert "fs.write_protected_file" in reason, "must name the OS-authorization route"
    assert "Redesign" in reason, "must name the thread type meant for editing Thomas"
    assert is_deterministic_policy_refusal(reason), "and the loop must recognise it as permanent"


def test_an_allowed_path_is_still_allowed(tmp_path: Path) -> None:
    """The message and recogniser work must not turn into over-blocking."""
    (tmp_path / "docs").mkdir()
    protection.anchor_runtime_protection(tmp_path)

    assert protection._is_protected_runtime_path(tmp_path, tmp_path / "docs" / "notes.md") is None


def test_the_person_is_told_the_real_reason_not_just_the_stall() -> None:
    """The third link: the remedy has to reach the reply, not die in the runner.

    What the person actually saw on 2026-09-19 was "The refactor stalled again
    after 135 seconds, and no finished changes were produced. I can rerun it with
    a narrower scope" - a suggestion that could never work, because scope was
    never the obstacle. The stall was real; it was also the symptom.
    """
    summary = "The refactor stalled again after 135 seconds, and no finished changes were produced."

    out = result_with_policy_remedy(summary, [RUNTIME_BLOCK])

    assert summary in out, "the honest outcome must survive"
    assert "Redesign" in out, "and the route that works must be named"
    assert out != summary, "the remedy must actually be appended"


def test_a_runtime_block_is_not_described_as_a_setting_you_control() -> None:
    """The file-access note says "a setting you control". This is not one.

    Calling it a setting would send the person hunting for a slider that does not
    exist - a different way of stranding them.
    """
    out = result_with_policy_remedy("summary", [RUNTIME_BLOCK])

    assert "a setting you control" not in out


def test_a_ladder_refusal_still_gets_its_own_wording() -> None:
    """Widening must not flatten the file-access message that already worked."""
    ladder = "BLOCKED: cannot write there. Raise Thomas's file-access level to let it write files."

    out = result_with_policy_remedy("summary", [ladder])

    assert "a setting you control" in out, "the ladder's user-settable lever is still a setting"


def test_a_run_with_no_refusals_is_left_alone() -> None:
    assert result_with_policy_remedy("all good", []) == "all good"
    assert result_with_policy_remedy("all good", None) == "all good"
