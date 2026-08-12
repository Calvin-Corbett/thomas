"""Run the fail-closed Thomas-to-ChatGPT capability convergence evaluation."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from chatgpt_parity_harness import (
    EvidenceRow,
    load_rubric,
    preserve_workspace_paths,
    ranked_gaps,
    score_families,
    validate_evidence_provenance,
    write_jsonl,
)
from chatgpt_parity_probes import ProbeContext, collect_evidence
from chatgpt_parity_provenance import (
    _build_provenance,
    _normalized_selected_rubric,
    _public_base_url,
    _runtime_attribution,
    _sha256_bytes,
)
from chatgpt_parity_provenance import (
    _runtime_tree_sha256 as _provenance_runtime_tree_sha256,
)

DEFAULT_RUBRIC = _REPO_ROOT / "plans" / "thomas" / "chatgpt_parity" / "CAPABILITY_RUBRIC.json"
DEFAULT_OUTPUT = _REPO_ROOT / "plans" / "thomas" / "chatgpt_parity"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
LIVE_PROBE_SIDE_EFFECT_PATHS = (
    "agentic_report.md",
    "cleaned_data.csv",
    "conflict_report.md",
    "grounded_report.md",
    "audit_manifest.json",
    "cleaned_snapshot.csv",
    "index.html",
    "thomas/server/plugins_registry/api_keys.json",
)


def _render_rubric(rubric: dict[str, Any]) -> str:
    lines = [
        "# Thomas vs. Current ChatGPT Capability Rubric",
        "",
        f"- Target date: `{rubric['as_of']}`",
        f"- Schema: `{rubric['schema_version']}`",
        "- Completion rule: every family must score 4/4; averages never waive a missing family.",
        "",
        "## Evidence Levels",
        "",
    ]
    for tier in (0, 1, 2, 3, 4):
        lines.append(f"- **{tier}** — {rubric['scoring'][str(tier)]}")
    lines.extend(["", "## Official Target Sources", ""])
    lines.extend(f"- {url}" for url in rubric["source_urls"])
    lines.extend(["", "## Capability Families", ""])
    for family in rubric["families"]:
        critical = " — critical floor" if family.get("critical") else ""
        lines.append(f"### {family['name']} (`{family['id']}`, weight {family['weight']:.2f}){critical}")
        lines.append("")
        lines.extend(f"- {behavior}" for behavior in family["behaviors"])
        lines.append("")
        for tier in (1, 2, 3, 4):
            kinds = ", ".join(str(check.get("probe") or check.get("kind")) for check in family["tiers"][str(tier)])
            lines.append(f"- Tier {tier} evidence: {kinds}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_gaps(rubric: dict[str, Any], scorecard: dict[str, Any]) -> str:
    gaps = ranked_gaps(rubric, scorecard)
    completion_label = "Selected scope achieved" if scorecard.get("coverage") == "targeted" else "Parity achieved"
    lines = [
        "# ChatGPT Parity Gap Ledger",
        "",
        f"- Target as of: `{scorecard['target_as_of']}`",
        f"- Parity index: **{scorecard['parity_index']}/100**",
        f"- Families at adversarial proof: **{scorecard['totals']['families_at_4']}/{scorecard['totals']['families']}**",
        f"- {completion_label}: **{str(scorecard.get('selected_scope_achieved', scorecard['parity_achieved'])).lower()}**",
        "",
        "A family is complete only at 4/4. The next fix is the highest-priority first failed tier, not the easiest green check.",
        "",
        "## Ranked Gaps",
        "",
    ]
    for number, gap in enumerate(gaps, 1):
        floor = "critical" if gap["critical"] else "standard"
        lines.append(
            f"{number}. **{gap['name']}** — {gap['score']}/4; first failed tier {gap['first_failed_tier']}; "
            f"weight {gap['weight']:.2f}; {floor}"
        )
        failed_at_tier = [row for row in gap["failed_checks"] if int(row["tier"]) == int(gap["first_failed_tier"])]
        for row in failed_at_tier[:4]:
            lines.append(f"   - `{row['case']}`: {row['actual']}")
    if not gaps:
        if scorecard.get("coverage") == "targeted":
            lines.append("No gaps remain in the selected scope.")
        else:
            lines.append("No gaps remain; every family has adversarial live proof.")
    return "\n".join(lines).rstrip() + "\n"


def _runtime_tree_sha256() -> str:
    return _provenance_runtime_tree_sha256(_REPO_ROOT)


def _write_run_bundle(
    output_dir: Path,
    *,
    run_id: str,
    provenance: dict[str, Any],
    rows: list[EvidenceRow],
    scorecard: dict[str, Any],
    rubric_markdown: str,
    gap_markdown: str,
) -> tuple[Path, dict[str, Any]]:
    runs_dir = output_dir / "runs"
    bundle_dir = runs_dir / run_id
    if bundle_dir.exists():
        raise FileExistsError(f"parity run id already exists: {run_id}")
    runs_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{run_id}.", dir=runs_dir) as temporary_root:
        staged_bundle = Path(temporary_root) / run_id
        staged_bundle.mkdir()
        write_jsonl(staged_bundle / "evidence.jsonl", rows)
        (staged_bundle / "scorecard.json").write_text(
            json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (staged_bundle / "RUBRIC.md").write_text(rubric_markdown, encoding="utf-8")
        (staged_bundle / "GAP_LEDGER.md").write_text(gap_markdown, encoding="utf-8")
        artifact_names = ("evidence.jsonl", "scorecard.json", "RUBRIC.md", "GAP_LEDGER.md")
        manifest = {
            **provenance,
            "artifacts": {name: _sha256_bytes((staged_bundle / name).read_bytes()) for name in artifact_names},
        }
        (staged_bundle / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        staged_bundle.replace(bundle_dir)
    return bundle_dir, manifest


def _publish_canonical(
    output_dir: Path,
    *,
    bundle_dir: Path,
    manifest: dict[str, Any],
) -> None:
    lock_path = output_dir / ".canonical-publish.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"canonical parity publication is already locked: {lock_path}") from exc
    os.close(lock_fd)
    try:
        with tempfile.TemporaryDirectory(prefix=".canonical-stage.", dir=output_dir) as temporary_root:
            stage = Path(temporary_root)
            projections = {
                "latest_evidence.jsonl": "evidence.jsonl",
                "RUBRIC.md": "RUBRIC.md",
                "GAP_LEDGER.md": "GAP_LEDGER.md",
                "latest_scorecard.json": "scorecard.json",
            }
            for target_name, source_name in projections.items():
                (stage / target_name).write_bytes((bundle_dir / source_name).read_bytes())
            pointer = {
                "schema_version": "thomas-chatgpt-parity-latest-v1",
                "run_id": manifest["run_id"],
                "provenance_id": manifest["provenance_id"],
                "bundle_dir": f"runs/{manifest['run_id']}",
                "artifacts": manifest["artifacts"],
            }
            (stage / "latest_run.json").write_text(
                json.dumps(pointer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            for target_name in ("latest_evidence.jsonl", "RUBRIC.md", "GAP_LEDGER.md", "latest_scorecard.json"):
                (stage / target_name).replace(output_dir / target_name)
            (stage / "latest_run.json").replace(output_dir / "latest_run.json")
    finally:
        lock_path.unlink()


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not RUN_ID_PATTERN.fullmatch(str(args.run_id)):
        raise ValueError("run id must be 1-128 characters using letters, numbers, dot, underscore, or hyphen")
    rubric_path = Path(args.rubric).resolve()
    output_dir = Path(args.output_dir).resolve()
    bundle_dir = output_dir / "runs" / str(args.run_id)
    if bundle_dir.exists():
        raise FileExistsError(f"parity run id already exists: {args.run_id}")
    rubric = load_rubric(rubric_path)
    context = ProbeContext(
        repo_root=_REPO_ROOT,
        base_url=args.base_url,
        profile=args.profile,
        model_id=args.model_id,
        run_tests=bool(args.run_tests),
        timeout_seconds=float(args.timeout_seconds),
    )
    selected = set(args.family or [])
    known = {family["id"] for family in rubric["families"]}
    unknown = sorted(selected - known)
    if unknown:
        raise ValueError(f"unknown capability families: {unknown}")
    selected_rubric = _normalized_selected_rubric(rubric, selected)
    generated_at = datetime.now(UTC).isoformat()
    with preserve_workspace_paths(_REPO_ROOT, LIVE_PROBE_SIDE_EFFECT_PATHS):
        raw_rows = collect_evidence(selected_rubric, context)
    runtime_attribution = _runtime_attribution(context, profile=args.profile, model_id=args.model_id)
    provenance = _build_provenance(
        args=args,
        rubric_path=rubric_path,
        selected=selected,
        generated_at=generated_at,
        runtime_attribution=runtime_attribution,
    )
    rows = [replace(row, provenance_id=str(provenance["provenance_id"])) for row in raw_rows]
    validate_evidence_provenance(rows, required=True)
    scorecard = score_families(selected_rubric, rows, require_provenance=True)
    selected_scope_achieved = bool(scorecard["parity_achieved"])
    scorecard.update(
        {
            "run_id": args.run_id,
            "generated_at": generated_at,
            "base_url": _public_base_url(args.base_url),
            "profile": args.profile,
            "model_id": args.model_id,
            "tests_executed": bool(args.run_tests),
            "selected_families": sorted(selected) if selected else ["all"],
            "coverage": provenance["coverage"],
            "provenance_id": provenance["provenance_id"],
            "selected_scope_achieved": selected_scope_achieved,
            "parity_claimable": bool(
                not selected and selected_scope_achieved and runtime_attribution["status"] == "verified"
            ),
            "bundle_dir": f"runs/{args.run_id}",
            "runtime_attribution": runtime_attribution,
        }
    )
    if selected:
        scorecard["parity_achieved"] = False
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_rubric = _render_rubric(selected_rubric)
    rendered_gaps = _render_gaps(selected_rubric, scorecard)
    bundle_dir, manifest = _write_run_bundle(
        output_dir,
        run_id=args.run_id,
        provenance=provenance,
        rows=rows,
        scorecard=scorecard,
        rubric_markdown=rendered_rubric,
        gap_markdown=rendered_gaps,
    )
    if not selected:
        _publish_canonical(output_dir, bundle_dir=bundle_dir, manifest=manifest)
    return scorecard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--base-url", default="http://127.0.0.1:8908")
    parser.add_argument("--profile", default="local")
    parser.add_argument("--model-id", default="qwen2.5-coder:7b")
    parser.add_argument("--run-id", default=f"manual-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--family", action="append", help="Evaluate one family in an isolated targeted run")
    parser.add_argument("--require-parity", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scorecard = run(args)
    totals = scorecard["totals"]
    print(
        f"{'Targeted parity scope' if scorecard['coverage'] == 'targeted' else 'ChatGPT parity'}: "
        f"{scorecard['parity_index']}/100; "
        f"families at 4/4: {totals['families_at_4']}/{totals['families']}; "
        f"critical failures: {totals['critical_failures']}"
    )
    print(f"Global parity claimable: {scorecard['parity_claimable']}")
    if args.require_parity and not scorecard["parity_claimable"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
