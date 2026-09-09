"""CAP-073: Breadth connectors -- a governed productivity/deploy connector set.

This module builds *on top of* the CAP-074 BYO connector contract
(:mod:`thomas.integrations.byo_connector`). It ships three first-class
connectors that model the productivity/deploy surface every workspace needs:

* :class:`DocsConnector`   -- a docs/notes app (create/read/list/delete a doc).
* :class:`IssueConnector`  -- a task/issue tracker (create/read/list/delete a task).
* :class:`DeployConnector` -- a deploy recorder (record/read/list/delete a deploy).

Each connector implements the ``byo_connector.Connector`` contract by
subclassing :class:`~thomas.integrations.byo_connector.BaseConnector`, and each
talks to an **injectable backend** (the "external edge"):

* :class:`FileStorageBackend`     -- the REAL default. A durable local store
  backed by stdlib ``json`` under a directory. No new dependencies, no network.
* :class:`InMemoryStorageBackend` -- the hermetic FAKE used by tests: pure
  in-process dicts, deterministic, no disk.

A production deployment swaps the backend for a real SaaS HTTP client (Notion,
Jira, a deploy API). That live lane is *credential-gated and not implemented
here*; the contract and the composed-workflow logic are fully implemented and
proven offline against the fake.

On top of the connectors sit two governed pieces:

1. :class:`GovernancePolicy` + :class:`GovernedConnectorSuite` -- an allow/deny
   policy over *(connector, action)* pairs. A denied action is refused with a
   structured ``ok=False`` envelope carrying the reason; it never reaches the
   connector.

2. :class:`WorkflowRunner` -- a composed cross-app workflow runner. It chains
   actions across two or more connectors, passing outputs of earlier steps into
   the params of later steps (via :class:`Ref` bindings), with a choice of
   **all-or-nothing** (atomic; completed steps are compensated/rolled back on a
   later failure) or **recorded-partial** (committed steps are kept and the
   failure is surfaced explicitly -- never silently dropped) semantics.

Everything is hermetic and deterministic given an injected clock and the
in-memory backend.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from thomas.integrations.byo_connector import BaseConnector, run_conformance

logger = logging.getLogger(__name__)

# Reserved id prefix for conformance fixtures. A connector seeds one fixture per
# read action so that the byo conformance harness (which invokes each declared
# capability's ``sample`` once) gets an ``ok=True`` envelope for reads without
# the fixture leaking into user-visible ``list`` results.
FIXTURE_PREFIX = "__cf__"


# ---------------------------------------------------------------------------
# Injectable backend (the external edge)
# ---------------------------------------------------------------------------
@runtime_checkable
class StorageBackend(Protocol):
    """A namespaced record store. The seam a real SaaS client plugs into."""

    def put(self, namespace: str, key: str, value: Mapping[str, Any]) -> None: ...

    def get(self, namespace: str, key: str) -> dict[str, Any] | None: ...

    def list(self, namespace: str) -> list[dict[str, Any]]: ...

    def delete(self, namespace: str, key: str) -> bool: ...


class InMemoryStorageBackend:
    """Hermetic fake backend: pure in-process dicts. Deterministic, no disk."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def put(self, namespace: str, key: str, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._data.setdefault(namespace, {})[key] = dict(value)

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._data.get(namespace, {}).get(key)
            return dict(record) if record is not None else None

    def list(self, namespace: str) -> list[dict[str, Any]]:
        with self._lock:
            records = self._data.get(namespace, {})
            return [dict(v) for _, v in sorted(records.items())]

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            return self._data.get(namespace, {}).pop(key, None) is not None


