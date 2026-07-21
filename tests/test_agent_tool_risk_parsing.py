"""CAP-084 L2: parsed-command danger policy — obfuscation/alias bypass and negative tests.

Proves the upgrade from substring markers to tokenized command analysis:
bypasses that the legacy marker logic missed are now caught, and quoted-string
false positives that markers flagged are now clean.
"""

from __future__ import annotations

import pytest

from thomas.agent.command_analysis import analyze_command
from thomas.agent.tool_risk import (
    ToolActionCategory,
    ToolRiskControl,
    ToolRiskLevel,
    classify_tool_action,
)

# The exact marker tuple the legacy substring policy used (tool_risk.py before
# CAP-084 L2). Kept here so bypass tests can prove the old logic misses them.
_LEGACY_MARKERS = (
    "chmod",
    "chown",
    "del ",
    "format",
    "git push",
    "mkfs",
    "remove-item",
    "rm ",
    "rmdir",
)


def _legacy_marker_hit(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in _LEGACY_MARKERS)


# ── Bypasses the legacy substring policy MISSED, now caught ────────────────

BYPASS_COMMANDS = (
    '"rm" -rf /tmp/data',  # quote-wrapped argv[0] breaks the "rm " marker
    "r''m -rf /tmp/data",  # quote-splitting inside argv[0]
    "rm\t-rf\t/tmp/data",  # tab separators defeat the space-suffixed marker
    'cmd /c "del" /s /q C:\\data',  # quoted del defeats the "del " marker
    'echo ok; "rm" -rf /srv',  # obfuscated delete hidden behind chaining
    "bash -c 'r\"\"m -rf /'",  # obfuscation nested inside a quoted -c payload
    "dd if=/dev/zero of=/dev/sda",  # raw device overwrite (no legacy marker)
    "git clean -fdx",  # force-clean (no legacy marker)
    "git reset --hard origin/main",  # protected-ref reset (no legacy marker)
    'psql -c "DROP DATABASE prod"',  # SQL drop via client payload
    "mysql -e 'truncate table users'",  # SQL truncate via client payload
    "shutdown -h now",  # host shutdown (no legacy marker)
)


@pytest.mark.parametrize("command", BYPASS_COMMANDS)
def test_bypasses_missed_by_legacy_markers_are_now_caught(command: str) -> None:
    assert not _legacy_marker_hit(command), f"not a real bypass, legacy markers already hit: {command!r}"
    analysis = analyze_command(command)
    assert analysis.dangerous, f"parsed policy failed to catch: {command!r}"
    assert analysis.parsed
    assert analysis.findings


# ── Alias / wrapper / chaining coverage ────────────────────────────────────

DANGEROUS_COMMANDS = (
    "/bin/rm -rf /var/data",
    "sudo rm -rf /",
    "sudo -u root rm -rf /",
    "nohup rm -rf /srv &",
    "env FOO=1 rm -rf /",
    "AWS_PROFILE=prod rm -rf /",
    "rm  -rf   /doubled/space",
    "C:\\Windows\\System32\\cmd.exe /c del /s /q C:\\data",
    'powershell -Command "Remove-Item -Recurse -Force C:\\data"',
    "pwsh -c Remove-Item -Recurse -Force ./build",
    "bash -c 'rm -rf /'",
    "mkfs.ext4 /dev/sda1",
    "rd /s /q C:\\backup",
    "rmdir /s /q C:\\backup",
    "format c:",
    "echo hi && rm -rf /",
    "true || rm -rf /",
    "echo x | xargs rm -rf",
    "ls -la\nrm -rf /",
    "drop database analytics",
    "git push --force origin main",
    "reboot",
)


@pytest.mark.parametrize("command", DANGEROUS_COMMANDS)
def test_alias_wrapper_and_chaining_coverage(command: str) -> None:
    analysis = analyze_command(command)
    assert analysis.dangerous, f"parsed policy failed to catch: {command!r}"


