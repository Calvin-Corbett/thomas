"""Verification planning helpers for Thomas evolve sessions."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from evolve_supervisor.coverage_floor import execution_coverage_failures, select_blast_radius_tests

MAX_BLAST_RADIUS_TEST_FILES = 8
SHELL_VERIFY_METACHARS = (";", "&", "|", "<", ">", "`", "\n", "\r")
REJECTED_VERIFY_SCRIPT = "import sys; sys.stderr.write(sys.argv[1] + '\\n'); raise SystemExit(2)"
UNKNOWN_ACCEPTANCE_CHECK_SCRIPT = (
    "import sys; sys.stderr.write('unknown evolve acceptance check: ' + sys.argv[1] + '\\n'); raise SystemExit(2)"
)
PYTHON_SEMANTIC_DELTA_SCRIPT = r"""
import ast
import os
import sys
from pathlib import Path


def normalized_tree(path):
    if not path.exists():
        return "<missing>"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        return f"<syntax-error:{exc}>"
    body = list(tree.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    tree.body = body
    return ast.dump(tree, include_attributes=False)


blue_root = Path(os.environ.get("THOMAS_EVOLVE_BLUE_ROOT") or "")
if not blue_root.is_dir():
    raise SystemExit("THOMAS_EVOLVE_BLUE_ROOT is missing or invalid")
candidate_root = Path.cwd()
noops = []
for raw in sys.argv[1:]:
    rel = raw.replace("\\", "/").lstrip("./")
    before = normalized_tree(blue_root / rel)
    after = normalized_tree(candidate_root / rel)
    if before == after:
        noops.append(rel)
if noops:
    raise SystemExit("semantic-noop Python change(s): " + ", ".join(noops[:8]))
print("semantic delta: PASS")
"""
EVOLVE_STATUS_VERIFIER_PANEL_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"semantic-status-{nonce}"
pass_count = 5
quorum = 4
dissent = 0
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-status-semantic-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
evolve_root = root / ".thomas" / "evolve"
session_dir = evolve_root / "sessions" / session_id
session_dir.mkdir(parents=True)
(evolve_root / "charter.json").write_text(
    json.dumps(
        {
            "objective": "Semantic status check",
            "default_goal": "",
            "principles": [],
            "verify_commands": [],
            "max_passes": 1,
        }
    ),
    encoding="utf-8",
)
(session_dir / "session.json").write_text(
    json.dumps(
        {
            "session_id": session_id,
            "status": "promoted",
            "delta": {"changed_count": 1},
            "promotable": True,
            "promoted": True,
            "verifier_panel": {
                "ok": True,
                "quorum": quorum,
                "pass_count": pass_count,
                "critical_dissent_count": dissent,
                "votes": [],
            },
        }
    ),
    encoding="utf-8",
)
result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Latest session: {session_id} status=promoted changed=1 promotable=True"
if session_line not in result.output:
    raise SystemExit(f"missing nonce session output {session_line!r}; got: {result.output!r}")
summary = f"Verifier panel: PASS ({pass_count}/{quorum} pass, {dissent} critical dissent)"
if summary not in result.output:
    raise SystemExit(f"missing computed status output {summary!r}; got: {result.output!r}")
"""
EVOLVE_STATUS_PANEL_COUNTS_MATCH_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve


def run_case(pass_count, quorum, dissent):
    nonce = uuid.uuid4().hex[:10]
    session_id = f"panel-counts-{nonce}-{pass_count}-{quorum}-{dissent}"
    root = Path(tempfile.mkdtemp(prefix="thomas-evolve-panel-counts-"))
    (root / "thomas").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
    evolve_root = root / ".thomas" / "evolve"
    session_dir = evolve_root / "sessions" / session_id
    session_dir.mkdir(parents=True)
    (evolve_root / "charter.json").write_text(
        json.dumps(
            {
                "objective": "Panel count reconciliation check",
                "default_goal": "",
                "principles": [],
                "verify_commands": [],
                "max_passes": 1,
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "status": "promoted",
                "delta": {"changed_count": 1},
                "promotable": True,
                "promoted": True,
                "verifier_panel": {
                    "ok": dissent == 0 and pass_count >= quorum,
                    "quorum": quorum,
                    "pass_count": pass_count,
                    "critical_dissent_count": dissent,
                    "votes": [],
                },
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
    if result.exit_code:
        raise SystemExit(result.output)
    session_line = f"Latest session: {session_id} status=promoted changed=1 promotable=True"
    if session_line not in result.output:
        raise SystemExit(f"missing nonce session output {session_line!r}; got: {result.output!r}")
    expected = f"Verifier panel reconciled: votes={pass_count} quorum={quorum} dissent={dissent} (computed)"
    if expected not in result.output:
        raise SystemExit(f"missing panel reconciliation output {expected!r}; got: {result.output!r}")


run_case(5, 4, 0)
run_case(3, 4, 1)
"""
EVOLVE_STATUS_REJECTION_REASON_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"rejected-session-{nonce}"
reason = f"operator rejected ineffective candidate {nonce}"
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-rejection-reason-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
evolve_root = root / ".thomas" / "evolve"
session_dir = evolve_root / "sessions" / session_id
session_dir.mkdir(parents=True)
(evolve_root / "charter.json").write_text(
    json.dumps(
        {
            "objective": "Rejected session status check",
            "default_goal": "",
            "principles": [],
            "verify_commands": [],
            "max_passes": 1,
        }
    ),
    encoding="utf-8",
)
(session_dir / "session.json").write_text(
    json.dumps(
        {
            "session_id": session_id,
            "status": "rejected",
            "delta": {"changed_count": 1},
            "promotable": False,
            "promoted": False,
            "rejection_reason": reason,
            "session_rejections": [f"manual red-team rejection: {reason}"],
        }
    ),
    encoding="utf-8",
)
result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Latest session: {session_id} status=rejected changed=1 promotable=False"
if session_line not in result.output:
    raise SystemExit(f"missing nonce rejected-session output {session_line!r}; got: {result.output!r}")
expected_reason = f"Rejection reason: {reason}"
if expected_reason not in result.output:
    raise SystemExit(f"missing rejection reason output {expected_reason!r}; got: {result.output!r}")
"""
EVOLVE_CORPUS_SUMMARY_SCRIPT = r"""
import hashlib
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve


def write_locked_case(root, rel, payload):
    corpus = root / "evolve_corpus"
    cases = corpus / "cases"
    cases.mkdir(parents=True)
    case_path = corpus / rel
    case_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(case_path.read_bytes()).hexdigest()
    (corpus / "LOCK.json").write_text(
        json.dumps({"version": 1, "files": {rel: digest}}, sort_keys=True),
        encoding="utf-8",
    )


nonce = uuid.uuid4().hex[:10]

pass_root = Path(tempfile.mkdtemp(prefix="thomas-evolve-corpus-semantic-pass-"))
(pass_root / "thomas").mkdir()
(pass_root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
write_locked_case(
    pass_root,
    "cases/known_good_minimal.json",
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
)
pass_result = CliRunner().invoke(evolve, ["corpus", "--repo-root", str(pass_root)])
if pass_result.exit_code:
    raise SystemExit(pass_result.output)
pass_summary = "Evolve corpus: PASS (1 case(s), 0 failed, 0 lock error(s))"
if pass_summary not in pass_result.output:
    raise SystemExit(f"missing semantic corpus output {pass_summary!r}; got: {pass_result.output!r}")

fail_root = Path(tempfile.mkdtemp(prefix="thomas-evolve-corpus-semantic-fail-"))
(fail_root / "thomas").mkdir()
(fail_root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
bad_case_id = f"known_bad_nonce_{nonce}"
write_locked_case(
    fail_root,
    f"cases/{bad_case_id}.json",
    {
        "case_id": bad_case_id,
        "expected_supervisor_outcome": "eligible_for_decision_gate",
        "session": {
            "status": "ready",
            "delta": {"changed_count": 1, "changed_files": ["thomas/__init__.py"]},
            "verification": [{"source": "generated", "returncode": 1}],
            "policy_violations": [],
            "session_rejections": [],
        },
    },
)
fail_result = CliRunner().invoke(evolve, ["corpus", "--repo-root", str(fail_root)])
if fail_result.exit_code == 0:
    raise SystemExit("corpus failure fixture unexpectedly passed")
fail_summary = "Evolve corpus: FAIL (1 case(s), 1 failed, 0 lock error(s))"
if fail_summary not in fail_result.output or bad_case_id not in fail_result.output:
    raise SystemExit(f"missing nonce corpus failure output {bad_case_id!r}; got: {fail_result.output!r}")
"""
EVOLVE_RUN_ACCEPTANCE_CHECKS_SCRIPT = r"""
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

import thomas.cli.commands.evolve as evolve_module
from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"semantic-run-{nonce}"
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-run-acceptance-semantic-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")

original_run_evolve_session = evolve_module.run_evolve_session

def fake_run_evolve_session(repo_root, **kwargs):
    return {
        "ok": True,
        "session": {
            "session_id": session_id,
            "status": "ready",
            "delta": {"changed_count": 1},
            "promotable": True,
            "acceptance_checks": ["evolve_status_verifier_panel"],
        },
    }

try:
    evolve_module.run_evolve_session = fake_run_evolve_session
    result = CliRunner().invoke(
        evolve,
        [
            "run",
            "--repo-root",
            str(root),
            "--goal",
            "Semantic run output check",
            "--acceptance-check",
            "status-verifier-panel",
        ],
    )
finally:
    evolve_module.run_evolve_session = original_run_evolve_session

if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Evolve session: {session_id}"
if session_line not in result.output:
    raise SystemExit(f"missing nonce run output {session_line!r}; got: {result.output!r}")
expected_acceptance = "Acceptance checks: evolve_status_verifier_panel"
if expected_acceptance not in result.output:
    raise SystemExit(f"missing semantic run output {expected_acceptance!r}; got: {result.output!r}")
"""
EVOLVE_STATUS_REPAIR_SUMMARY_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"semantic-repair-{nonce}"
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-status-repair-semantic-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
evolve_root = root / ".thomas" / "evolve"
session_dir = evolve_root / "sessions" / session_id
session_dir.mkdir(parents=True)
(evolve_root / "charter.json").write_text(
    json.dumps(
        {
            "objective": "Semantic repair check",
            "default_goal": "",
            "principles": [],
            "verify_commands": [],
            "max_passes": 1,
        }
    ),
    encoding="utf-8",
)
(session_dir / "session.json").write_text(
    json.dumps(
        {
            "session_id": session_id,
            "status": "promoted",
            "delta": {"changed_count": 1},
            "promotable": True,
            "promoted": True,
            "verification_repair_attempted": True,
            "verification_repair_failures": [
                {
                    "source": "acceptance",
                    "acceptance_check": "evolve_status_repair_summary",
                    "returncode": 1,
                }
            ],
        }
    ),
    encoding="utf-8",
)
result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Latest session: {session_id} status=promoted changed=1 promotable=True"
if session_line not in result.output:
    raise SystemExit(f"missing nonce repair-session output {session_line!r}; got: {result.output!r}")
expected_repair = "Verification repair: attempted"
if expected_repair not in result.output:
    raise SystemExit(f"missing semantic repair status output {expected_repair!r}; got: {result.output!r}")
"""
EVOLVE_STATUS_REPAIR_ARTIFACTS_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"semantic-repair-artifacts-{nonce}"
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-status-repair-artifacts-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
evolve_root = root / ".thomas" / "evolve"
session_dir = evolve_root / "sessions" / session_id
artifact_dir = session_dir / "verification-repair"
artifact_dir.mkdir(parents=True)
artifact_path = artifact_dir / "failure-01-acceptance-evolve_status_repair_artifacts.txt"
artifact_path.write_text("stderr:\nmissing artifact count\n", encoding="utf-8")
(evolve_root / "charter.json").write_text(
    json.dumps(
        {
            "objective": "Semantic repair artifact check",
            "default_goal": "",
            "principles": [],
            "verify_commands": [],
            "max_passes": 1,
        }
    ),
    encoding="utf-8",
)
(session_dir / "session.json").write_text(
    json.dumps(
        {
            "session_id": session_id,
            "status": "promoted",
            "delta": {"changed_count": 1},
            "promotable": True,
            "promoted": True,
            "verification_repair_attempted": True,
            "verification_repair_artifacts": [
                {
                    "path": str(artifact_path),
                    "json_path": str(artifact_path.with_suffix(".json")),
                    "source": "acceptance",
                    "acceptance_check": "evolve_status_repair_artifacts",
                }
            ],
        }
    ),
    encoding="utf-8",
)
result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Latest session: {session_id} status=promoted changed=1 promotable=True"
if session_line not in result.output:
    raise SystemExit(f"missing nonce repair-artifacts output {session_line!r}; got: {result.output!r}")
expected_artifact_count = "Verification repair artifacts: 1"
if expected_artifact_count not in result.output:
    raise SystemExit(f"missing semantic repair artifact output {expected_artifact_count!r}; got: {result.output!r}")
"""
EVOLVE_STATUS_REPAIR_ARTIFACT_PATH_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"semantic-repair-artifact-path-{nonce}"
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-status-repair-artifact-path-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
evolve_root = root / ".thomas" / "evolve"
session_dir = evolve_root / "sessions" / session_id
artifact_rel = Path("verification-repair") / f"failure-01-acceptance-evolve_status_repair_artifact_path_{nonce}.txt"
artifact_path = session_dir / artifact_rel
artifact_path.parent.mkdir(parents=True)
artifact_path.write_text("stderr:\nmissing stable artifact path\n", encoding="utf-8")
(evolve_root / "charter.json").write_text(
    json.dumps(
        {
            "objective": "Semantic repair artifact path check",
            "default_goal": "",
            "principles": [],
            "verify_commands": [],
            "max_passes": 1,
        }
    ),
    encoding="utf-8",
)
(session_dir / "session.json").write_text(
    json.dumps(
        {
            "session_id": session_id,
            "status": "promoted",
            "delta": {"changed_count": 1},
            "promotable": True,
            "promoted": True,
            "verification_repair_attempted": True,
            "verification_repair_artifacts": [
                {
                    "path": str(artifact_path),
                    "json_path": str(artifact_path.with_suffix(".json")),
                    "source": "acceptance",
                    "acceptance_check": "evolve_status_repair_artifact_path",
                }
            ],
        }
    ),
    encoding="utf-8",
)
result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Latest session: {session_id} status=promoted changed=1 promotable=True"
if session_line not in result.output:
    raise SystemExit(f"missing nonce repair-artifact-path output {session_line!r}; got: {result.output!r}")
expected_artifact_path = (
    "Verification repair artifact: "
    f"verification-repair/failure-01-acceptance-evolve_status_repair_artifact_path_{nonce}.txt"
)
if expected_artifact_path not in result.output:
    raise SystemExit(f"missing semantic repair artifact path output {expected_artifact_path!r}; got: {result.output!r}")
if str(artifact_path) in result.output:
    raise SystemExit(f"repair artifact path should be relative, got absolute path in output: {result.output!r}")
"""
EVOLVE_STATUS_VERIFICATION_OUTPUT_ARTIFACTS_SCRIPT = r"""
import json
import tempfile
import uuid
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve

nonce = uuid.uuid4().hex[:10]
session_id = f"semantic-verification-output-artifacts-{nonce}"
root = Path(tempfile.mkdtemp(prefix="thomas-evolve-status-verification-output-artifacts-"))
(root / "thomas").mkdir()
(root / "pyproject.toml").write_text('[project]\nname="thomas"\nversion="0.0.0"\n', encoding="utf-8")
evolve_root = root / ".thomas" / "evolve"
session_dir = evolve_root / "sessions" / session_id
output_dir = session_dir / "verification-output" / "initial"
output_dir.mkdir(parents=True)
stdout_path = output_dir / "01-acceptance-output.stdout.txt"
stderr_path = output_dir / "01-acceptance-output.stderr.txt"
stdout_path.write_text("full stdout evidence\n", encoding="utf-8")
stderr_path.write_text("full stderr evidence\n", encoding="utf-8")
(evolve_root / "charter.json").write_text(
    json.dumps(
        {
            "objective": "Semantic verification output artifact check",
            "default_goal": "",
            "principles": [],
            "verify_commands": [],
            "max_passes": 1,
        }
    ),
    encoding="utf-8",
)
(session_dir / "session.json").write_text(
    json.dumps(
        {
            "session_id": session_id,
            "status": "promoted",
            "delta": {"changed_count": 1},
            "promotable": True,
            "promoted": True,
            "verification": [
                {
                    "source": "acceptance",
                    "acceptance_check": "evolve_status_verification_output_artifacts",
                    "returncode": 0,
                    "stdout_artifact": {"path": str(stdout_path), "bytes": 21, "sha256": "stdout"},
                    "stderr_artifact": {"path": str(stderr_path), "bytes": 21, "sha256": "stderr"},
                }
            ],
        }
    ),
    encoding="utf-8",
)
result = CliRunner().invoke(evolve, ["status", "--repo-root", str(root)])
if result.exit_code:
    raise SystemExit(result.output)
session_line = f"Latest session: {session_id} status=promoted changed=1 promotable=True"
if session_line not in result.output:
    raise SystemExit(f"missing nonce verification-output output {session_line!r}; got: {result.output!r}")
expected_output_artifacts = "Verification output artifacts: 2"
if expected_output_artifacts not in result.output:
    raise SystemExit(f"missing verification output artifact summary {expected_output_artifacts!r}; got: {result.output!r}")
"""
EVOLVE_PLANNER_BUILTINS_EVAL_ALIAS_SCRIPT = r"""
from thomas.forge.anvil import evolve_planner_detectors as detectors

samples = {
    "from-import alias": "from builtins import eval as run_eval\nrun_eval(expr)\n",
    "getattr imported builtins": "import builtins\ngetattr(builtins, 'eval')(expr)\n",
    "getattr imported builtins alias": "import builtins as bi\ngetattr(bi, 'eval')(expr)\n",
    "getattr __import__ builtins": "getattr(__import__('builtins'), 'eval')(expr)\n",
    "getattr __builtins__": "getattr(__builtins__, 'eval')(expr)\n",
    "__builtins__ subscript": "__builtins__['eval'](expr)\n",
}
failures = []
for label, sample in samples.items():
    count = detectors._count_security_markers_in_source(sample)
    if count != 1:
        failures.append(f"{label}: expected 1, got {count}")
if failures:
    raise SystemExit("builtins eval alias marker count mismatch: " + "; ".join(failures))
print("planner builtins eval alias: PASS")
"""
ACCEPTANCE_CHECK_ALIASES = {
    "status_verifier_panel": "evolve_status_verifier_panel",
    "verifier_panel_status": "evolve_status_verifier_panel",
    "status_panel_counts_match": "evolve_status_panel_counts_match",
    "panel_counts_match": "evolve_status_panel_counts_match",
    "status_rejection_reason": "evolve_status_rejection_reason",
    "rejection_reason_status": "evolve_status_rejection_reason",
    "planner_builtins_eval_alias": "evolve_planner_builtins_eval_alias",
    "builtins_eval_alias": "evolve_planner_builtins_eval_alias",
    "corpus_summary": "evolve_corpus_summary",
    "evolve_corpus_human_summary": "evolve_corpus_summary",
    "run_acceptance_checks": "evolve_run_acceptance_checks",
    "evolve_run_acceptance": "evolve_run_acceptance_checks",
    "status_repair_summary": "evolve_status_repair_summary",
    "evolve_status_repair": "evolve_status_repair_summary",
    "status_repair_artifacts": "evolve_status_repair_artifacts",
    "evolve_status_repair_artifact_count": "evolve_status_repair_artifacts",
    "status_repair_artifact_path": "evolve_status_repair_artifact_path",
    "evolve_status_repair_artifact_paths": "evolve_status_repair_artifact_path",
    "status_verification_output_artifacts": "evolve_status_verification_output_artifacts",
    "verification_output_artifacts": "evolve_status_verification_output_artifacts",
}
SEMANTIC_ACCEPTANCE_CHECKS = {
    "evolve_status_verifier_panel": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_VERIFIER_PANEL_SCRIPT],
        "description": "evolve status verifier-panel output",
    },
    "evolve_status_panel_counts_match": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_PANEL_COUNTS_MATCH_SCRIPT],
        "description": "evolve status verifier-panel computed count reconciliation",
    },
    "evolve_status_rejection_reason": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_REJECTION_REASON_SCRIPT],
        "description": "evolve status rejection reason output",
    },
    "evolve_planner_builtins_eval_alias": {
        "command": [sys.executable, "-c", EVOLVE_PLANNER_BUILTINS_EVAL_ALIAS_SCRIPT],
        "description": "evolve planner builtins eval alias detection",
    },
    "evolve_corpus_summary": {
        "command": [sys.executable, "-c", EVOLVE_CORPUS_SUMMARY_SCRIPT],
        "description": "evolve corpus human-readable summary",
    },
    "evolve_run_acceptance_checks": {
        "command": [sys.executable, "-c", EVOLVE_RUN_ACCEPTANCE_CHECKS_SCRIPT],
        "description": "evolve run acceptance-check output",
    },
    "evolve_status_repair_summary": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_REPAIR_SUMMARY_SCRIPT],
        "description": "evolve status verification-repair output",
    },
    "evolve_status_repair_artifacts": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_REPAIR_ARTIFACTS_SCRIPT],
        "description": "evolve status verification-repair artifact output",
    },
    "evolve_status_repair_artifact_path": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_REPAIR_ARTIFACT_PATH_SCRIPT],
        "description": "evolve status verification-repair artifact path output",
    },
    "evolve_status_verification_output_artifacts": {
        "command": [sys.executable, "-c", EVOLVE_STATUS_VERIFICATION_OUTPUT_ARTIFACTS_SCRIPT],
        "description": "evolve status verification-output artifact summary",
    },
}


def _normalize_acceptance_check(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = raw.lower().replace("-", "_").replace(".", "_").replace(":", "_")
    return ACCEPTANCE_CHECK_ALIASES.get(key, key)


def _normalize_acceptance_checks(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = []
    checks: list[str] = []
    seen: set[str] = set()
    for item in items:
        check = _normalize_acceptance_check(item)
        if check and check not in seen:
            checks.append(check)
            seen.add(check)
    return checks


def _semantic_check_entry(check_id: str, *, source: str) -> dict[str, Any]:
    check = SEMANTIC_ACCEPTANCE_CHECKS.get(check_id)
    if not check:
        return {
            "command": [sys.executable, "-c", UNKNOWN_ACCEPTANCE_CHECK_SCRIPT, check_id],
            "source": "acceptance_unknown",
            "description": f"unknown evolve acceptance check: {check_id}",
            "acceptance_check": check_id,
        }
    return {
        "command": list(check["command"]),
        "source": source,
        "description": str(check["description"]),
        "acceptance_check": check_id,
    }


def _acceptance_verify_plan(acceptance_checks: Any) -> tuple[list[dict[str, Any]], set[str]]:
    plan: list[dict[str, Any]] = []
    check_ids: set[str] = set()
    for check_id in _normalize_acceptance_checks(acceptance_checks):
        plan.append(_semantic_check_entry(check_id, source="acceptance"))
        check_ids.add(check_id)
    return plan, check_ids


def _truncate(text: str, limit: int = 6000) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "\n...[truncated]"


def _blast_radius_tests(changed_py: list[str], repo_root: Path) -> list[str]:
    """Return bounded tests that import any changed Python modules."""
    return select_blast_radius_tests(changed_py, repo_root, max_files=MAX_BLAST_RADIUS_TEST_FILES)


def _rejected_verify_command(command: str, reason: str) -> list[str]:
    message = f"unsafe charter verify command rejected: {reason}: {_truncate(command, limit=240)}"
    return [
        sys.executable,
        "-c",
        REJECTED_VERIFY_SCRIPT,
        message,
    ]


def _normalize_verify_command(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return [str(part) for part in command]
    raw = str(command or "").strip()
    if not raw:
        return _rejected_verify_command(str(command or ""), "empty command")
    if any(char in raw for char in SHELL_VERIFY_METACHARS):
        return _rejected_verify_command(raw, "shell metacharacter")
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError as exc:
        return _rejected_verify_command(raw, f"parse error: {exc}")
    if not parts:
        return _rejected_verify_command(raw, "empty command")
    executable = Path(parts[0]).name.lower()
    if executable in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
        parts[0] = sys.executable
    return parts


def _is_rejected_verify_command(command: list[str]) -> bool:
    return len(command) >= 3 and command[1] == "-c" and command[2] == REJECTED_VERIFY_SCRIPT


def _semantic_cli_verify_plan(
    goal: str,
    delta: dict[str, Any],
    *,
    skip_check_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    changed = {str(rel).replace("\\", "/") for rel in (delta.get("changed_files") or [])}
    goal_text = str(goal or "").lower()
    skipped = skip_check_ids or set()
    plan: list[dict[str, Any]] = []
    if "thomas/cli/commands/evolve.py" in changed:
        if "status" in goal_text and ("verifier panel" in goal_text or "verifier_panel" in goal_text):
            check_id = "evolve_status_verifier_panel"
            if check_id not in skipped:
                plan.append(_semantic_check_entry(check_id, source="semantic"))
        if "status" in goal_text and ("rejection reason" in goal_text or "rejected" in goal_text):
            check_id = "evolve_status_rejection_reason"
            if check_id not in skipped:
                plan.append(_semantic_check_entry(check_id, source="semantic"))
        if "corpus" in goal_text and (
            "human-readable" in goal_text or "failed" in goal_text or "lock error" in goal_text
        ):
            check_id = "evolve_corpus_summary"
            if check_id not in skipped:
                plan.append(_semantic_check_entry(check_id, source="semantic"))
    if "thomas/forge/anvil/evolve_planner_detectors.py" in changed and "builtins" in goal_text and "eval" in goal_text:
        check_id = "evolve_planner_builtins_eval_alias"
        if check_id not in skipped:
            plan.append(_semantic_check_entry(check_id, source="semantic"))
    return plan


def _build_verify_plan(
    charter: Any,
    delta: dict[str, Any],
    repo_root: Path,
    *,
    goal: str = "",
    acceptance_checks: Any = None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    changed_py = [rel for rel in (delta.get("changed_files") or []) if str(rel).endswith(".py")]
    if changed_py:
        plan.append({"command": [sys.executable, "-m", "py_compile", *changed_py], "source": "generated"})
        plan.append(
            {
                "command": [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--select",
                    "F401,F821,F841",
                    *changed_py,
                ],
                "source": "generated",
                "description": "ruff changed-python hygiene",
            }
        )
        plan.append(
            {
                "command": [sys.executable, "-c", PYTHON_SEMANTIC_DELTA_SCRIPT, *changed_py],
                "source": "generated",
                "description": "python semantic delta",
            }
        )
        blast = _blast_radius_tests(changed_py, repo_root)
        if blast:
            plan.append(
                {
                    "command": [sys.executable, "-m", "pytest", *blast, "-q", "-p", "no:cacheprovider"],
                    "source": "generated",
                }
            )
    acceptance_plan, explicit_check_ids = _acceptance_verify_plan(acceptance_checks)
    plan.extend(acceptance_plan)
    plan.extend(_semantic_cli_verify_plan(goal, delta, skip_check_ids=explicit_check_ids))
    for cmd in charter.verify_commands:
        if str(cmd).strip():
            command = _normalize_verify_command(cmd)
            source = "charter_unsafe" if _is_rejected_verify_command(command) else "charter"
            plan.append({"command": command, "source": source})
    return plan


def _build_verify_commands(
    charter: Any,
    delta: dict[str, Any],
    repo_root: Path,
    *,
    goal: str = "",
    acceptance_checks: Any = None,
) -> list[str | list[str]]:
    return [
        entry["command"]
        for entry in _build_verify_plan(charter, delta, repo_root, goal=goal, acceptance_checks=acceptance_checks)
    ]


def _verification_skipped_reason(
    *,
    agent_failed: bool,
    policy_violations: list[str],
    session_rejections: list[str],
    verification_floor_failures: list[str],
    delta: dict[str, Any],
) -> str:
    if agent_failed:
        return "agent pass failed before verification"
    if policy_violations:
        return "protected path tamper detected before verification: " + ", ".join(policy_violations[:8])
    if session_rejections:
        return "session rejected before verification: " + "; ".join(session_rejections[:4])
    if verification_floor_failures:
        return "verification floor failed before subprocess verification: " + "; ".join(verification_floor_failures[:4])
    if int(delta.get("changed_count") or 0) <= 0:
        return "no candidate changes before verification"
    return ""


def _run_verification_plan(
    paths: Any,
    *,
    verify_root: Path,
    verify_plan: list[dict[str, Any]],
    timeout_seconds: int,
    artifact_dir: Path | None = None,
    prepare_verification_root: Any,
    evolve_child_env: Any,
    run_exec: Any,
    strip_evolve_verification_env: Any,
) -> list[dict[str, Any]]:
    if not verify_plan:
        return []
    verify_env = evolve_child_env()
    verify_env["PYTHONPATH"] = str(verify_root)
    strip_evolve_verification_env(verify_env)
    verify_env["THOMAS_EVOLVE_BLUE_ROOT"] = str(paths.blue_root)
    baseline_verify_root = prepare_verification_root(paths, source_root=paths.blue_root, dirname="verify-blue")
    baseline_verify_env = evolve_child_env()
    baseline_verify_env["PYTHONPATH"] = str(baseline_verify_root)
    strip_evolve_verification_env(baseline_verify_env)
    baseline_verify_env["THOMAS_EVOLVE_BLUE_ROOT"] = str(paths.blue_root)
    verification: list[dict[str, Any]] = []
    output_root = Path(artifact_dir) if artifact_dir is not None else None
    for index, entry in enumerate(verify_plan, start=1):
        command = entry["command"]
        source = str(entry.get("source") or "generated")
        check = str(entry.get("acceptance_check") or entry.get("description") or "verify")
        prefix = f"{index:02d}-{_artifact_slug(source, fallback='verify')}-{_artifact_slug(check, fallback='check')}"
        command_env = dict(verify_env)
        if output_root is not None:
            command_env["THOMAS_EVOLVE_EXEC_OUTPUT_DIR"] = str(output_root)
            command_env["THOMAS_EVOLVE_EXEC_OUTPUT_PREFIX"] = prefix
        result = run_exec(command, cwd=verify_root, env=command_env, timeout_seconds=timeout_seconds)
        result["source"] = str(entry.get("source") or "generated")
        if entry.get("description"):
            result["description"] = str(entry.get("description"))
        if entry.get("acceptance_check"):
            result["acceptance_check"] = str(entry.get("acceptance_check"))
        if result["source"] == "charter":
            baseline_env = dict(baseline_verify_env)
            if output_root is not None:
                baseline_env["THOMAS_EVOLVE_EXEC_OUTPUT_DIR"] = str(output_root)
                baseline_env["THOMAS_EVOLVE_EXEC_OUTPUT_PREFIX"] = f"{prefix}-baseline"
            baseline = run_exec(
                command,
                cwd=baseline_verify_root,
                env=baseline_env,
                timeout_seconds=timeout_seconds,
            )
            result["baseline_returncode"] = int(baseline.get("returncode") or 0)
            result["baseline_stdout_tail"] = baseline.get("stdout_tail", "")
            result["baseline_stderr_tail"] = baseline.get("stderr_tail", "")
            result["baseline_timed_out"] = bool(baseline.get("timed_out"))
            result["baseline_command"] = baseline.get("command", result.get("command", ""))
            if baseline.get("stdout_artifact"):
                result["baseline_stdout_artifact"] = baseline.get("stdout_artifact")
            if baseline.get("stderr_artifact"):
                result["baseline_stderr_artifact"] = baseline.get("stderr_artifact")
        verification.append(result)
    return verification


def _verification_result_blocks_promotion(item: dict[str, Any]) -> bool:
    if int(item.get("returncode") or 0) == 0:
        return False
    if str(item.get("source") or "") == "charter" and int(item.get("baseline_returncode") or 0) != 0:
        return False
    return True


def _repairable_verification_failures(verification: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repairable_sources = {"acceptance"}
    return [
        dict(item)
        for item in verification
        if str(item.get("source") or "") in repairable_sources and _verification_result_blocks_promotion(item)
    ]


def _brief_failure_text(value: Any, *, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _artifact_slug(value: Any, *, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return (slug or fallback)[:80]


def _render_verification_failure_artifact(item: dict[str, Any]) -> str:
    lines = [
        f"source: {item.get('source') or 'n/a'}",
        f"acceptance_check: {item.get('acceptance_check') or 'n/a'}",
        f"description: {item.get('description') or 'n/a'}",
        f"returncode: {item.get('returncode')}",
        f"timed_out: {bool(item.get('timed_out'))}",
        f"command: {item.get('command') or ''}",
        "",
        "stdout:",
        str(item.get("stdout_tail") or ""),
        "",
        "stderr:",
        str(item.get("stderr_tail") or ""),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _write_verification_repair_artifacts(
    session_dir: Path,
    failures: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not failures:
        return []
    artifact_dir = session_dir / "verification-repair"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, str]] = []
    for index, item in enumerate(failures, start=1):
        source = _artifact_slug(item.get("source"), fallback="verification")
        check = _artifact_slug(item.get("acceptance_check"), fallback="failure")
        stem = f"failure-{index:02d}-{source}-{check}"
        text_path = artifact_dir / f"{stem}.txt"
        json_path = artifact_dir / f"{stem}.json"
        text_path.write_text(_render_verification_failure_artifact(item), encoding="utf-8")
        json_path.write_text(json.dumps(item, ensure_ascii=True, indent=2), encoding="utf-8")
        artifacts.append(
            {
                "path": str(text_path),
                "json_path": str(json_path),
                "source": str(item.get("source") or ""),
                "acceptance_check": str(item.get("acceptance_check") or ""),
            }
        )
    return artifacts


def _build_verification_failure_repair_goal(
    goal: str,
    failures: list[dict[str, Any]],
    *,
    artifacts: list[dict[str, str]] | None = None,
) -> str:
    lines = [
        "The previous evolve attempt made an eligible diff, but an explicit semantic acceptance verifier failed.",
        "Make one focused repair to the existing diff so the same verifier passes.",
        "Do not broaden scope, do not edit tests, and do not edit the verifier or any guardrail.",
        "If the verifier says a specific output string is missing, make the product output include that string exactly.",
        "When the expected text includes a path, preserve its slash style and relative/absolute form exactly.",
        f"Original goal: {goal}",
        "",
        "Failing verifier evidence:",
    ]
    artifact_rows = artifacts or []
    for index, item in enumerate(failures[:3]):
        lines.append(
            "- "
            f"source={item.get('source')} "
            f"acceptance_check={item.get('acceptance_check') or 'n/a'} "
            f"description={item.get('description') or 'n/a'} "
            f"returncode={item.get('returncode')}"
        )
        if index < len(artifact_rows) and artifact_rows[index].get("path"):
            lines.append(f"  artifact: {artifact_rows[index]['path']}")
        stderr = _brief_failure_text(item.get("stderr_tail"))
        stdout = _brief_failure_text(item.get("stdout_tail"))
        if stderr:
            lines.append(f"  stderr: {stderr}")
        if stdout:
            lines.append(f"  stdout: {stdout}")
    lines.extend(
        [
            "",
            "After the repair, run the narrowest relevant local check yourself if possible, then stop.",
        ]
    )
    return "\n".join(lines).strip()


def _verification_floor_failures(
    delta: dict[str, Any],
    repo_root: Path,
    *,
    blue_root: Path | None = None,
) -> list[str]:
    changed_py = [str(rel) for rel in (delta.get("changed_files") or []) if str(rel).endswith(".py")]
    if not changed_py:
        return []
    return execution_coverage_failures(
        changed_py,
        blue_root=Path(blue_root or repo_root),
        candidate_root=Path(repo_root),
    )