class FileStorageBackend:
    """Real default backend: one ``<namespace>.json`` file per namespace.

    Durable, dependency-free (stdlib ``json`` + ``pathlib``), and safe for
    arbitrary keys because keys are dict entries inside the file rather than
    file names. This is the local stand-in for a real SaaS store.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, namespace: str) -> Path:
        safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in namespace)
        return self._root / f"{safe}.json"

    def _load(self, namespace: str) -> dict[str, dict[str, Any]]:
        path = self._path(namespace)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("connector_suite: unreadable store %s: %s", path, exc)
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, namespace: str, data: Mapping[str, dict[str, Any]]) -> None:
        path = self._path(namespace)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    def put(self, namespace: str, key: str, value: Mapping[str, Any]) -> None:
        with self._lock:
            data = self._load(namespace)
            data[key] = dict(value)
            self._save(namespace, data)

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._load(namespace).get(key)
            return dict(record) if record is not None else None

    def list(self, namespace: str) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load(namespace)
            return [dict(data[k]) for k in sorted(data)]

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            data = self._load(namespace)
            existed = data.pop(key, None) is not None
            if existed:
                self._save(namespace, data)
            return existed


# A clock is any zero-arg callable returning a monotonic-ish integer timestamp.
Clock = Callable[[], int]


def _wall_clock() -> int:
    return time.time_ns()


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------
class _SuiteConnector(BaseConnector):
    """Shared plumbing for the suite's connectors.

    Concrete subclasses set ``NAME``/``VERSION``/``NAMESPACE``/``ID_PREFIX`` and
    implement :meth:`capabilities` and :meth:`handle`. This base wires an
    injected backend + clock, deterministic id generation, and a per-read
    conformance fixture so each connector certifies against the byo harness.
    """

    NAME: str = ""
    VERSION: str = "1.0"
    NAMESPACE: str = ""
    ID_PREFIX: str = "rec"
    DESCRIPTION: str = ""

    def __init__(self, backend: StorageBackend, *, clock: Clock | None = None) -> None:
        self._backend = backend
        self._clock = clock or _wall_clock
        self._seq = itertools.count(1)
        self._seed_fixture()

    # -- contract surface --------------------------------------------------
    def metadata(self) -> Mapping[str, Any]:
        return {"name": self.NAME, "version": self.VERSION, "description": self.DESCRIPTION}

    # -- helpers -----------------------------------------------------------
    @property
    def fixture_id(self) -> str:
        return f"{FIXTURE_PREFIX}{self.NAMESPACE}"

    def _seed_fixture(self) -> None:
        """Seed the reserved read fixture the conformance sample points at."""
        record = self._fixture_record()
        self._backend.put(self.NAMESPACE, self.fixture_id, record)

    def _fixture_record(self) -> dict[str, Any]:  # overridden per connector
        return {"id": self.fixture_id, "created_at": 0}

    def _next_id(self) -> str:
        return f"{self.ID_PREFIX}-{next(self._seq)}"

    def _require(self, params: Mapping[str, Any], key: str) -> Any:
        if key not in params or params[key] in (None, ""):
            raise ValueError(f"missing required param {key!r}")
        return params[key]

    def _store(self, record: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(record)
        self._backend.put(self.NAMESPACE, str(record["id"]), record)
        return record

    def _fetch(self, key: str) -> dict[str, Any]:
        record = self._backend.get(self.NAMESPACE, key)
        if record is None:
            raise ValueError(f"{self.NAMESPACE} {key!r} not found")
        return record

    def _visible(self) -> list[dict[str, Any]]:
        return [r for r in self._backend.list(self.NAMESPACE) if not str(r.get("id", "")).startswith(FIXTURE_PREFIX)]

    def _delete(self, key: str) -> dict[str, Any]:
        # Idempotent: deleting a missing record is not an error (keeps the
        # compensation path and the conformance sample robust).
        existed = self._backend.delete(self.NAMESPACE, key)
        return {"deleted": key, "existed": existed}


class DocsConnector(_SuiteConnector):
    """A docs/notes connector (create a doc, read it back, list, delete)."""

    NAME = "docs"
    VERSION = "1.0"
    NAMESPACE = "docs"
    ID_PREFIX = "doc"
    DESCRIPTION = "Documents / notes productivity connector"

    def _fixture_record(self) -> dict[str, Any]:
        return {"id": self.fixture_id, "title": "Fixture", "body": "", "created_at": 0}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [
            {"action": "create_doc", "description": "Create a document", "sample": {"title": "Sample", "body": "hi"}},
            {"action": "get_doc", "description": "Fetch a document by id", "sample": {"id": self.fixture_id}},
            {"action": "list_docs", "description": "List documents", "sample": {}},
            {"action": "delete_doc", "description": "Delete a document by id", "sample": {"id": self.fixture_id}},
        ]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        if action == "create_doc":
            title = self._require(params, "title")
            record = {
                "id": self._next_id(),
                "title": str(title),
                "body": str(params.get("body", "")),
                "created_at": self._clock(),
            }
            return self._store(record)
        if action == "get_doc":
            return self._fetch(str(self._require(params, "id")))
        if action == "list_docs":
            return {"docs": self._visible()}
        if action == "delete_doc":
            return self._delete(str(self._require(params, "id")))
        raise KeyError(action)


class IssueConnector(_SuiteConnector):
    """A task/issue tracker connector (create/read/list/delete a task)."""

    NAME = "issues"
    VERSION = "1.0"
    NAMESPACE = "issues"
    ID_PREFIX = "task"
    DESCRIPTION = "Task / issue tracker connector"

    def _fixture_record(self) -> dict[str, Any]:
        return {"id": self.fixture_id, "title": "Fixture", "description": "", "status": "open", "created_at": 0}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [
            {"action": "create_task", "description": "Create a task", "sample": {"title": "Sample task"}},
            {"action": "get_task", "description": "Fetch a task by id", "sample": {"id": self.fixture_id}},
            {"action": "list_tasks", "description": "List tasks", "sample": {}},
            {"action": "delete_task", "description": "Delete a task by id", "sample": {"id": self.fixture_id}},
        ]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        if action == "create_task":
            title = self._require(params, "title")
            record = {
                "id": self._next_id(),
                "title": str(title),
                "description": str(params.get("description", "")),
                "status": str(params.get("status", "open")),
                "created_at": self._clock(),
            }
            return self._store(record)
        if action == "get_task":
            return self._fetch(str(self._require(params, "id")))
        if action == "list_tasks":
            return {"tasks": self._visible()}
        if action == "delete_task":
            return self._delete(str(self._require(params, "id")))
        raise KeyError(action)


class DeployConnector(_SuiteConnector):
    """A deploy-recorder connector (record/read/list/delete a deploy)."""

    NAME = "deploy"
    VERSION = "1.0"
    NAMESPACE = "deploys"
    ID_PREFIX = "deploy"
    DESCRIPTION = "Deploy recorder connector"

    def _fixture_record(self) -> dict[str, Any]:
        return {"id": self.fixture_id, "service": "fixture", "ref": "", "status": "recorded", "created_at": 0}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [
            {"action": "record_deploy", "description": "Record a deploy", "sample": {"service": "web", "ref": "v1"}},
            {"action": "get_deploy", "description": "Fetch a deploy by id", "sample": {"id": self.fixture_id}},
            {"action": "list_deploys", "description": "List deploys", "sample": {}},
            {"action": "delete_deploy", "description": "Delete a deploy by id", "sample": {"id": self.fixture_id}},
        ]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        if action == "record_deploy":
            service = self._require(params, "service")
            record = {
                "id": self._next_id(),
                "service": str(service),
                "ref": str(params.get("ref", "")),
                "doc_id": str(params.get("doc_id", "")),
                "status": "recorded",
                "created_at": self._clock(),
            }
            return self._store(record)
        if action == "get_deploy":
            return self._fetch(str(self._require(params, "id")))
        if action == "list_deploys":
            return {"deploys": self._visible()}
        if action == "delete_deploy":
            return self._delete(str(self._require(params, "id")))
        raise KeyError(action)


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GovernanceDecision:
    """The outcome of consulting the policy for one *(connector, action)*."""

    allowed: bool
    reason: str


@dataclass(frozen=True)
class GovernancePolicy:
    """Allow/deny policy over *(connector, action)* pairs.

    ``deny`` always wins over ``allow``. Within either map, the sentinel
    action ``"*"`` matches every action on that connector. When neither map
    decides, ``default_allow`` is the fallback.
    """

    allow: Mapping[str, frozenset[str]] = field(default_factory=dict)
    deny: Mapping[str, frozenset[str]] = field(default_factory=dict)
    default_allow: bool = False

    @classmethod
    def allow_all(cls) -> GovernancePolicy:
        return cls(default_allow=True)

    @staticmethod
    def _matches(rules: Mapping[str, frozenset[str]], connector: str, action: str) -> bool:
        actions = rules.get(connector)
        if actions is None:
            return False
        return "*" in actions or action in actions

    def decide(self, connector: str, action: str) -> GovernanceDecision:
        if self._matches(self.deny, connector, action):
            return GovernanceDecision(False, f"denied by policy: {connector}.{action} is on the deny list")
        if self._matches(self.allow, connector, action):
            return GovernanceDecision(True, f"allowed by policy: {connector}.{action}")
        if self.default_allow:
            return GovernanceDecision(True, f"allowed by default: {connector}.{action}")
        return GovernanceDecision(False, f"denied by default: {connector}.{action} is not on the allow list")


class GovernedConnectorSuite:
    """A named set of connectors fronted by a :class:`GovernancePolicy`.

    :meth:`invoke` consults the policy before touching a connector; a denied
    action returns a structured ``ok=False`` envelope and never reaches the
    connector. :meth:`connector` returns the raw connector for internal use
    (e.g. workflow compensation) and deliberately bypasses governance.
    """

    def __init__(self, connectors: Mapping[str, Any], policy: GovernancePolicy) -> None:
        self._connectors = dict(connectors)
        self._policy = policy

    @property
    def policy(self) -> GovernancePolicy:
        return self._policy

    def names(self) -> list[str]:
        return sorted(self._connectors)

    def connector(self, name: str) -> Any:
        try:
            return self._connectors[name]
        except KeyError:
            raise KeyError(f"unknown connector: {name!r}") from None

    def invoke(self, connector: str, action: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        from thomas.integrations.byo_connector import make_envelope

        if connector not in self._connectors:
            return make_envelope(action, ok=False, error=f"unknown connector: {connector!r}")
        decision = self._policy.decide(connector, action)
        if not decision.allowed:
            return make_envelope(
                action,
                ok=False,
                error=f"governance: {decision.reason}",
                meta={"governed": True, "denied": True, "connector": connector},
            )
        envelope = self._connectors[connector].invoke(action, dict(params or {}))
        return dict(envelope)


# ---------------------------------------------------------------------------
# Composed cross-app workflow
# ---------------------------------------------------------------------------
class WorkflowBindingError(ValueError):
    """Raised when a step binding cannot be resolved from prior outputs."""


@dataclass(frozen=True)
class Ref:
    """A reference to a dotted path inside an earlier step's result payload."""

    step: str
    path: str


