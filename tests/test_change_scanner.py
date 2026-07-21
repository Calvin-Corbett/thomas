"""CAP-083 acceptance tests: change-scoped security scanning that feeds
confirmed findings back into generation.

Acceptance line: "Apply scanning to every generated change and feed confirmed
findings back into generation."

Covered here:
- (a) a generated change introducing a hardcoded secret / eval / shell=True is
  flagged, each with its rule id;
- (b) a clean change yields no findings;
- (c) confirmed findings produce regeneration directives naming file:line + a
  concrete fix instruction;
- (d) a suppressed finding (inline ``# nosec`` and explicit fingerprint) is
  excluded from the confirmed set;
- (e) the change is marked not-clean iff there are confirmed findings;
- (f) an injectable extra rule fires;
- (g) the scan is deterministic.

All inputs are synthetic source strings -- hermetic, no network, no clock, no
repository access.
"""

from __future__ import annotations

import ast

from thomas.security.change_scanner import (
    BUILTIN_RULES,
    ChangeScanResult,
    ChangeSecurityScanner,
    Confidence,
    FileEdit,
    GeneratedChange,
    RegenerationDirective,
    Rule,
    RuleContext,
    RuleMatch,
)

# ---------------------------------------------------------------------------
# Sample generated content -- secrets are assembled at runtime so scanning the
# test tree itself stays clean.
# ---------------------------------------------------------------------------

_SECRET_SRC = 'API_KEY = "' + "sk-" + "a1b2c3d4e5f6g7h8i9j0" + '"\n'
_EVAL_SRC = "def run(expr):\n    return eval(expr)\n"
_SHELL_SRC = "import subprocess\n\n\ndef go(cmd):\n    subprocess.run(cmd, shell=True)\n"
_PICKLE_SRC = "import pickle\n\n\ndef load(blob):\n    return pickle.loads(blob)\n"
_SQL_SRC = 'def q(uid):\n    return "SELECT * FROM users WHERE id = " + uid\n'
_CLEAN_SRC = "import os\n\n\ndef fetch(uid):\n    key = os.environ['API_KEY']\n    return {'uid': uid, 'key': key}\n"


def _change(**files: str) -> GeneratedChange:
    return GeneratedChange.from_mapping(files)


# ---------------------------------------------------------------------------
# (a) scanning every generated change flags each defect with its rule
# ---------------------------------------------------------------------------


def test_hardcoded_secret_is_flagged_with_rule() -> None:
    scanner = ChangeSecurityScanner()
    findings = scanner.scan(_change(**{"pkg/config.py": _SECRET_SRC}))
    rules = {f.rule_id for f in findings}
    assert "hardcoded-secret" in rules
    secret = next(f for f in findings if f.rule_id == "hardcoded-secret")
    assert secret.file == "pkg/config.py"
    assert secret.line == 1


def test_eval_is_flagged_with_rule() -> None:
    findings = ChangeSecurityScanner().scan(_change(**{"pkg/run.py": _EVAL_SRC}))
    evals = [f for f in findings if f.rule_id == "eval-exec"]
    assert len(evals) == 1
    assert evals[0].line == 2


def test_shell_true_is_flagged_with_rule() -> None:
    findings = ChangeSecurityScanner().scan(_change(**{"pkg/sh.py": _SHELL_SRC}))
    shells = [f for f in findings if f.rule_id == "shell-true"]
    assert len(shells) == 1
    assert shells[0].line == 5


def test_pickle_loads_is_flagged_with_rule() -> None:
    findings = ChangeSecurityScanner().scan(_change(**{"pkg/p.py": _PICKLE_SRC}))
    assert any(f.rule_id == "pickle-loads" for f in findings)


def test_sql_concatenation_is_flagged_with_rule() -> None:
    findings = ChangeSecurityScanner().scan(_change(**{"pkg/db.py": _SQL_SRC}))
    assert any(f.rule_id == "sql-injection" for f in findings)


