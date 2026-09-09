"""The world Thomas can see without being asked.

Design: `plans/thomas/ALIVENESS_DESIGN_2026-08-27.md` §2 (the world) and §3
(the tick band).

This is the cheap tier of the aliveness loop. Nothing here calls a model, opens
a socket, or costs money: every sensor is a filesystem read or a short
subprocess with a hard timeout, so the whole sweep is safe to run on a short
interval. That is deliberate — the design's whole cost argument is that 99% of
being alive must be free.

Sensors return :class:`Observation` values. :class:`WorldModel` diffs one sweep
against the previous one and emits :class:`Change` values. A Change is what
"something happened while you were away" actually means, and it is the only
thing the drives react to.

Adding a sensor: implement ``name`` and ``sample()``, return Observations whose
``key`` is stable across sweeps (the key is the identity used for diffing), and
register it with the WorldModel. Keep it cheap and keep it silent — a sensor
that talks to the user has escaped its layer.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

# Sensors must stay cheap. A sensor that cannot answer within this budget is
# treated as unavailable for the sweep rather than allowed to stall the tick.
SENSOR_TIMEOUT_S: float = 5.0

# Consecutive failures before a sensor is dropped for the life of the process.
# A sensor that throws on every sweep would otherwise fill the log forever.
SENSOR_FAILURE_LIMIT: int = 5

# How long one sensor gets to answer before the sweep moves on without it.
SENSOR_SAMPLE_TIMEOUT_S: float = 10.0

# Sensors are the extension point of this module, so a misbehaving one must not
# be able to stop the loop. Catching exception types cannot achieve that: repo
# policy forbids a catch-all that does not re-raise (agent_safety.toml:
# broad_catch_requires), re-raising would defeat the isolation, and any explicit
# tuple still misses a custom type derived straight from Exception. It also does
# nothing about a sensor that simply never returns.
#
# So the isolation is structural instead of syntactic: each sensor is sampled in
# its own short-lived thread and joined with a timeout. An exception of *any*
# type dies inside that worker (and is printed by the default threading
# excepthook, so it stays visible), and a sensor that hangs is abandoned. Either
# way the sweep sees "no result", counts a failure, and carries on.
SENSOR_FAULTS: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    LookupError,
    ArithmeticError,
    ImportError,
    AssertionError,
    NotImplementedError,
    UnicodeError,
)


@dataclass(frozen=True)
class Observation:
    """One reading of one fact about the world.

    ``topic`` is the permission bucket this fact belongs to (design §5 — topic
    identity). ``key`` is the stable identity of the fact within that topic;
    ``value`` is its current state rendered as a string so successive sweeps
    diff by equality without per-sensor comparison logic.
    """

    topic: str
    key: str
    value: str
    at: float = field(default_factory=time.time)
    detail: dict[str, Any] = field(default_factory=dict)

    def identity(self) -> tuple[str, str]:
        return (self.topic, self.key)


@dataclass(frozen=True)
class Change:
    """A fact that differs from the previous sweep."""

    topic: str
    key: str
    before: str | None
    after: str
    at: float = field(default_factory=time.time)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_new(self) -> bool:
        """True when this fact had no previous reading (first sighting)."""
        return self.before is None

    def describe(self) -> str:
        if self.is_new:
            return f"{self.topic}: {self.key} = {self.after}"
        return f"{self.topic}: {self.key} {self.before} -> {self.after}"


class Sensor(Protocol):
    """Something that can read part of the world cheaply and silently."""

    @property
    def name(self) -> str: ...

    def sample(self) -> Sequence[Observation]: ...


def _run_git(repo_root: Path, args: Sequence[str]) -> str | None:
    """Run one git command, returning stripped stdout or None if unavailable.

    Returns None rather than raising: a sensor that cannot read is a sensor with
    nothing to report, not a failed tick.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=SENSOR_TIMEOUT_S,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("git %s unavailable: %s", " ".join(args), exc)
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