@dataclass(frozen=True)
class WorkflowStep:
    """One step in a composed workflow.

    ``params`` are static; ``bindings`` map a param name to a :class:`Ref` into
    an earlier step's result, resolved just before the step runs. ``compensate``
    names an action on the *same* connector that undoes this step during an
    atomic rollback; ``compensate_key`` selects which field of this step's result
    is passed to the compensating action (default ``"id"``).
    """

    id: str
    connector: str
    action: str
    params: Mapping[str, Any] = field(default_factory=dict)
    bindings: Mapping[str, Ref] = field(default_factory=dict)
    compensate: str | None = None
    compensate_key: str = "id"


@dataclass(frozen=True)
class StepReport:
    """Per-step outcome inside a :class:`WorkflowResult`."""

    id: str
    connector: str
    action: str
    status: str  # "ok" | "failed" | "skipped" | "rolled_back"
    ok: bool
    error: str
    result: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connector": self.connector,
            "action": self.action,
            "status": self.status,
            "ok": self.ok,
            "error": self.error,
            "result": self.result,
        }


@dataclass(frozen=True)
class WorkflowResult:
    """The combined result of a composed workflow run."""

    ok: bool
    mode: str  # "atomic" | "partial"
    steps: tuple[StepReport, ...]
    outputs: Mapping[str, Any]
    error: str
    failed_step: str | None

    def committed(self) -> list[str]:
        """Ids of steps whose side effects still stand after the run."""
        return [s.id for s in self.steps if s.status in ("ok", "committed")]

    def report(self, step_id: str) -> StepReport | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "error": self.error,
            "failed_step": self.failed_step,
            "outputs": dict(self.outputs),
            "steps": [s.to_dict() for s in self.steps],
        }