def test_scan_targets_only_files_in_the_change() -> None:
    # Two files in the change; only the offending one produces a finding, and
    # the finding is attributed to that file (the scan is per-change, per-file).
    change = _change(**{"a/clean.py": _CLEAN_SRC, "b/bad.py": _EVAL_SRC})
    findings = ChangeSecurityScanner().scan(change)
    assert {f.file for f in findings} == {"b/bad.py"}


def test_non_python_edits_are_skipped() -> None:
    change = _change(**{"notes.md": "password = hunter2 in prose"})
    result = ChangeSecurityScanner().evaluate_change(change)
    assert result.findings == ()
    assert result.files_scanned == 0


# ---------------------------------------------------------------------------
# (b) a clean change yields no findings
# ---------------------------------------------------------------------------


def test_clean_change_yields_no_findings() -> None:
    result = ChangeSecurityScanner().evaluate_change(_change(**{"pkg/ok.py": _CLEAN_SRC}))
    assert result.findings == ()
    assert result.confirmed == ()
    assert result.directives == ()
    assert result.clean is True
    assert result.files_scanned == 1


def test_constant_sql_without_dynamic_part_is_not_flagged() -> None:
    src = 'def q():\n    return "SELECT * FROM users"\n'
    findings = ChangeSecurityScanner().scan(_change(**{"pkg/db.py": src}))
    assert findings == []


# ---------------------------------------------------------------------------
# (c) confirmed findings produce regeneration directives (file:line + fix)
# ---------------------------------------------------------------------------


def test_confirmed_finding_produces_directive_with_location_and_fix() -> None:
    scanner = ChangeSecurityScanner()
    result = scanner.evaluate_change(_change(**{"pkg/run.py": _EVAL_SRC}))
    assert len(result.directives) == 1
    directive = result.directives[0]
    assert isinstance(directive, RegenerationDirective)
    assert directive.file == "pkg/run.py"
    assert directive.line == 2
    assert directive.location == "pkg/run.py:2"
    assert directive.rule_id == "eval-exec"
    # concrete, actionable fix instruction the generator should apply
    assert "eval" in directive.fix_instruction.lower()
    assert "pkg/run.py:2" in directive.as_prompt()
    assert "eval-exec" in directive.as_prompt()


def test_directives_only_come_from_confirmed_findings() -> None:
    scanner = ChangeSecurityScanner()
    change = _change(**{"pkg/run.py": _EVAL_SRC})
    findings = scanner.scan(change)
    fingerprint = findings[0].fingerprint
    # Suppress the only finding -> no confirmed findings -> no directives.
    confirmed = scanner.confirm(findings, suppressions=[fingerprint])
    assert confirmed == []
    assert scanner.build_directives(confirmed) == []


# ---------------------------------------------------------------------------
# (d) suppressed findings are excluded from the confirmed set
# ---------------------------------------------------------------------------


def test_explicit_suppression_excludes_finding_from_confirmed() -> None:
    scanner = ChangeSecurityScanner()
    change = _change(**{"pkg/run.py": _EVAL_SRC})
    findings = scanner.scan(change)
    assert len(findings) == 1
    result = scanner.evaluate_change(change, suppressions=[findings[0].fingerprint])
    assert result.confirmed == ()
    assert result.clean is True
    # the raw finding is still reported, just not confirmed
    assert len(result.findings) == 1
    assert result.findings[0].confirmed is False


def test_inline_nosec_marker_suppresses_finding() -> None:
    src = "def run(expr):\n    return eval(expr)  # nosec deliberate\n"
    scanner = ChangeSecurityScanner()
    change = _change(**{"pkg/run.py": src})
    findings = scanner.scan(change)
    assert findings[0].inline_suppressed is True
    confirmed = scanner.confirm(findings)
    assert confirmed == []


def test_min_confidence_floor_excludes_lower_confidence() -> None:
    scanner = ChangeSecurityScanner()
    findings = scanner.scan(_change(**{"pkg/config.py": _SECRET_SRC}))
    # The name-based secret assignment is MEDIUM confidence; a HIGH floor drops it,
    # unless the literal also matched a known credential shape (which is HIGH).
    secret_findings = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert secret_findings
    medium_only = [f for f in secret_findings if f.confidence == Confidence.MEDIUM]
    if medium_only:
        confirmed = scanner.confirm(medium_only, min_confidence=Confidence.HIGH)
        assert confirmed == []


