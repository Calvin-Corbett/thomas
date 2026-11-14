"""One landing, as many attempts as the branch's movement forces. Stdlib only; the commit tool passes itself in as ``core``.

An attempt reads the branch tip (the base), builds a temporary index on it, judges that index with the gates, makes the
commit object with the base as its parent, and swaps the branch ref with the base as the expected old value. The swap is
the only atomic step, so a landing is always judged against one coherent base.

When a neighbour lands first the tip moves. Before this module the whole landing was refused (``branch_race``) and the
agent paid the full gate ladder again. Now the landing REBASES: it rebuilds the index on the new tip and tries again, at
most MAX_ATTEMPTS times, re-judging everything except what gate_reuse can show is unchanged.

What stays exactly as it was:

* a refusal from a gate that ran while the tip stayed on its base is final and is returned at once;
* a refusal from a gate that ran while the tip MOVED is not trusted at first (it compared the index with a tip it was not
  built on, the way two measured refusals did), so the landing rebases and the gate judges again. If the same gate refuses
  with the same words on the next attempt the refusal is about this agent, not the moving tip, and it is final. (Measured
  with ten agents: an unread-mail refusal from active_folder_guard took three full attempts to be reported before this.)
  Attempts run out on a refusal that keeps changing: it is returned as the gate's refusal, not as a race;
* a branch that was rewritten rather than advanced (the base is not an ancestor of the new tip), or a tip that is not a
  commit at all, is not rebased onto: it is ``branch_race`` as before;
* ``dry_run`` never needs a slot and never swaps.

THOMAS_COMMIT_LEGACY_PATH=1 gives the old tool's behaviour for everything in this module: one attempt, no skipped no-op
gates, no reused passes, one gate at a time (gate_runner). The batched git reads stay, they only ask the same questions with
fewer processes.
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.crew.brief import gate_phase, gate_reuse, gate_runner, git_reads, slot_check

MAX_ATTEMPTS = 3
SWAP_SETTLE_SECONDS = 1.0
INDEX_LOCK_TRIES = 6
REBASE_JITTER_ENV = "THOMAS_COMMIT_REBASE_JITTER"  # the longest random pause, in seconds, before a rebase; 0 for none
DEFAULT_REBASE_JITTER = 1.0
MAX_REBASE_JITTER = 10.0
RACE_MESSAGE = "HEAD changed during scoped commit preparation; branch was not advanced"
RACE_NEXT_STEP = "Re-run the scoped commit after refreshing the branch state."
GATE_NEXT_STEP = "Fix the reported local gate failure, or adjust the explicit fallback paths if the gate reports an ownership conflict."


def _reasons(failure: gate_runner.Result | None) -> dict[str, str]:
    """What an unstable refusal carries into a branch_race, so the agent still reads why a gate said no."""
    return {} if failure is None else {"gate_name": failure.name, "gate_output": failure.output}


def _cannot_rebase(core: Any, repo_root: Path, base: str, tip: str) -> str | None:
    """Why the landing cannot move onto ``tip``, or None when it can."""
    if tip == base:
        return "the branch did not move"
    if core._run_git(repo_root, ["cat-file", "-e", f"{tip}^{{commit}}"]).returncode != 0:
        return f"{tip[:12]} is not a commit"
    if core._run_git(repo_root, ["merge-base", "--is-ancestor", base, tip]).returncode != 0:
        return "the branch was rewritten, not advanced"
    return None


def _rebase_pause(environ: dict[str, str] | None = None) -> None:
    """Wait a random moment before rebuilding on the new tip.

    Landings that lose the same race all rebase at once and then run their gate ladders in step: ten simulated agents
    peaked at 193 processes, 92 percent of ten ladders at once. A random pause spreads them. Whether it helps is NOT
    measured (the review that asked for it measured the lockstep, not the cure), so it is short, and 0 turns it off.
    """
    env = os.environ if environ is None else environ
    try:
        longest = float(str(env.get(REBASE_JITTER_ENV) or "").strip())
    except ValueError:
        longest = DEFAULT_REBASE_JITTER
    if math.isfinite(longest) and longest > 0:
        time.sleep(random.uniform(0.0, min(longest, MAX_REBASE_JITTER)))


def _tip_moved_within(core: Any, repo_root: Path, base: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if core._current_head(repo_root) != base:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _swap(core: Any, repo_root: Path, *, branch: str, sha: str, base: str) -> bool:
    """True when the ref moved to ``sha``. False when a neighbour's landing got there first. Anything else raises."""
    try:
        core._update_branch_ref(repo_root, branch=branch, commit_sha=sha, expected_head=base)
    except RuntimeError:
        # A lost compare-and-swap reads "is at X but expected Y"; a swap that met the neighbour's ref lock reads as a lock
        # error with the tip not yet moved. Both are a neighbour landing: wait briefly for the tip, else it is a real fault.
        if _tip_moved_within(core, repo_root, base, SWAP_SETTLE_SECONDS):
            return False
        raise
    return True


def _realign(core: Any, repo_root: Path, selected: Sequence[str], sha: str) -> None:
    """Reset the live index for the selected paths. A neighbour's reset holds index.lock for a moment, so ask again."""
    last: RuntimeError | None = None
    for _ in range(INDEX_LOCK_TRIES):
        try:
            core._sync_live_index(repo_root, selected)
            return
        except RuntimeError as exc:
            last = exc
            if "index.lock" not in str(exc):
                break
            time.sleep(0.25)
    raise RuntimeError(f"the commit landed as {sha}, but the live index could not be realigned to it: {last}") from last


