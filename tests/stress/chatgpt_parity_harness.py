"""Evidence and scoring contract for the ChatGPT capability parity loop."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from thomas.server.model_runtime_receipt import sanitize_model_runtime_trace, validate_model_runtime_receipt

SCHEMA_VERSION = "thomas-chatgpt-parity-v1"
TIERS = (1, 2, 3, 4)
SEVERITIES = {"low", "med", "high", "critical"}


def _runtime_cache(context: Any) -> dict[str, Any]:
    cache = getattr(context, "runtime_cache", None)
    if cache is None:
        cache = {}
        context.runtime_cache = cache
    if not isinstance(cache, dict):
        raise TypeError("probe runtime_cache must be a dictionary")
    return cache


def _store_model_runtime(context: Any, runtime: dict[str, Any], *, execution_id: str = "") -> bool:
    validated = validate_model_runtime_receipt(runtime)
    safe_receipt = validated or sanitize_model_runtime_trace(runtime)
    if execution_id:
        safe_receipt["execution_id"] = execution_id
    receipts = _runtime_cache(context).setdefault("model_runtime_receipts", [])
    if not isinstance(receipts, list):
        raise TypeError("model_runtime_receipts must be a list")
    receipts.append(safe_receipt)
    return validated is not None


def record_model_runtime_event(context: Any, event: Any) -> bool:
    """Record one secret-safe observed-model receipt from a chat stream."""

    if not isinstance(event, dict) or event.get("type") != "model_runtime":
        return False
    runtime = event.get("runtime")
    return _store_model_runtime(context, runtime) if isinstance(runtime, dict) else False


def record_delegation_runtime(context: Any, row: Any) -> bool:
    """Require and record the model receipt bound to one delegated execution."""

    if not isinstance(row, dict):
        return False
    execution_id = str(row.get("execution_id") or "").strip()
    if not execution_id:
        return False
    cache = _runtime_cache(context)
    expected = cache.setdefault("delegated_execution_ids", [])
    if not isinstance(expected, list):
        raise TypeError("delegated_execution_ids must be a list")
    if execution_id not in expected:
        expected.append(execution_id)
    runtime_profile = row.get("runtime_profile") if isinstance(row.get("runtime_profile"), dict) else {}
    runtime = runtime_profile.get("model_runtime") if isinstance(runtime_profile.get("model_runtime"), dict) else None
    return _store_model_runtime(context, runtime, execution_id=execution_id) if runtime is not None else False


@contextmanager
def preserve_workspace_paths(repo_root: Path, relative_paths: Sequence[str]) -> Iterator[None]:
    """Restore the exact pre-probe bytes for a bounded set of workspace paths."""

    root = repo_root.resolve()
    snapshots: dict[Path, bytes | None] = {}
    for relative_path in relative_paths:
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"probe side-effect path escapes repository: {relative_path}")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"probe side-effect path is not a file: {relative_path}")
        snapshots[target] = target.read_bytes() if target.is_file() else None

    try:
        yield
    finally:
        cleanup_errors: list[str] = []
        for target, original in snapshots.items():
            try:
                if target.is_symlink():
                    target.unlink()
                if original is None:
                    if target.is_file():
                        target.unlink()
                    elif target.exists():
                        raise RuntimeError(f"probe replaced a file with a non-file path: {target}")
                else:
                    if target.exists() and not target.is_file():
                        raise RuntimeError(f"probe replaced a file with a non-file path: {target}")
                    if not target.is_file() or target.read_bytes() != original:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(original)
            except (OSError, RuntimeError) as exc:
                cleanup_errors.append(f"{target}: {exc}")
        if cleanup_errors:
            raise RuntimeError("probe workspace cleanup failed: " + "; ".join(cleanup_errors))


@dataclass(frozen=True)
class EvidenceRow:
    family: str
    tier: int
    case: str
    expected: str
    actual: str
    passed: bool
    severity: str
    evidence: str = ""
    provenance_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_evidence_provenance(rows: list[EvidenceRow], *, required: bool = False) -> str:
    """Return the single run provenance id or reject mixed evidence.

    Legacy JSONL rows remain readable with an empty provenance id, but a fresh
    claimable run must require provenance on every row.  Mixing legacy rows,
    or rows from multiple live runs, would make profile/model attribution
    dishonest and therefore fails closed.
    """

    missing = sum(not str(row.provenance_id or "").strip() for row in rows)
    identifiers = {str(row.provenance_id).strip() for row in rows if str(row.provenance_id or "").strip()}
    if required and missing:
        raise ValueError(f"fresh evidence is missing provenance on {missing} row(s)")
    if missing and identifiers:
        raise ValueError("legacy and attributed evidence cannot be combined")
    if len(identifiers) > 1:
        raise ValueError(f"mixed evidence provenance is not claimable: {sorted(identifiers)}")
    return next(iter(identifiers), "")


def load_rubric(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_rubric(data)
    return data


def validate_rubric(rubric: dict[str, Any]) -> None:
    if rubric.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported rubric schema: {rubric.get('schema_version')!r}")
    families = rubric.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("rubric must define at least one capability family")

    identifiers: set[str] = set()
    total_weight = 0.0
    for family in families:
        family_id = str(family.get("id") or "").strip()
        if not family_id or family_id in identifiers:
            raise ValueError(f"missing or duplicate family id: {family_id!r}")
        identifiers.add(family_id)
        behaviors = family.get("behaviors")
        if not isinstance(behaviors, list) or not all(str(item).strip() for item in behaviors):
            raise ValueError(f"family {family_id!r} must define concrete behaviors")
        weight = float(family.get("weight") or 0.0)
        if weight <= 0:
            raise ValueError(f"family {family_id!r} has invalid weight")
        total_weight += weight
        tiers = family.get("tiers")
        if not isinstance(tiers, dict):
            raise ValueError(f"family {family_id!r} must define evidence tiers")
        for tier in TIERS:
            checks = tiers.get(str(tier))
            if not isinstance(checks, list) or not checks:
                raise ValueError(f"family {family_id!r} tier {tier} must fail closed with explicit checks")
            for check in checks:
                severity = str(check.get("severity") or "med")
                if severity not in SEVERITIES:
                    raise ValueError(f"family {family_id!r} tier {tier} has invalid severity")
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(f"family weights must sum to 1.0, got {total_weight:.12f}")


def score_families(
    rubric: dict[str, Any],
    rows: list[EvidenceRow],
    *,
    require_provenance: bool = False,
) -> dict[str, Any]:
    validate_evidence_provenance(rows, required=require_provenance)
    grouped: dict[tuple[str, int], list[EvidenceRow]] = {}
    for row in rows:
        grouped.setdefault((row.family, row.tier), []).append(row)

    family_scores: dict[str, int] = {}
    family_details: dict[str, dict[str, Any]] = {}
    weighted = 0.0
    for family in rubric["families"]:
        family_id = family["id"]
        score = 0
        first_failed_tier: int | None = None
        for tier in TIERS:
            tier_rows = grouped.get((family_id, tier), [])
            if tier_rows and all(row.passed for row in tier_rows):
                score = tier
                continue
            first_failed_tier = tier
            break
        family_scores[family_id] = score
        weighted += float(family["weight"]) * (score / 4.0)
        failed = [row.to_dict() for row in rows if row.family == family_id and not row.passed]
        family_details[family_id] = {
            "name": family["name"],
            "weight": family["weight"],
            "critical": bool(family.get("critical")),
            "score": score,
            "first_failed_tier": first_failed_tier,
            "failed_checks": failed,
        }

    parity = all(score == 4 for score in family_scores.values())
    critical_failures = [row.to_dict() for row in rows if not row.passed and row.severity == "critical"]
    return {
        "schema_version": SCHEMA_VERSION,
        "target": rubric["target"],
        "target_as_of": rubric["as_of"],
        "parity_achieved": parity,
        "parity_index": round(weighted * 100, 2),
        "family_scores": family_scores,
        "families": family_details,
        "totals": {
            "families": len(family_scores),
            "families_at_4": sum(score == 4 for score in family_scores.values()),
            "checks": len(rows),
            "checks_passed": sum(row.passed for row in rows),
            "checks_failed": sum(not row.passed for row in rows),
            "critical_failures": len(critical_failures),
        },
        "critical_failures": critical_failures,
    }


def ranked_gaps(rubric: dict[str, Any], scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for family in rubric["families"]:
        details = scorecard["families"][family["id"]]
        score = int(details["score"])
        if score == 4:
            continue
        gaps.append(
            {
                "family": family["id"],
                "name": family["name"],
                "score": score,
                "weight": family["weight"],
                "critical": bool(family.get("critical")),
                "first_failed_tier": details["first_failed_tier"],
                "priority": round(float(family["weight"]) * (4 - score) * (2 if family.get("critical") else 1), 4),
                "failed_checks": details["failed_checks"],
            }
        )
    return sorted(gaps, key=lambda gap: (-gap["priority"], gap["family"]))


def write_jsonl(path: Path, rows: list[EvidenceRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row.to_dict(), ensure_ascii=False) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8")


def read_jsonl(path: Path) -> list[EvidenceRow]:
    if not path.is_file():
        return []
    rows: list[EvidenceRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(EvidenceRow(**json.loads(line)))
    return rows
