"""Selectable targets for a Code task -- including Thomas himself, on purpose.

Today the project picker has no notion of *named choices*: a Code task either
carries a validated ``project_root`` or falls back. Thomas's own source is
handled purely as something to defend against, so the only way it can ever be
reached is by accident -- which is exactly the failure being reported, and
exactly backwards.

Thomas can edit himself. That is a legitimate, occasionally necessary thing to
want. It should just never be what you get by *not* choosing.

So this offers the picker a small explicit list:

``scratch``  a disposable working project -- the default when nothing is chosen
``thomas``   Thomas's own source tree -- opt-in only, and clearly labelled
``project``  any other validated directory the user picks

The rule this module exists to enforce: :func:`resolve_selection` returns
Thomas's source root **only** when the caller explicitly asked for it by id.
Every other input -- empty, unknown, malformed, or a path that happens to sit
inside the Thomas repo -- resolves somewhere safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects

log = logging.getLogger(__name__)

SCRATCH_ID = "scratch"
THOMAS_ID = "thomas"
PROJECT_ID = "project"

# Shown next to the Thomas option so the consequence is visible at click time.
THOMAS_WARNING = "Edits Thomas's own source. Changes affect the app you are using right now."

_RESOLVE_FAULTS = (OSError, ValueError, TypeError, AttributeError)


@dataclass(frozen=True)
class ProjectOption:
    """One entry in the picker."""

    id: str
    label: str
    root: str
    kind: str
    is_default: bool = False
    requires_explicit_choice: bool = False
    warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "root": self.root,
            "kind": self.kind,
            "is_default": self.is_default,
            "requires_explicit_choice": self.requires_explicit_choice,
            "warning": self.warning,
        }


def thomas_option() -> ProjectOption | None:
    """The explicit 'work on Thomas himself' choice, or None if unavailable."""
    try:
        root = forge_code_projects.thomas_source_repo_root()
    except _RESOLVE_FAULTS as exc:  # pragma: no cover - defensive
        log.debug("thomas source root unavailable: %s", exc)
        return None
    if root is None:
        return None
    return ProjectOption(
        id=THOMAS_ID,
        label="Thomas",
        root=str(root),
        kind="self",
        requires_explicit_choice=True,
        warning=THOMAS_WARNING,
    )


def scratch_option(catalog_root: Path | str) -> ProjectOption:
    """The disposable default project."""
    root = forge_code_projects.default_scratch_project(Path(catalog_root))
    return ProjectOption(
        id=SCRATCH_ID,
        label="Scratch project",
        root=str(root),
        kind="scratch",
        is_default=True,
    )


def project_options(catalog_root: Path | str) -> list[ProjectOption]:
    """Everything the picker should offer, default first."""
    options = [scratch_option(catalog_root)]
    thomas = thomas_option()
    if thomas is not None:
        options.append(thomas)
    return options


def resolve_selection(
    selection: Any,
    *,
    catalog_root: Path | str,
    requested_project: Any = None,
) -> Path:
    """Turn a picker selection into a project root.

    Thomas's own source is returned **only** for ``selection == "thomas"``.
    Anything else -- including a ``requested_project`` path that points at or
    inside the Thomas repo -- resolves to a safe project, because reaching
    Thomas by accident is the bug this module exists to prevent.
    """
    catalog = Path(catalog_root)
    chosen = str(selection or "").strip().lower()

    if chosen == THOMAS_ID:
        thomas = thomas_option()
        if thomas is not None:
            return Path(thomas.root)
        log.warning("Thomas source root was requested but is unavailable; using scratch")
        return forge_code_projects.default_scratch_project(catalog)

    scratch = forge_code_projects.default_scratch_project(catalog)

    if chosen in ("", SCRATCH_ID):
        return scratch

    # An explicit directory. Only treat the input as a path when one was
    # actually supplied -- an unrecognised option id is a picker/client bug, and
    # the safe answer is scratch rather than an exception that fails the task.
    target = requested_project if requested_project is not None else selection
    if not _looks_like_path(target):
        log.warning("unrecognised project selection %r; using scratch", selection)
        return scratch

    try:
        resolved = forge_code_projects.validate_project_root(target, fallback=scratch)
    except forge_code_projects.ForgeCodeProjectError:
        raise
    except _RESOLVE_FAULTS as exc:
        log.warning("could not resolve project selection %r: %s", target, exc)
        return scratch

    thomas = thomas_option()
    if thomas is not None and Path(resolved) == Path(thomas.root):
        log.warning("project selection resolved to Thomas's source without an explicit choice; using scratch")
        return scratch
    return Path(resolved)


def _looks_like_path(value: Any) -> bool:
    """True when a selection is plausibly a directory rather than an option id."""
    if isinstance(value, Path):
        return True
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return Path(text).is_absolute()
    except (OSError, ValueError):  # pragma: no cover - malformed input
        return False


def describe_selection(root: Path | str) -> str:
    """Human label for an already-bound root, so the UI can say what it is."""
    thomas = thomas_option()
    if thomas is not None and Path(root) == Path(thomas.root):
        return "Thomas"
    return Path(root).name or str(root)
