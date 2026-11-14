"""A Thomas project whose Build conversation has gone quiet is not listed as running.

You reported ``GET /api/self/projects`` listing a project that had died hours earlier as
``running -- its first Build run is starting``. That sentence is
:func:`thomas.server.routes.self_project_routes._in_green`'s wording for
:func:`thomas.server.thomas_project.project_phase` answering ``("waiting", "")``, which it does whenever a
project's conversation carries no agent turn yet. Nothing in that answer was time-bounded, so a run that was
killed before it recorded anything left a conversation that read exactly like one started a second ago,
forever.

The liveness rule DID exist, but only inside a loop's memory: ``chat_self_project.follow_card`` gives a
project ``_IDLE_GRACE_S`` (120 s) of quiet and then ends its chat card. That loop stops with the process
that started it, and the list route never had a rule of its own -- so the card and the list could disagree
about the same project, and after a restart nothing re-derived the answer at all.

This is that rule, rewritten to read from what is on disk rather than from how long a loop has been
watching: a project whose Build conversation in its green has not been written to for
:data:`QUIET_MAX_S`, with no run going, is not running. Both callers of ``project_phase`` already establish
"no run going" before they trust an ending (the list route asks the run registry first; ``follow_card``
checks ``_run_active``), so this only ever speaks about a project nothing is running.

An hour, not two minutes: a single Build turn can think for a long time before it writes a turn, and this
rule has no run registry to ask, unlike the card loop. The failure it must catch is measured in hours.

Silence is the only thing measured here, and silence is all the wording claims. An earlier draft of this
module went further: it ended EVERY wait whose conversation predated this process and called that "stopped
by the restart -- a Build run does not survive a restart and nothing resumes it". That sentence is not true
of Thomas as he is, and the two passes that make it untrue are both registered at boot:

* ``thomas/server/autopilot_park.py``'s ``park_loop``, started by ``app_routes_init``'s ``on_startup`` hook.
  It rebuilds every paused build from the ``autopilot.parked_until`` stamp left on its conversation -- which
  is what survives the restart -- and starts the next run when the provider's limit resets.
* ``recover_interrupted_runs`` in ``thomas/server/praxis/startup.py``, which the Praxis row in
  ``thomas/server/rows/praxis.py`` runs once the server is up. It reads the Praxis run journal and resumes the
  nonterminal children of a run the restart interrupted.

``_stored_phase`` asks Autopilot's own ``decide`` before anything here is applied, so a parked project
arrives as ``paused`` and is exempt on that ground alone; the draft would still have printed "stopped" over
a project either pass had just picked up, at the moment it picked it up. Neither pass is total -- a Praxis
child that ran as an external builder is recorded interrupted and needs the run started again -- which is a
reason for this module to say less, not more. A wait that another pass owns is reconsidered here on the same
evidence as any other: an hour of silence with no run going, and nothing about who is or is not going to
start one. Whatever starts a run next writes to this same conversation file, and the clock is read again on
every call, so a project that starts moving again stops being called stopped without this module having to
know what moved it.

The limit of that, said plainly: the run registry the callers check is THIS process's. A project a second
Thomas is running, or one a pass has picked up but not yet written a turn for, is indistinguishable from a
dead one after an hour of silence, and this calls it stopped. Both halves of the sentence it prints stay
true in that case -- nothing has been written for an hour, and no Build run is going here -- and the next
turn written to the file takes the row back to waiting.
"""

from __future__ import annotations

import time
from pathlib import Path

# A Build run writes a turn to its conversation as each one finishes, and Autopilot writes between rounds.
# Quiet for longer than this, with nothing running, means the team that owned this green is gone.
QUIET_MAX_S = 3600.0
# thomas_project.project_phase's wording while a settle is mid-flight: the green is being handed over right
# now and its conversation has already been copied out, so its own file stops changing on purpose.
HANDING_OVER = "Handing the change to your approval card"
# hand_in_hold.phase's checking row also waits on a second look without writing to the Build conversation.
CHECKING = "Your finished change is being checked before your approval card."


def last_write(live_file: Path) -> float | None:
    """When anything was last written to a project's Build conversation, or None if it cannot be read."""
    try:
        return Path(live_file).stat().st_mtime
    except OSError:
        return None


def settle_quiet(live_file: Path, phase: str, why: str, *, now: float | None = None) -> tuple[str, str]:
    """``(phase, why)`` unchanged, unless a project said to be waiting has been silent for an hour.

    Only ``waiting`` is reconsidered. ``paused`` is a usage limit that Autopilot resumes by itself;
    ``settled`` and ``ended`` are already answers; hand-over and checking waits can stop writing to this
    file by design. Ordinary waiting, including a wait without a hold row, still expires after an hour.

    A conversation that cannot be read at all is left alone: ``project_phase`` already ends a project whose
    Build conversation is gone, and a file caught mid-write is answered again on the next call.
    """
    if phase != "waiting" or why in (HANDING_OVER, CHECKING):
        return phase, why
    written = last_write(live_file)
    if written is None:
        return phase, why
    moment = time.time() if now is None else now
    quiet = max(0.0, moment - written)
    if quiet <= QUIET_MAX_S:
        return phase, why
    waiting_for = why or "its first Build run was starting"
    return "ended", (
        f"nothing has been written to its Build conversation for {quiet / 3600.0:.1f} h "
        f"and no Build run is going, after: {waiting_for}"
    )


__all__ = ["CHECKING", "HANDING_OVER", "QUIET_MAX_S", "last_write", "settle_quiet"]