def test_every_chained_segment_is_evaluated() -> None:
    analysis = analyze_command("git status && echo fine; rm -rf /srv | cat")
    assert analysis.dangerous
    assert any(finding.rule == "delete_command" for finding in analysis.findings)
    assert any("rm -rf /srv" in finding.segment for finding in analysis.findings)


# ── Negatives: quoted strings and lookalike names must NOT trigger ─────────

SAFE_COMMANDS = (
    "grep 'rm -rf' notes.txt",  # destructive text as a quoted STRING argument
    'grep "drop database" migration.log',
    "python format_output.py",  # lookalike filename, not the format command
    "pip install rmdirtool",  # legacy "rmdir" substring false positive
    'echo "git push is risky"',  # legacy "git push" substring false positive
    "rmdir_helper --dry-run",
    "ls -la /tmp",
    "git status && git log --oneline",
    "git clean -n",  # dry run, no force flag
    "git reset --hard HEAD~1",  # not a protected ref
    "dd if=/dev/zero of=./disk.img",  # file target, not a raw device
    "truncate -s 0 build.log",  # coreutils truncate, not SQL
    "pytest tests/test_example.py",
)


@pytest.mark.parametrize("command", SAFE_COMMANDS)
def test_safe_commands_do_not_trigger(command: str) -> None:
    analysis = analyze_command(command)
    assert not analysis.dangerous, f"false positive on: {command!r} -> {analysis.findings}"


# ── Parse-failure fallback: never less strict than the legacy markers ──────


def test_unparseable_dangerous_command_falls_back_to_markers() -> None:
    analysis = analyze_command('rm -rf / "unterminated')
    assert not analysis.parsed
    assert analysis.dangerous
    assert all(finding.rule == "marker_fallback" for finding in analysis.findings)


def test_unparseable_benign_command_stays_clean() -> None:
    analysis = analyze_command('echo "hello')
    assert not analysis.parsed
    assert not analysis.dangerous


# ── Public API: classify_tool_action keeps its shape, reasons carry segment ─


def test_shell_action_with_obfuscated_delete_escalates_to_critical() -> None:
    profile = classify_tool_action("shell.run", {"command": '"rm" -rf /srv/data'})

    assert profile.category == ToolActionCategory.SHELL
    assert profile.risk_level == ToolRiskLevel.CRITICAL
    assert ToolRiskControl.DENY_BY_DEFAULT in profile.recommended_controls
    assert profile.matched_rule == "shell_execution"
    # The reason must name the parsed segment that triggered.
    assert "rm -rf /srv/data" in profile.reason


def test_shell_action_with_quoted_destructive_string_stays_high() -> None:
    profile = classify_tool_action("shell.run", {"command": "grep 'rm -rf' notes.txt"})

    assert profile.category == ToolActionCategory.SHELL
    assert profile.risk_level == ToolRiskLevel.HIGH
    assert ToolRiskControl.DENY_BY_DEFAULT not in profile.recommended_controls


def test_shell_action_with_lookalike_filename_stays_high() -> None:
    profile = classify_tool_action("shell.run", {"command": "python format_output.py"})

    assert profile.risk_level == ToolRiskLevel.HIGH


def test_unprefixed_tool_with_dangerous_command_matches_shell_rule() -> None:
    profile = classify_tool_action("automation.step", {"script": "sudo rm -rf /"})

    assert profile.category == ToolActionCategory.SHELL
    assert profile.risk_level == ToolRiskLevel.CRITICAL
    assert profile.matched_rule == "shell_execution"


def test_argv_list_arguments_are_analyzed_as_one_command() -> None:
    profile = classify_tool_action("subprocess.run", {"argv": ["rm", "-rf", "/tmp/x"]})

    assert profile.risk_level == ToolRiskLevel.CRITICAL
    assert "rm -rf /tmp/x" in profile.reason
