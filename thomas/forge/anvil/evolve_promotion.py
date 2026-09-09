"""Fail-closed promotion evaluation for Evolve sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _evolve_runtime():
    # Imported lazily so evolve.py can expose these helpers without a cycle.
    from . import evolve

    return evolve


def _non_python_delta_files(changed_files: list[str]) -> list[str]:
    return [str(rel).replace("\\", "/") for rel in changed_files if not str(rel).replace("\\", "/").endswith(".py")]


def _has_passing_non_python_verifier(session: dict[str, Any]) -> bool:
    for item in session.get("verification") or []:
        if not isinstance(item, dict) or int(item.get("returncode") or 0) != 0:
            continue
        label = " ".join(
            str(item.get(key) or "") for key in ("source", "description", "acceptance_check", "command")
        ).lower()
        normalized = label.replace("_", "-")
        if "non-python" in normalized or "nonpy" in normalized:
            return True
    return False


def _supervisor_rejection_codes(supervisor_verdict: dict[str, Any]) -> str:
    return ", ".join(str(item.get("code") or "unknown") for item in (supervisor_verdict.get("findings") or [])[:8])


def _verifier_panel_rejection_reason(panel_result: dict[str, Any]) -> str:
    critical_dissent_count = int(panel_result.get("critical_dissent_count") or 0)
    if critical_dissent_count:
        return f"{critical_dissent_count} critical dissent vote(s)"
    pass_count = int(panel_result.get("pass_count") or 0)
    quorum = int(panel_result.get("quorum") or 0)
    nonpassing_votes = _verifier_panel_nonpassing_votes(panel_result)
    if nonpassing_votes:
        return "non-passing verifier vote(s): " + ", ".join(nonpassing_votes[:5])
    return f"pass_count {pass_count} below quorum {quorum}"


def _evolve_corpus_rejection_reason(corpus_result: dict[str, Any]) -> str:
    lock_errors = corpus_result.get("lock_errors") or []
    if lock_errors:
        codes = [str(item.get("code") or "unknown") for item in lock_errors if isinstance(item, dict)]
        return "lock errors: " + ", ".join(codes[:5])
    failed_cases = [
        str(item.get("case_id") or "unknown")
        for item in (corpus_result.get("cases") or [])
        if isinstance(item, dict) and not bool(item.get("ok"))
    ]
    if failed_cases:
        return "failed cases: " + ", ".join(failed_cases[:5])
    return "no passing evolve corpus cases"


def _verifier_panel_nonpassing_votes(panel_result: dict[str, Any]) -> list[str]:
    votes = panel_result.get("votes") or []
    nonpassing: list[str] = []
    for vote in votes:
        if not isinstance(vote, dict):
            continue
        status = str(vote.get("status") or "").strip() or "unknown"
        if status == "pass":
            continue
        role = str(vote.get("role") or "unknown").strip() or "unknown"
        nonpassing.append(f"{role}:{status}")
    return nonpassing


def _evaluate_promotion_candidate(
    paths,
    expected_delta: dict[str, Any],
    session_payload: dict[str, Any],
    *,
    candidate_dirname: str = "promote-candidate",
) -> dict[str, Any]:
    try:
        from evolve_supervisor import evaluate_candidate
    except ImportError as exc:
        raise RuntimeError("blue-only evolve supervisor is unavailable; refusing promotion") from exc

    candidate_root = _evolve_runtime()._prepare_delta_candidate_root(
        paths,
        expected_delta,
        dirname=candidate_dirname,
    )
    return evaluate_candidate(
        paths.blue_root,
        candidate_root,
        claimed_category=str(session_payload.get("category") or ""),
        claimed_risk=str(session_payload.get("risk_tier") or "low"),
        session_payload=session_payload,
    ).to_dict()


def _promote_verified_green_delta(
    paths,
    session_payload: dict[str, Any],
    expected_delta: dict[str, Any],
    *,
    stop_port: int = 8899,
    candidate_dirname: str = "promote-candidate",
    allow_critical_risk_floor: bool = False,
) -> tuple[Path, dict[str, Any]]:
    runtime = _evolve_runtime()
    changed_files = runtime._validate_verified_delta_for_promotion(paths, session_payload, expected_delta)
    supervisor_verdict = runtime._evaluate_promotion_candidate(
        paths,
        expected_delta,
        session_payload,
        candidate_dirname=candidate_dirname,
    )
    if not supervisor_verdict.get("ok"):
        codes = runtime._supervisor_rejection_codes(supervisor_verdict)
        raise runtime._PromotionRejected(
            f"blue-only supervisor rejected evolve promotion: {codes or 'unknown'}",
            supervisor_verdict=supervisor_verdict,
        )
    panel_result = runtime.run_verifier_panel(session_payload, supervisor_verdict=supervisor_verdict)
    verifier_panel = panel_result.to_dict()
    supervisor_verdict["verifier_panel"] = verifier_panel
    if not verifier_panel.get("ok") or runtime._verifier_panel_nonpassing_votes(verifier_panel):
        raise runtime._PromotionRejected(
            f"verifier panel rejected evolve promotion: {runtime._verifier_panel_rejection_reason(verifier_panel)}",
            supervisor_verdict=supervisor_verdict,
        )
    if str(supervisor_verdict.get("risk_floor") or "").strip().lower() == "critical" and not allow_critical_risk_floor:
        raise runtime._PromotionRejected(
            "blue-only supervisor requires human approval for critical risk floor",
            supervisor_verdict=supervisor_verdict,
        )
    non_python_files = runtime._non_python_delta_files(changed_files)
    if non_python_files and not runtime._has_passing_non_python_verifier(session_payload):
        preview = ", ".join(non_python_files[:8])
        raise runtime._PromotionRejected(
            f"non-Python delta requires a dedicated passing non-Python verifier before promotion: {preview}",
            supervisor_verdict=supervisor_verdict,
        )
    corpus_result = runtime.run_evolve_corpus(paths.blue_root).to_dict()
    supervisor_verdict["evolve_corpus"] = corpus_result
    if not bool(corpus_result.get("ok")):
        raise runtime._PromotionRejected(
            f"blue evolve corpus rejected promotion: {runtime._evolve_corpus_rejection_reason(corpus_result)}",
            supervisor_verdict=supervisor_verdict,
        )
    backup = runtime.promote_green_delta_to_blue(paths, changed_files, stop_port=int(stop_port))
    return backup, supervisor_verdict


def promote_evolve_session(
    project_root: Path | None = None,
    *,
    session_id: str = "",
    stop_port: int = 8899,
    allow_critical_risk_floor: bool = False,
) -> dict[str, Any]:
    runtime = _evolve_runtime()
    repo_root = runtime.resolve_repo_root(project_root)
    session = (
        runtime.load_evolve_session(repo_root, session_id)
        if str(session_id).strip()
        else runtime.load_latest_evolve_session(repo_root)
    )
    if session is None:
        raise RuntimeError("no evolve sessions found")
    if session.get("promoted"):
        return {"ok": True, "session": session, "already_promoted": True}
    if not bool(session.get("promotable")):
        raise RuntimeError("latest evolve session is not promotable")
    paths = runtime.get_paths(repo_root)
    if not paths.green_root.exists():
        raise RuntimeError("green doppelganger slot does not exist")
    expected_delta = dict(session.get("delta") or {})
    backup, supervisor_verdict = runtime._promote_verified_green_delta(
        paths,
        session,
        expected_delta,
        stop_port=int(stop_port),
        allow_critical_risk_floor=bool(allow_critical_risk_floor),
    )
    session["promoted"] = True
    session["supervisor_verdict"] = supervisor_verdict
    session["verifier_panel"] = dict(supervisor_verdict.get("verifier_panel") or {})
    session["promotion_backup"] = str(backup)
    session["status"] = "promoted"
    session["finished_at"] = runtime.utc_now_iso()
    session_dir = runtime._sessions_root(repo_root) / str(session["session_id"])
    runtime._write_json(session_dir / "session.json", session)
    runtime._write_text(session_dir / "session.md", runtime._render_session_markdown(session))
    return {"ok": True, "session": session, "backup_path": str(backup)}
