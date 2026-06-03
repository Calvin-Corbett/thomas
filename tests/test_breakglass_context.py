from __future__ import annotations

from scripts.breakglass_context import (
    BREAKGLASS_CONTEXT_ENV,
    breakglass_context_from_env,
    breakglass_context_from_json,
    breakglass_context_to_json,
    build_commit_blocker_context,
)


def test_build_commit_blocker_context_preserves_concrete_gate_evidence() -> None:
    output = """
Thomas Protected Files Gate.......................................................Failed
- hook id: thomas-protected-files-gate
- exit code: 1
You modified 7 protected file(s):
  - agent_safety.toml  (protected policy document)

Thomas Merge Readiness............................................................Failed
- hook id: thomas-merge-readiness
- exit code: 1
Merge readiness: FAIL
- repo_hygiene: FAIL
  - uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800
- architecture: FAIL
  E   Failed: New files exceeding soft limit:
  E     thomas/agent/skills_runtime.py is 838 lines (limit for new files: 800)
"""

    context = build_commit_blocker_context(
        output,
        ai_recommendation="The protected-file change needs review, and the large commit should be split unless the files are one clear checkpoint.",
    )

    assert context.title == "Thomas commit blocker"
    assert len(context.issues) == 2
    assert "large commit should be split" in context.recommendation
    joined = "\n".join(line for issue in context.issues for line in issue.evidence)
    assert "1548 changed lines exceeds max_uncommitted_changed_lines=800" in joined
    assert "838 lines" in joined
    assert any("protected Thomas files" in issue.recommendation for issue in context.issues)


def test_build_commit_blocker_context_accepts_model_authored_gate_guidance() -> None:
    output = """
Thomas Merge Readiness............................................................Failed
- uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800
"""

    context = build_commit_blocker_context(
        output,
        ai_guidance_json=(
            '{"recommendation":"This commit is 748 lines over the limit, but the files are related.",'
            '"resolution_label":"Split commit",'
            '"resolution_prompt":"Split the current changes into two smaller commits and retry.",'
            '"issues":[{"gate":"Thomas Merge Readiness",'
            '"plain_reason":"This commit changes 1548 lines, and the guardrail allows 800.",'
            '"impact":"Large commits are harder to review and easier to get wrong.",'
            '"recommendation":"Split it unless these files must land together.",'
            '"next_step":"Review the file list, then either split it or authorize one checkpoint."}]}'
        ),
    )

    issue = context.issues[0]
    assert "748 lines over" in context.recommendation
    assert issue.plain_reason == "This commit changes 1548 lines, and the guardrail allows 800."
    assert issue.impact == "Large commits are harder to review and easier to get wrong."
    assert issue.next_step == "Review the file list, then either split it or authorize one checkpoint."
    assert context.resolution_label == "Split commit"
    assert "two smaller commits" in context.resolution_prompt


def test_breakglass_context_json_round_trip_and_env_loader() -> None:
    context = build_commit_blocker_context(
        "Thomas Workboard Agent Claim Gate.................................Failed\n"
        "- no active workboard claim found for 'codex-owner'.\n"
    )

    raw = breakglass_context_to_json(context)
    restored = breakglass_context_from_json(raw)
    loaded = breakglass_context_from_env({BREAKGLASS_CONTEXT_ENV: raw})

    assert restored is not None
    assert loaded is not None
    assert restored.issues[0].gate == "Thomas Workboard Agent Claim Gate"
    assert "codex-owner" in loaded.issues[0].why