def land(
    core: Any,
    *,
    repo_root: Path,
    workboard_path: Path,
    agent: str,
    scope_selection: Any,
    selected_paths: Sequence[str],
    include_paths: Sequence[str],
    message: str,
    dry_run: bool,
    local_gate_commands: Sequence[tuple[str, Sequence[str]]],
    require_slot: bool = False,
) -> Any:
    selected = list(selected_paths)
    branch: str | None = None
    holder: Any = None
    want_slot = bool(require_slot) or slot_check.configured_default(repo_root)
    legacy = gate_runner.legacy_requested()
    cap = 1 if legacy else MAX_ATTEMPTS
    note: str | None = None

    def result(ok: bool, blocker: str | None, text: str, **extra: Any) -> Any:
        return core.CommitResult(
            ok=ok,
            blocker_class=blocker,
            message=text,
            agent=agent,
            branch=branch,
            claim_scopes=tuple(scope_selection.scopes),
            selected_paths=tuple(selected),
            dry_run=bool(dry_run),
            scope_source=scope_selection.source,
            **extra,
        )

    def refusal(failure: gate_runner.Result, text: str = "") -> Any:
        return result(
            False,
            "local_gate_failed",
            f"local gate failed: {failure.name}{text}",
            gate_name=failure.name,
            gate_output=failure.output,
            next_step=GATE_NEXT_STEP,
        )

    def no_slot() -> Any:
        refusal_text = slot_check.check_slot(repo_root, agent=agent)
        if refusal_text is None:
            return None
        return result(
            False, "no_landing_slot", refusal_text, next_step=f"Get a landing slot: {slot_check.HOW_TO_GET_ONE}"
        )

    try:
        branch = core._current_branch(repo_root)
        base = core._current_head(repo_root)
        trailers = core._commit_trailers(agent=agent, scope_selection=scope_selection)
        full_message = core.commit_integrity.compose_message(message, trailers)
        core.coordination_barrier.require_clear_p0(workboard_path, bound_agent=agent)
        if want_slot and not dry_run and (refused := no_slot()) is not None:
            return refused
        probe = git_reads.HeadProbe(repo_root, branch)
        passed: dict[str, gate_reuse.Passed] = {}
        rebased = False
        last_refusal: tuple[str, str] | None = None
        attempt = 1
        while True:
            if holder is not None:
                holder.cleanup()
            index_path, holder = core._prepare_temp_index(
                repo_root, agent=agent, selected_paths=selected, scope_selection=scope_selection, base=base
            )
            results, unreviewed = gate_phase.judge(
                core,
                repo_root,
                agent=agent,
                scope_selection=scope_selection,
                index_path=index_path,
                base=base,
                full_message=full_message,
                selected=selected,
                local_gate_commands=local_gate_commands,
                probe=probe,
                passed=passed,
                rebased=rebased,
            )
            note = gate_phase.skipped_note(unreviewed)
            failure = gate_runner.first_failure(results)
            if failure is not None:
                # A refusal from a gate that ran while the tip moved is not trusted at first. One that comes back word for
                # word after the landing rebased is about this agent's state, not about the moving tip: it is real.
                if not failure.tainted or legacy or last_refusal == (failure.name, failure.output):
                    return refusal(failure)
                last_refusal = (failure.name, failure.output)
            stable = failure is None and probe() == base
            if dry_run and failure is None:
                return result(True, None, "local scoped commit checks passed (dry-run)", gate_output=note)
            if stable:
                core.coordination_barrier.require_clear_p0(workboard_path, bound_agent=agent)
                if want_slot and (refused := no_slot()) is not None:
                    return refused
                sha = core._create_commit_object(
                    repo_root,
                    agent=agent,
                    index_path=index_path,
                    parent_head=base,
                    message=full_message,
                    expected_body=message,
                    expected_trailers=trailers,
                )
                if core._current_head(repo_root) == base and _swap(core, repo_root, branch=branch, sha=sha, base=base):
                    _realign(core, repo_root, selected, sha)
                    return result(True, None, "scoped agent commit created", commit_sha=sha, gate_output=note)
            # The tip moved under this attempt: during the gates, before the swap, or at it. Rebase onto it.
            tip = core._current_head(repo_root)
            why = _cannot_rebase(core, repo_root, base, tip)
            if why is None and attempt >= cap and failure is not None:
                return refusal(failure, f" (judged while the branch moved, on {attempt} attempts)")
            if why is not None or attempt >= cap:
                return result(False, "branch_race", RACE_MESSAGE, next_step=RACE_NEXT_STEP, **_reasons(failure))
            _rebase_pause()
            # the pause is long enough for another landing: rebase onto the tip as it is now, not as it was
            tip = core._current_head(repo_root)
            if _cannot_rebase(core, repo_root, base, tip) is not None:
                return result(False, "branch_race", RACE_MESSAGE, next_step=RACE_NEXT_STEP, **_reasons(failure))
            fresh = core._selected_paths(repo_root, scope_selection, include_paths)
            if fresh != selected or core._stray_version_files(repo_root, fresh):
                return result(
                    False,
                    "branch_race",
                    RACE_MESSAGE + "; the selected paths changed meanwhile",
                    next_step=RACE_NEXT_STEP,
                )
            base, attempt, rebased = tip, attempt + 1, True
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return result(False, "broken_repo_tool", str(exc))
    finally:
        if holder is not None:
            holder.cleanup()