# ---------------------------------------------------------------------------
# (e) not-clean iff there are confirmed findings
# ---------------------------------------------------------------------------


def test_change_is_not_clean_iff_confirmed_findings_exist() -> None:
    scanner = ChangeSecurityScanner()

    dirty = scanner.evaluate_change(_change(**{"pkg/run.py": _EVAL_SRC}))
    assert dirty.confirmed
    assert dirty.clean is False

    clean = scanner.evaluate_change(_change(**{"pkg/ok.py": _CLEAN_SRC}))
    assert not clean.confirmed
    assert clean.clean is True

    # A dirty change whose sole finding is suppressed becomes clean again.
    change = _change(**{"pkg/run.py": _EVAL_SRC})
    fp = scanner.scan(change)[0].fingerprint
    suppressed = scanner.evaluate_change(change, suppressions=[fp])
    assert not suppressed.confirmed
    assert suppressed.clean is True


# ---------------------------------------------------------------------------
# (f) injectable extra rule fires
# ---------------------------------------------------------------------------


def _no_todo_detector(ctx: RuleContext) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for node in ast.walk(ctx.tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "DANGER" in node.value:
            matches.append(RuleMatch(line=node.lineno, col=node.col_offset))
    return matches


def test_injectable_extra_rule_fires() -> None:
    extra = Rule(
        rule_id="no-danger-literal",
        description="Literal contains the DANGER marker.",
        fix_hint="Remove the DANGER marker from the string literal.",
        confidence=Confidence.HIGH,
        detector=_no_todo_detector,
    )
    scanner = ChangeSecurityScanner(extra_rules=[extra])
    src = 'MSG = "this is DANGER text"\n'
    result = scanner.evaluate_change(_change(**{"pkg/m.py": src}))
    assert any(f.rule_id == "no-danger-literal" for f in result.confirmed)
    directive = next(d for d in result.directives if d.rule_id == "no-danger-literal")
    assert directive.file == "pkg/m.py"
    assert "DANGER" in directive.fix_instruction


def test_extra_rule_does_not_replace_builtins() -> None:
    extra = Rule(
        rule_id="extra",
        description="extra",
        fix_hint="fix",
        confidence=Confidence.LOW,
        detector=lambda ctx: [],
    )
    scanner = ChangeSecurityScanner(extra_rules=[extra])
    builtin_ids = {r.rule_id for r in BUILTIN_RULES}
    scanner_ids = {r.rule_id for r in scanner.rules}
    assert builtin_ids <= scanner_ids
    assert "extra" in scanner_ids


# ---------------------------------------------------------------------------
# (g) determinism
# ---------------------------------------------------------------------------


def test_scan_is_deterministic() -> None:
    change = _change(
        **{
            "z/db.py": _SQL_SRC,
            "a/run.py": _EVAL_SRC,
            "m/sh.py": _SHELL_SRC,
            "k/config.py": _SECRET_SRC,
        }
    )
    scanner = ChangeSecurityScanner()
    first = scanner.evaluate_change(change)
    second = scanner.evaluate_change(change)
    assert first == second
    # findings are sorted by (file, line, col, rule_id)
    ordered = [(f.file, f.line, f.col, f.rule_id) for f in first.findings]
    assert ordered == sorted(ordered)


def test_result_to_dict_is_serializable() -> None:
    import json

    result = ChangeSecurityScanner().evaluate_change(_change(**{"pkg/run.py": _EVAL_SRC}))
    payload = json.dumps(result.to_dict())
    reloaded = json.loads(payload)
    assert reloaded["clean"] is False
    assert reloaded["directives"][0]["rule_id"] == "eval-exec"
    assert isinstance(result, ChangeScanResult)


def test_file_edit_scannable_flag() -> None:
    assert FileEdit("a.py", "").is_scannable is True
    assert FileEdit("a.pyi", "").is_scannable is True
    assert FileEdit("a.md", "").is_scannable is False
