"""Tests for cross-tool skill/format compatibility (CAP-133).

Proves lossless live compatibility with a major external skill format
(Claude/Anthropic ``SKILL.md``) and a major external instruction format
(``CLAUDE.md`` / ``.cursorrules``), and that incompatibility is surfaced with a
diff rather than silently dropped.
"""

from __future__ import annotations

import pytest

from thomas.skills.format_compat import (
    FORMAT_ANTHROPIC_SKILL,
    FORMAT_CLAUDE_MD,
    FORMAT_CURSORRULES,
    CompatReport,
    FormatCompatError,
    classify_format,
    compat_report,
    export_instruction,
    export_skill,
    import_instruction,
    import_skill,
)

# A Claude/Anthropic SKILL.md document modeled exactly on the on-disk convention
# (frontmatter block with name + description, then a free-form body).
CLAUDE_SKILL_MD = (
    "---\n"
    "name: cloudflare-deploy\n"
    "description: Deploy applications and infrastructure to Cloudflare Workers.\n"
    "---\n"
    "\n"
    "# Cloudflare Deploy\n"
    "\n"
    "Use this skill when Thomas needs to deploy an app on Cloudflare.\n"
    "\n"
    "## Workflow\n"
    "1. Inspect the app shape and target Cloudflare product.\n"
    "2. Run the relevant deploy command and capture the outcome.\n"
)

# A CLAUDE.md instruction document.
CLAUDE_MD_INSTRUCTIONS = (
    "# Project instructions\n"
    "\n"
    "- Always run the tests before committing.\n"
    "- Never use exec().\n"
    "- Tag commits with the agent name.\n"
)

# A .cursorrules instruction document.
CURSORRULES_INSTRUCTIONS = (
    "You are an expert TypeScript engineer.\n"
    "Prefer functional components.\n"
    "Do not introduce new dependencies without approval.\n"
)


# --- (1) Skill format: lossless round-trip ---------------------------------
def test_skill_import_export_is_byte_lossless() -> None:
    skill = import_skill(CLAUDE_SKILL_MD)
    assert skill.name == "cloudflare-deploy"
    assert skill.description == "Deploy applications and infrastructure to Cloudflare Workers."
    assert skill.field_order == ("name", "description")
    assert skill.unsupported == ()
    # Round-trip must reproduce the source byte-for-byte.
    assert export_skill(skill) == CLAUDE_SKILL_MD


def test_skill_body_preserved_verbatim() -> None:
    skill = import_skill(CLAUDE_SKILL_MD)
    assert skill.body.startswith("\n# Cloudflare Deploy\n")
    assert skill.body.endswith("capture the outcome.\n")


def test_skill_preserves_frontmatter_key_order() -> None:
    # description appears before name in the source; export must keep that order.
    reordered = "---\ndescription: Reordered fields.\nname: reorder-skill\n---\nBody.\n"
    skill = import_skill(reordered)
    assert skill.field_order == ("description", "name")
    assert export_skill(skill) == reordered


def test_import_skill_rejects_document_without_frontmatter() -> None:
    with pytest.raises(FormatCompatError):
        import_skill("# Just a heading\n\nNo frontmatter here.\n")


# --- (2) Instruction format: lossless round-trip ---------------------------
def test_claude_md_instruction_is_lossless() -> None:
    instruction = import_instruction(CLAUDE_MD_INSTRUCTIONS, FORMAT_CLAUDE_MD)
    assert instruction.fmt == FORMAT_CLAUDE_MD
    assert export_instruction(instruction) == CLAUDE_MD_INSTRUCTIONS


def test_cursorrules_instruction_is_lossless() -> None:
    instruction = import_instruction(CURSORRULES_INSTRUCTIONS, FORMAT_CURSORRULES)
    assert export_instruction(instruction) == CURSORRULES_INSTRUCTIONS


# --- (3) compat_report: classify + assert lossless, surface diff -----------
def test_compat_report_skill_lossless() -> None:
    report = compat_report(CLAUDE_SKILL_MD, filename="SKILL.md")
    assert isinstance(report, CompatReport)
    assert report.source_format == FORMAT_ANTHROPIC_SKILL
    assert report.kind == "skill"
    assert report.lossless_round_trip is True
    assert report.diff == ""
    assert report.unsupported_fields == ()


def test_compat_report_instruction_lossless() -> None:
    report = compat_report(CLAUDE_MD_INSTRUCTIONS, filename="CLAUDE.md")
    assert report.source_format == FORMAT_CLAUDE_MD
    assert report.kind == "instruction"
    assert report.lossless_round_trip is True
    assert report.diff == ""


def test_compat_report_surfaces_unsupported_field_with_diff() -> None:
    # A skill carrying a frontmatter field the internal model does not represent.
    doc_with_extra = "---\nname: licensed-skill\ndescription: Has an unsupported field.\nlicense: MIT\n---\nBody.\n"
    report = compat_report(doc_with_extra, filename="SKILL.md")
    # Incompatibility must be surfaced, not hidden.
    assert report.lossless_round_trip is False
    assert "license" in report.unsupported_fields
    assert report.diff != ""
    # The dropped field must appear in the diff (surfaced, not silently gone).
    assert "license: MIT" in report.diff
    # And the round-trip export genuinely omits the unsupported field.
    assert "license: MIT" not in report.exported


def test_unsupported_field_preserved_on_import_not_silently_dropped() -> None:
    doc_with_extra = "---\nname: licensed-skill\ndescription: Has an unsupported field.\nlicense: MIT\n---\nBody.\n"
    skill = import_skill(doc_with_extra)
    # The field is retained on the internal object for inspection...
    assert ("license", "MIT") in skill.unsupported
    # ...but is not part of the modeled schema, so export drops it (loss).
    assert export_skill(skill) != doc_with_extra


# --- Classification --------------------------------------------------------
def test_classify_by_filename() -> None:
    assert classify_format("", "SKILL.md") == FORMAT_ANTHROPIC_SKILL
    assert classify_format("", "CLAUDE.md") == FORMAT_CLAUDE_MD
    assert classify_format("", ".cursorrules") == FORMAT_CURSORRULES
    assert classify_format("", "sub/dir/AGENTS.md") == FORMAT_CLAUDE_MD


def test_classify_by_content_without_filename() -> None:
    # Frontmatter with a name key => skill.
    assert classify_format(CLAUDE_SKILL_MD) == FORMAT_ANTHROPIC_SKILL
    # Plain instructions => claude-md.
    assert classify_format(CLAUDE_MD_INSTRUCTIONS) == FORMAT_CLAUDE_MD
    assert classify_format(CURSORRULES_INSTRUCTIONS) == FORMAT_CLAUDE_MD


def test_classify_prefers_filename_hint_over_content() -> None:
    # Filename hint wins even if the body has skill-like frontmatter.
    assert classify_format(CLAUDE_SKILL_MD, "CLAUDE.md") == FORMAT_CLAUDE_MD


# --- Determinism -----------------------------------------------------------
def test_compat_report_is_deterministic() -> None:
    first = compat_report(CLAUDE_SKILL_MD, filename="SKILL.md")
    second = compat_report(CLAUDE_SKILL_MD, filename="SKILL.md")
    assert first == second


def test_unsupported_report_diff_is_deterministic() -> None:
    doc_with_extra = "---\nname: licensed-skill\ndescription: Has an unsupported field.\nlicense: MIT\n---\nBody.\n"
    first = compat_report(doc_with_extra, filename="SKILL.md")
    second = compat_report(doc_with_extra, filename="SKILL.md")
    assert first.diff == second.diff
    assert first == second