class WorkflowRunner:
    """Runs composed cross-app workflows over a :class:`GovernedConnectorSuite`."""

    def __init__(self, suite: GovernedConnectorSuite) -> None:
        self._suite = suite

    def run(self, steps: Sequence[WorkflowStep], *, atomic: bool = True) -> WorkflowResult:
        """Execute ``steps`` in order, threading outputs into later params.

        With ``atomic=True`` a later failure rolls back every completed step
        (in reverse, via its ``compensate`` action) so nothing persists.
        With ``atomic=False`` completed steps are kept ("recorded-partial") and
        the failure is surfaced explicitly. Either way a failure is never
        silently dropped.
        """
        from thomas.integrations.byo_connector import make_envelope

        mode = "atomic" if atomic else "partial"
        steps = list(steps)
        reports: list[StepReport] = []
        outputs: dict[str, Any] = {}
        executed: list[tuple[WorkflowStep, dict[str, Any]]] = []
        failed_step: str | None = None
        error = ""

        for index, step in enumerate(steps):
            try:
                params = self._resolve_params(step, outputs)
            except WorkflowBindingError as exc:
                envelope = make_envelope(step.action, ok=False, error=str(exc))
            else:
                envelope = self._suite.invoke(step.connector, step.action, params)

            if bool(envelope.get("ok")):
                result = envelope.get("result")
                reports.append(StepReport(step.id, step.connector, step.action, "ok", True, "", result))
                outputs[step.id] = result
                executed.append((step, dict(envelope)))
                continue

            failed_step = step.id
            error = str(envelope.get("error") or "step failed")
            reports.append(
                StepReport(step.id, step.connector, step.action, "failed", False, error, envelope.get("result"))
            )
            for later in steps[index + 1 :]:
                reports.append(StepReport(later.id, later.connector, later.action, "skipped", False, "", None))
            break
        else:
            return WorkflowResult(True, mode, tuple(reports), dict(outputs), "", None)

        if atomic:
            self._rollback(executed)
            rolled = {step.id for step, _ in executed}
            reports = [
                StepReport(r.id, r.connector, r.action, "rolled_back", False, r.error, None) if r.id in rolled else r
                for r in reports
            ]
            outputs = {}
        else:
            reports = [
                StepReport(r.id, r.connector, r.action, "committed", True, "", r.result) if r.status == "ok" else r
                for r in reports
            ]

        return WorkflowResult(False, mode, tuple(reports), dict(outputs), error, failed_step)

    def _resolve_params(self, step: WorkflowStep, outputs: Mapping[str, Any]) -> dict[str, Any]:
        params = dict(step.params)
        for key, ref in step.bindings.items():
            params[key] = self._resolve_ref(ref, outputs)
        return params

    @staticmethod
    def _resolve_ref(ref: Ref, outputs: Mapping[str, Any]) -> Any:
        if ref.step not in outputs:
            raise WorkflowBindingError(f"binding references unknown step {ref.step!r}")
        value: Any = outputs[ref.step]
        for part in ref.path.split("."):
            if not part:
                continue
            if not isinstance(value, Mapping) or part not in value:
                raise WorkflowBindingError(f"binding path {ref.path!r} not found in step {ref.step!r} result")
            value = value[part]
        return value

    def _rollback(self, executed: Sequence[tuple[WorkflowStep, dict[str, Any]]]) -> None:
        for step, envelope in reversed(list(executed)):
            if not step.compensate:
                continue
            result = envelope.get("result")
            target = result.get(step.compensate_key) if isinstance(result, Mapping) else None
            if target is None:
                continue
            try:
                # Compensation bypasses governance: the forward action was already
                # permitted, so its rollback must not be blockable.
                self._suite.connector(step.connector).invoke(step.compensate, {step.compensate_key: target})
            except (ValueError, TypeError, LookupError, RuntimeError) as exc:
                logger.warning("connector_suite: compensation for step %s failed: %s", step.id, exc)


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------
def build_connectors(backend: StorageBackend, *, clock: Clock | None = None) -> dict[str, Any]:
    """Instantiate the governed connector set against a shared backend."""
    return {
        "docs": DocsConnector(backend, clock=clock),
        "issues": IssueConnector(backend, clock=clock),
        "deploy": DeployConnector(backend, clock=clock),
    }


