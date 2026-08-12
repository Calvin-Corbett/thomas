"""Aggregate registration for the frontier capability surfaces.

Each surface pairs a committed backend core with an HTTP route module and a
self-contained browser panel served from ``thomas/server/web/js``:

==========  =========================================  ==========================
Capability  Backend core                               Panel global
==========  =========================================  ==========================
CAP-040     thomas/agent/fleet_reply.py                mountFleetReplyPanel
CAP-137     thomas/observability/run_projection.py     mountRunTelemetryPanel
CAP-139     thomas/observability/worktree_progress.py  mountWorktreeProgressPanel
CAP-147     thomas/tools/source_annotations.py         mountSourceAnnotationPanel
CAP-148     thomas/tools/mention_context.py            mountMentionContextPanel
CAP-149     thomas/tools/pr_review.py                  mountPrReviewPanel
==========  =========================================  ==========================

Registering them through one entry point keeps the app-wide route
initialisation to a single guarded block, and lets one surface fail to load
without taking the others down with it.

The companion page is ``thomas/server/web/frontier.html``, served by the
existing static handler at ``/static/frontier.html``.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Import/registration faults are reported per surface instead of aborting the
# whole set. Deliberately a wide *specific* tuple -- never a bare Exception.
_REGISTRATION_FAULTS = (
    ImportError,
    ModuleNotFoundError,
    RuntimeError,
    KeyError,
    TypeError,
    AttributeError,
    ValueError,
    OSError,
)

# (capability id, module path, register-function name)
_SURFACES: tuple[tuple[str, str, str], ...] = (
    ("CAP-040", "thomas.server.routes.fleet_reply_routes", "register_fleet_reply_routes"),
    ("CAP-137", "thomas.server.routes.run_telemetry_routes", "register_run_telemetry_routes"),
    ("CAP-139", "thomas.server.routes.worktree_progress_routes", "register_worktree_progress_routes"),
    ("CAP-147", "thomas.server.routes.source_annotation_routes", "register_source_annotation_routes"),
    ("CAP-148", "thomas.server.routes.mention_context_routes", "register_mention_context_routes"),
    ("CAP-149", "thomas.server.routes.pr_review_routes", "register_pr_review_routes"),
)


def register_frontier_surface_routes(app: Any, config: Any = None) -> list[str]:
    """Register every frontier capability surface on ``app``.

    Returns the capability ids that registered successfully, so callers (and
    tests) can assert coverage rather than guessing.
    """
    registered: list[str] = []
    for cap_id, module_path, func_name in _SURFACES:
        try:
            module = __import__(module_path, fromlist=[func_name])
            register = getattr(module, func_name)
            register(app, config)
        except _REGISTRATION_FAULTS as exc:
            log.warning("Frontier surface %s (%s) unavailable: %s", cap_id, func_name, exc)
            continue
        registered.append(cap_id)
        log.debug("Frontier surface %s registered via %s", cap_id, func_name)

    if registered:
        log.info("Frontier surfaces registered: %s", ", ".join(registered))
    return registered
