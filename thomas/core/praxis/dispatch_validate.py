"""Validate a `send_task` dispatch without re-deciding it.

The chat model decides everything in one structured `send_task` call: surface,
specialist, kind, deliverable_format, needs_build, project and acceptance. This
module may only **validate enums, reject an unknown project, and veto on hard
blockers with a visible reason** (spec S2.2). It never rewrites a decision - a
specialist that looks wrong for the kind is reported as a NOTE, because silently
reclassifying the model's choice is the failure this design exists to prevent.

The escape hatch is deliberate and load-bearing: after two failed repairs in one
turn the task is dispatched ANYWAY, with invalid acceptance items dropped and the
best reachable end state degraded to `completed_unverified`. A validator that can
refuse forever is a way for Thomas to say "sorry, I can't", which Rule 0 forbids.

Pure and I/O-free. The project catalog arrives as ids from the caller, so
`thomas/core` never imports `thomas/server` or `thomas/tools`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

# Error codes. Named in the spec where it names them; the rest follow the
# same shape so a card can show a stable identifier rather than prose.
NEEDS_BUILD_REQUIRES_TASK_SURFACE = "needs_build_requires_task_surface"
NEEDS_BUILD_KIND_MISMATCH = "needs_build_kind_mismatch"
UNKNOWN_PROJECT = "unknown_project"
PROJECT_IS_THOMAS_SOURCE = "project_is_thomas_source"
UNCITED_ACCEPTANCE = "uncited_acceptance"
INVALID_ACCEPTANCE_CHECK = "invalid_acceptance_check"
UNKNOWN_KIND = "unknown_kind"
UNKNOWN_PROJECT_MODE = "unknown_project_mode"

KINDS: frozenset[str] = frozenset(
    {"code", "web_app", "document", "pdf", "image", "creative", "research", "data", "other"}
)
BUILD_KINDS: frozenset[str] = frozenset({"code", "web_app"})
REPO_CHANGES = "repo_changes"
PROJECT_MODES: frozenset[str] = frozenset({"existing", "new"})
ACCEPTANCE_KINDS: frozenset[str] = frozenset(
    {
        "file_exists",
        "file_contains",
        "project_test_command",
        "lint",
        "render_html",
        "pdf_opens",
        "image_dimensions",
        "custom_command",
    }
)

MAX_REPAIRS = 2

END_STATE_COMPLETED = "completed"
END_STATE_UNVERIFIED = "completed_unverified"


@dataclass(frozen=True)
class DispatchVerdict:
    """What validation found, and what the caller must do about it.

    `errors` are blocking only while `dispatch_anyway` is False. Once the repair
    budget is spent the task goes out regardless, and the errors survive as the
    reason the card shows.
    """

    errors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    dropped_acceptance: tuple[int, ...] = ()
    dispatch_anyway: bool = False
    best_end_state: str = END_STATE_COMPLETED
    repair_attempts: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def may_dispatch(self) -> bool:
        """A task goes out when it is clean, or when the repair budget is spent."""
        return self.ok or self.dispatch_anyway


def _collapse(text: object) -> str:
    """Lower-case with runs of whitespace collapsed, for citation comparison."""
    return " ".join(str(text or "").split()).casefold()


def _acceptance_items(payload: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    raw = payload.get("acceptance") or ()
    if isinstance(raw, Mapping) or not isinstance(raw, Iterable):
        return ()
    return [item for item in raw if isinstance(item, Mapping)]


def uncited_acceptance_indexes(payload: Mapping[str, object]) -> tuple[int, ...]:
    """Acceptance items whose `cites` is not a verbatim quote from `instructions`.

    Compared case-insensitively after collapsing whitespace, per S2.2 - a model
    that re-wraps a quoted line has still cited it, and failing that would spend
    the repair budget on formatting.
    """
    instructions = _collapse(payload.get("instructions"))
    bad: list[int] = []
    for index, item in enumerate(_acceptance_items(payload)):
        cites = _collapse(item.get("cites"))
        if not cites or cites not in instructions:
            bad.append(index)
    return tuple(bad)


def validate_dispatch(
    payload: Mapping[str, object],
    *,
    known_project_ids: Iterable[str] = (),
    thomas_source_project_ids: Iterable[str] = (),
    repair_attempts: int = 0,
) -> DispatchVerdict:
    """Check one `send_task` payload. Never mutates it; never re-decides it."""
    errors: list[str] = []
    notes: list[str] = []

    kind = str(payload.get("kind") or "").strip()
    if kind and kind not in KINDS:
        errors.append(UNKNOWN_KIND)

    deliverable_format = str(payload.get("deliverable_format") or "").strip()
    needs_build = bool(payload.get("needs_build"))
    surface = str(payload.get("surface") or "").strip()

    if needs_build:
        if surface != "task":
            errors.append(NEEDS_BUILD_REQUIRES_TASK_SURFACE)
        if kind not in BUILD_KINDS and deliverable_format != REPO_CHANGES:
            errors.append(NEEDS_BUILD_KIND_MISMATCH)

    project = payload.get("project")
    if isinstance(project, Mapping):
        mode = str(project.get("mode") or "").strip()
        project_id = str(project.get("id") or "").strip()
        if mode and mode not in PROJECT_MODES:
            errors.append(UNKNOWN_PROJECT_MODE)
        elif mode == "existing":
            if project_id not in set(known_project_ids):
                errors.append(UNKNOWN_PROJECT)
            elif project_id in set(thomas_source_project_ids):
                # Not an error: Q2 routes this to the self-development worker
                # with a visible note. Refusing it would be a "can't do that".
                notes.append(PROJECT_IS_THOMAS_SOURCE)

    uncited = uncited_acceptance_indexes(payload)
    if uncited:
        errors.append(UNCITED_ACCEPTANCE)
    checks = _acceptance_items(payload)
    check_ids = [str(item.get("id") or "").strip() for item in checks]
    if len(check_ids) != len(set(check_ids)) or any(
        not check_id
        or str(item.get("kind") or "") not in ACCEPTANCE_KINDS
        or (str(item.get("kind") or "") in {"file_exists", "file_contains"} and not str(item.get("path") or "").strip())
        or (str(item.get("kind") or "") == "file_contains" and not str(item.get("needle") or ""))
        for check_id, item in zip(check_ids, checks, strict=True)
    ):
        errors.append(INVALID_ACCEPTANCE_CHECK)

    budget_spent = int(repair_attempts) >= MAX_REPAIRS
    dispatch_anyway = bool(errors) and budget_spent

    # Only acceptance is droppable. A bad enum or an unknown project is a
    # statement about the task itself, and dropping it would change what runs.
    dropped = uncited if dispatch_anyway else ()
    unverified = dispatch_anyway or bool(uncited)

    return DispatchVerdict(
        errors=tuple(errors),
        notes=tuple(notes),
        dropped_acceptance=dropped,
        dispatch_anyway=dispatch_anyway,
        best_end_state=END_STATE_UNVERIFIED if unverified else END_STATE_COMPLETED,
        repair_attempts=int(repair_attempts),
    )