def build_connector_suite(
    *,
    backend: StorageBackend | None = None,
    root: str | Path | None = None,
    clock: Clock | None = None,
    policy: GovernancePolicy | None = None,
) -> GovernedConnectorSuite:
    """Build a ready-to-use governed suite.

    Backend selection: an explicit ``backend`` wins; otherwise a ``root`` path
    yields the real :class:`FileStorageBackend`; otherwise an in-memory fake.
    ``policy`` defaults to allow-all (callers tighten it as needed).
    """
    if backend is None:
        backend = FileStorageBackend(root) if root is not None else InMemoryStorageBackend()
    connectors = build_connectors(backend, clock=clock)
    return GovernedConnectorSuite(connectors, policy or GovernancePolicy.allow_all())


def certify_suite(suite: GovernedConnectorSuite, *, timeout: float = 5.0) -> dict[str, bool]:
    """Run the byo conformance harness over every connector in the suite."""
    result: dict[str, bool] = {}
    for name in suite.names():
        report = run_conformance(suite.connector(name), timeout=timeout)
        result[name] = report.certified
    return result


__all__ = [
    "FIXTURE_PREFIX",
    "StorageBackend",
    "InMemoryStorageBackend",
    "FileStorageBackend",
    "Clock",
    "DocsConnector",
    "IssueConnector",
    "DeployConnector",
    "GovernanceDecision",
    "GovernancePolicy",
    "GovernedConnectorSuite",
    "WorkflowBindingError",
    "Ref",
    "WorkflowStep",
    "StepReport",
    "WorkflowResult",
    "WorkflowRunner",
    "build_connectors",
    "build_connector_suite",
    "certify_suite",
]
