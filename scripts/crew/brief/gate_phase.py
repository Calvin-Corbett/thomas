"""One attempt's gate phase: which gates run, which pass stands, and what the runner is told. Stdlib only.

Split out of commit_attempts.py. ``judge`` builds the plan (gate_plan), leaves out the proven no-ops (gate_skips) and, on a
rebase, the passes gate_reuse can show are still true, runs the rest (gate_runner, under the machine-wide slots of
gate_slots), and records which passes may be kept for the next attempt.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.crew.brief import gate_reuse, gate_runner, gate_skips, gate_slots, git_reads


def skipped_note(unreviewed: Sequence[str]) -> str | None:
    """The old tool built this sentence for every landing and then dropped it; it is returned in ``gate_output`` now."""
    return "skipped unreviewed gate(s), commit them to restore: " + ", ".join(unreviewed) if unreviewed else None


def board_text(repo_root: Path, base: str) -> str | None:
    blob = git_reads.cat_file_batch(repo_root, [f"{base}:{gate_skips.BOARD}"]).get(f"{base}:{gate_skips.BOARD}")
    return None if blob is None else blob.decode("utf-8", "replace")


def judge(
    core: Any,
    repo_root: Path,
    *,
    agent: str,
    scope_selection: Any,
    index_path: Path,
    base: str,
    full_message: str,
    selected: Sequence[str],
    local_gate_commands: Sequence[tuple[str, Sequence[str]]],
    probe: Any,
    passed: dict[str, gate_reuse.Passed],
    rebased: bool,
) -> tuple[list[gate_runner.Result], list[str]]:
    """Judge the temporary index. Returns the results (registry order) and the gates left out for being unreviewed."""
    env = core._temp_index_env(agent, index_path, scope_selection=scope_selection, base=base)
    env["THOMAS_COMMIT_MESSAGE"] = str(full_message or "")
    legacy = gate_runner.legacy_requested()
    skips: dict[str, str] = {}
    if not legacy:
        try:
            skips = gate_skips.provable_noops(selected, lambda: board_text(repo_root, base))
        except (git_reads.GitReadError, OSError, subprocess.SubprocessError):
            skips = {}  # could not prove it, so nothing is skipped
    jobs, unreviewed = gate_runner.plan_jobs(
        local_gate_commands,
        applies=lambda name: core._gate_applies(name, selected),
        resolve=lambda name, command: core._resolved_gate_command(name, command, selected_paths=selected),
        script_of=core._gate_script,
        tracked=lambda paths: git_reads.tracked_among(repo_root, paths),
        skips=skips,
    )
    prints = gate_reuse.Fingerprints(repo_root, index_env=env, base=base, selected=selected)
    if rebased:  # judge again everything that is not provably unchanged (gate_reuse)
        again = gate_reuse.rerun_set([job.name for job in jobs], passed, now=time.monotonic(), fingerprint_of=prints.of)
        jobs = [job for job in jobs if job.name in again]
    workers = gate_runner.worker_count()
    runner = gate_runner.Runner(
        cwd=str(repo_root),
        env=env,
        workers=workers,
        timeout=gate_runner.gate_timeout(),
        base=base,
        probe=probe,
        slots=gate_slots.pool() if workers > 1 else None,
    )
    results = runner.run(jobs)
    for result in results:
        keep, stamp = result.ok and not result.tainted, None
        if keep and result.name in gate_reuse.FINGERPRINTED:
            stamp = prints.stamp(result.name)  # None: its inputs changed while it ran, so this pass describes nothing
            keep = stamp is not None
        if keep:
            passed[result.name] = gate_reuse.Passed(result.finished, stamp)
        else:
            passed.pop(result.name, None)
    return results, unreviewed