class RepoSensor:
    """Repository state: branch, working tree, and position against upstream.

    This is the part of your world that moves most while you are not looking —
    commits land, the tree goes dirty, a branch falls behind.
    """

    topic_branch = "repo.branch"
    topic_tree = "repo.worktree"
    topic_upstream = "repo.upstream"

    def __init__(self, repo_root: Path | str) -> None:
        self._root = Path(repo_root)

    @property
    def name(self) -> str:
        return "repo"

    def sample(self) -> list[Observation]:
        if not (self._root / ".git").exists():
            return []
        now = time.time()
        out: list[Observation] = []

        branch = _run_git(self._root, ["rev-parse", "--abbrev-ref", "HEAD"])
        if branch:
            out.append(Observation(self.topic_branch, "current", branch, now))

        head = _run_git(self._root, ["rev-parse", "HEAD"])
        if head:
            out.append(Observation(self.topic_branch, "head", head[:12], now, {"sha": head}))

        status = _run_git(self._root, ["status", "--porcelain"])
        if status is not None:
            dirty = [line for line in status.splitlines() if line.strip()]
            out.append(
                Observation(
                    self.topic_tree,
                    "dirty_files",
                    str(len(dirty)),
                    now,
                    {"paths": [line[3:] for line in dirty[:20]]},
                )
            )

        counts = _run_git(self._root, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
        if counts:
            parts = counts.split()
            if len(parts) == 2:
                out.append(Observation(self.topic_upstream, "ahead", parts[0], now))
                out.append(Observation(self.topic_upstream, "behind", parts[1], now))
        return out


class GoalsSensor:
    """Open goals from persistence — the raw material for the Debt drive.

    Imported lazily and defensively: the aliveness loop must be startable in a
    process where persistence is not configured, and an unavailable store means
    "nothing to report", never a crashed tick.
    """

    topic = "goals.open"

    @property
    def name(self) -> str:
        return "goals"

    def _open_goals(self) -> list[dict[str, Any]]:
        try:
            from thomas.core.persistence import get_persistence

            goals = get_persistence().open_goals()
        except (ImportError, ModuleNotFoundError, AttributeError, OSError, ValueError) as exc:
            log.debug("GoalsSensor: goals unavailable: %s", exc)
            return []
        if not isinstance(goals, list):
            return []
        return [g for g in goals if isinstance(g, dict)]

    def sample(self) -> list[Observation]:
        goals = self._open_goals()
        now = time.time()
        out = [Observation(self.topic, "count", str(len(goals)), now)]
        for goal in goals:
            goal_id = str(goal.get("id") or "").strip()
            if not goal_id:
                continue
            out.append(
                Observation(
                    self.topic,
                    f"goal:{goal_id}",
                    str(goal.get("status") or "open"),
                    now,
                    {"text": str(goal.get("text") or "")[:200]},
                )
            )
        return out


class WorldModel:
    """Successive sweeps of the sensors, diffed into changes.

    The first sweep establishes a baseline. By default its observations are not
    reported as changes — on a cold start every fact in the world is "new", and
    treating that as news would hand the drives a spike that means nothing.
    """

    def __init__(self, sensors: Iterable[Sensor] | None = None) -> None:
        self._sensors: list[Sensor] = list(sensors or [])
        self._snapshot: dict[tuple[str, str], Observation] = {}
        self._sweeps: int = 0
        self._last_sweep_at: float | None = None
        self._failures: dict[str, int] = {}
        self._quarantined: set[str] = set()

    def add_sensor(self, sensor: Sensor) -> None:
        self._sensors.append(sensor)

    @property
    def sweeps(self) -> int:
        return self._sweeps

    @property
    def last_sweep_at(self) -> float | None:
        return self._last_sweep_at

    def topics(self) -> list[str]:
        """Every topic the world currently knows about, sorted."""
        return sorted({topic for topic, _ in self._snapshot})

    def snapshot(self) -> dict[tuple[str, str], Observation]:
        return dict(self._snapshot)

    @property
    def quarantined(self) -> set[str]:
        """Sensors dropped after failing :data:`SENSOR_FAILURE_LIMIT` times."""
        return set(self._quarantined)

    @staticmethod
    def _sample_isolated(sensor: Sensor, timeout: float) -> tuple[Any, str | None]:
        """Sample one sensor in its own thread. Returns ``(readings, error)``.

        Nothing a sensor does can reach the caller: an exception of any type
        dies in the worker, and a hang is abandoned at ``timeout``. Both come
        back as an error string rather than propagating.
        """
        box: dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["readings"] = sensor.sample()
            except SENSOR_FAULTS as exc:
                # Named types get a clean message; anything else still dies
                # here, in this thread, and is reported as a missing result.
                box["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=_worker, daemon=True, name=f"sensor-{getattr(sensor, 'name', '?')}")
        worker.start()
        worker.join(timeout=timeout)
        if worker.is_alive():
            return None, f"timed out after {timeout:g}s"
        if "error" in box:
            return None, str(box["error"])
        if "readings" not in box:
            return None, "raised an exception (see traceback above)"
        return box["readings"], None

    def _record_failure(self, name: str, reason: str) -> None:
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count >= SENSOR_FAILURE_LIMIT:
            self._quarantined.add(name)
            log.error("sensor %s failed %d times and is now quarantined: %s", name, count, reason)
        else:
            log.warning("sensor %s failed (%d): %s", name, count, reason)

    def _collect(self) -> list[Observation]:
        seen: list[Observation] = []
        for sensor in self._sensors:
            name = str(getattr(sensor, "name", "?"))
            if name in self._quarantined:
                continue
            readings, error = self._sample_isolated(sensor, SENSOR_SAMPLE_TIMEOUT_S)
            if error is not None:
                self._record_failure(name, error)
                continue
            if not isinstance(readings, (list, tuple)):
                self._record_failure(name, f"returned {type(readings).__name__}, not a sequence")
                continue
            self._failures.pop(name, None)
            seen.extend(r for r in readings if isinstance(r, Observation))
        return seen

    def sweep(self, *, report_first: bool = False) -> list[Change]:
        """Sample every sensor and return what differs from the previous sweep."""
        readings = self._collect()
        current = {obs.identity(): obs for obs in readings}
        baseline = self._snapshot
        first = self._sweeps == 0

        changes: list[Change] = []
        if not first or report_first:
            for identity, obs in current.items():
                previous = baseline.get(identity)
                if previous is not None and previous.value == obs.value:
                    continue
                changes.append(
                    Change(
                        topic=obs.topic,
                        key=obs.key,
                        before=previous.value if previous else None,
                        after=obs.value,
                        at=obs.at,
                        detail=dict(obs.detail),
                    )
                )

        self._snapshot = current
        self._sweeps += 1
        self._last_sweep_at = time.time()
        return changes


def default_sensors(repo_root: Path | str | None = None) -> list[Sensor]:
    """The sensor set the loop starts with when nothing else is configured."""
    sensors: list[Sensor] = [GoalsSensor()]
    if repo_root:
        sensors.insert(0, RepoSensor(repo_root))
    return sensors
