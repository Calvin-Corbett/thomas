"""CAP-080 L2: automation templates with integrated history + configured-channel
exception reports.

An :class:`AutomationTemplateRegistry` is the durable home for *automation
templates* -- named, versioned automation definitions -- and gives them the two
capabilities the frontier rubric requires at Level 2:

1. **Integrated template history.** Every change to a template (``create`` or
   ``update``) is recorded as a :class:`TemplateVersion` carrying its own
   monotonically increasing version number. The full edit history is inspectable
   (:meth:`AutomationTemplateRegistry.history`) and any *prior* version is
   recoverable -- either read back verbatim (:meth:`version`) or promoted back
   to current (:meth:`restore`). History is never rewritten; updates only append.

2. **Configured-channel exception reports.** Each template names a *configured
   channel* (an opaque routing key such as ``"email:ops"`` or
   ``"slack:#alerts"``). When an automation run raises an exception,
   :meth:`run` builds a structured :class:`ExceptionReport` -- carrying the
   automation id, the version that was running, the error, and the run context
   -- and routes it to *that automation's configured channel only*. Channel
   sinks are injected (:meth:`register_channel`); a sink registered for a
   different channel never receives the report. A template with no configured
   channel is handled gracefully: the report is retained for inspection and is
   not misrouted to any channel.

Persistence: templates, their full history, and every generated report are
persisted as JSON. The store path is overridable via the constructor or the
``THOMAS_AUTOMATION_TEMPLATES_FILE`` environment variable, so state survives a
restart of the host process.

Determinism / hermeticity: the registry takes an **injected clock** (any
zero-arg callable returning a float "seconds" value). No wall-clock sleeps,
network, or real processes are used, so behaviour is fully reproducible.

This module depends only on the standard library (tools-tier rule: no imports
from ``agent``/``server``/``cli``).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ClockFn = Callable[[], float]
# A channel sink receives a fully-built exception report for delivery.
ChannelSink = Callable[["ExceptionReport"], None]

TEMPLATES_PATH_ENV = "THOMAS_AUTOMATION_TEMPLATES_FILE"

CHANGE_CREATE = "create"
CHANGE_UPDATE = "update"
CHANGE_RESTORE = "restore"

# Sentinel so callers can distinguish "leave the channel unchanged" from
# "explicitly set the configured channel to None".
_UNSET: Any = object()


@dataclass(frozen=True)
class TemplateVersion:
    """One immutable revision of an automation template.

    Attributes:
        automation_id: The template / automation identifier.
        version: 1-based, monotonically increasing revision number.
        definition: The automation definition body for this revision (an
            arbitrary JSON-serializable mapping).
        channel: The configured exception channel for this revision, or
            ``None`` if the automation has no configured channel.
        change: Why this revision exists -- ``"create"``, ``"update"``, or
            ``"restore"``.
        at: Injected-clock timestamp when this revision was recorded.
    """

    automation_id: str
    version: int
    definition: dict[str, Any]
    channel: str | None
    change: str
    at: float


@dataclass(frozen=True)
class ExceptionReport:
    """Structured report produced when an automation run raises.

    Attributes:
        automation_id: The automation whose run failed.
        version: The template version that was running when it failed.
        channel: The automation's configured channel this report targets, or
            ``None`` when the automation has no configured channel.
        error_type: The exception class name (e.g. ``"ValueError"``).
        error_message: ``str(exception)``.
        context: The run context supplied to :meth:`run` (copied).
        at: Injected-clock timestamp when the failure was observed.
        delivered: ``True`` if the report was handed to a registered channel
            sink; ``False`` if it was retained (no configured channel, or no
            sink registered for the configured channel).
    """

    automation_id: str
    version: int
    channel: str | None
    error_type: str
    error_message: str
    context: dict[str, Any]
    at: float
    delivered: bool


@dataclass
class _Template:
    """Mutable in-memory record: the ordered version history of one template."""

    automation_id: str
    versions: list[TemplateVersion] = field(default_factory=list)

    @property
    def current(self) -> TemplateVersion:
        return self.versions[-1]


def _default_templates_path() -> Path:
    env = os.environ.get(TEMPLATES_PATH_ENV, "").strip()
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "thomas_automation" / "templates.json"


class AutomationTemplateRegistry:
    """Durable registry of versioned automation templates with integrated
    history and configured-channel exception-report routing.

    Args:
        clock: Zero-arg callable returning the current time in seconds. Every
            timestamp (version ``at``, report ``at``) is read from this, so
            tests can inject a controllable fake clock for determinism.
        store_path: Where the JSON store lives. Defaults to the
            ``THOMAS_AUTOMATION_TEMPLATES_FILE`` environment variable, else a
            file under the system temp directory.
    """

    def __init__(
        self,
        *,
        clock: ClockFn,
        store_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._clock = clock
        self._store_path = Path(store_path) if store_path is not None else _default_templates_path()
        self._lock = threading.RLock()
        self._channels: dict[str, ChannelSink] = {}
        self._templates: dict[str, _Template] = {}
        self._reports: list[ExceptionReport] = []
        self._load()

    # -- channel wiring ----------------------------------------------------

    def register_channel(self, channel: str, sink: ChannelSink) -> None:
        """Wire a channel routing key (e.g. ``"email:ops"``) to a sink callable.

        The sink is invoked with the :class:`ExceptionReport` whenever an
        automation *configured for this channel* fails. Sinks are not persisted;
        they are re-registered by the host on each process start.
        """
        with self._lock:
            self._channels[channel] = sink

    # -- template authoring ------------------------------------------------

    def create(
        self,
        automation_id: str,
        definition: dict[str, Any],
        *,
        channel: str | None = None,
    ) -> TemplateVersion:
        """Create version 1 of a new automation template.

        Args:
            automation_id: Unique template id.
            definition: The automation definition body (JSON-serializable).
            channel: Configured exception channel, or ``None``.

        Returns:
            The newly recorded :class:`TemplateVersion` (version 1).

        Raises:
            ValueError: If ``automation_id`` already exists.
        """
        with self._lock:
            if automation_id in self._templates:
                raise ValueError(f"template {automation_id!r} already exists")
            tmpl = _Template(automation_id=automation_id)
            self._templates[automation_id] = tmpl
            return self._append_version(tmpl, definition, channel, CHANGE_CREATE)

    def update(
        self,
        automation_id: str,
        definition: dict[str, Any],
        *,
        channel: Any = _UNSET,
    ) -> TemplateVersion:
        """Record a new version of an existing template.

        Args:
            automation_id: Id of an existing template.
            definition: The new definition body for this revision.
            channel: New configured channel. Omit to carry the current
                channel forward unchanged; pass ``None`` to explicitly clear it.

        Returns:
            The newly recorded :class:`TemplateVersion`.

        Raises:
            KeyError: If ``automation_id`` does not exist.
        """
        with self._lock:
            tmpl = self._require(automation_id)
            resolved = tmpl.current.channel if channel is _UNSET else channel
            return self._append_version(tmpl, definition, resolved, CHANGE_UPDATE)

    def restore(self, automation_id: str, version: int) -> TemplateVersion:
        """Recover a prior version by promoting it to a new current version.

        The recovered definition and channel are re-appended as a fresh
        revision (``change="restore"``); history is preserved, not rewound.

        Raises:
            KeyError: If the template does not exist.
            IndexError: If ``version`` is out of range.
        """
        with self._lock:
            tmpl = self._require(automation_id)
            prior = self._get_version(tmpl, version)
            return self._append_version(tmpl, copy.deepcopy(prior.definition), prior.channel, CHANGE_RESTORE)

    def _append_version(
        self,
        tmpl: _Template,
        definition: dict[str, Any],
        channel: str | None,
        change: str,
    ) -> TemplateVersion:
        rev = TemplateVersion(
            automation_id=tmpl.automation_id,
            version=len(tmpl.versions) + 1,
            definition=copy.deepcopy(definition),
            channel=channel,
            change=change,
            at=self._clock(),
        )
        tmpl.versions.append(rev)
        self._save()
        return rev

    # -- template inspection ----------------------------------------------

    def current(self, automation_id: str) -> TemplateVersion:
        """Return the latest version of a template."""
        with self._lock:
            return self._require(automation_id).current

    def history(self, automation_id: str) -> list[TemplateVersion]:
        """Return the full ordered version history of a template."""
        with self._lock:
            return list(self._require(automation_id).versions)

    def version(self, automation_id: str, version: int) -> TemplateVersion:
        """Return a specific (possibly prior) version verbatim.

        Raises:
            KeyError: If the template does not exist.
            IndexError: If ``version`` is out of range.
        """
        with self._lock:
            return self._get_version(self._require(automation_id), version)

    def template_ids(self) -> list[str]:
        """Return the ids of all registered templates, in creation order."""
        with self._lock:
            return list(self._templates)

    # -- running with configured-channel exception reports -----------------

    def run(
        self,
        automation_id: str,
        action: Callable[[], Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an automation's ``action`` under its current template.

        On success the action's return value is passed through. If ``action``
        raises, a structured :class:`ExceptionReport` is built (carrying the
        automation id, running version, error, and ``context``), routed to the
        automation's configured channel sink *only*, retained for inspection,
        and then the original exception is re-raised.

        Args:
            automation_id: Id of a registered template to run.
            action: Zero-arg callable performing the automation's work.
            context: Optional run context recorded on any exception report.

        Raises:
            KeyError: If ``automation_id`` is not a registered template.
            Exception: Re-raises whatever ``action`` raised, after reporting.
        """
        with self._lock:
            current = self._require(automation_id).current
        try:
            return action()
        except Exception as exc:
            report = self._build_and_route_report(current, exc, context)
            logger.warning(
                "automation %r (v%d) raised %s; report routed=%s channel=%r",
                automation_id,
                current.version,
                report.error_type,
                report.delivered,
                report.channel,
            )
            raise

    def _build_and_route_report(
        self,
        current: TemplateVersion,
        exc: BaseException,
        context: dict[str, Any] | None,
    ) -> ExceptionReport:
        with self._lock:
            channel = current.channel
            sink = self._channels.get(channel) if channel is not None else None
            report = ExceptionReport(
                automation_id=current.automation_id,
                version=current.version,
                channel=channel,
                error_type=type(exc).__name__,
                error_message=str(exc),
                context=copy.deepcopy(context) if context else {},
                at=self._clock(),
                delivered=sink is not None,
            )
            self._reports.append(report)
            self._save()
        # Deliver outside the lock so a sink cannot deadlock on the registry.
        if sink is not None:
            sink(report)
        return report

    def reports(self, automation_id: str | None = None) -> list[ExceptionReport]:
        """Return all generated exception reports, optionally filtered by id."""
        with self._lock:
            if automation_id is None:
                return list(self._reports)
            return [r for r in self._reports if r.automation_id == automation_id]

    def retained_reports(self) -> list[ExceptionReport]:
        """Return reports that were retained rather than delivered to a sink."""
        with self._lock:
            return [r for r in self._reports if not r.delivered]

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("could not load templates from %s (%s); starting empty", self._store_path, e)
            return
        for automation_id, body in raw.get("templates", {}).items():
            versions = [
                TemplateVersion(
                    automation_id=automation_id,
                    version=int(v["version"]),
                    definition=dict(v.get("definition", {})),
                    channel=v.get("channel"),
                    change=str(v.get("change", CHANGE_UPDATE)),
                    at=float(v.get("at", 0.0)),
                )
                for v in body.get("versions", [])
            ]
            if versions:
                self._templates[automation_id] = _Template(automation_id=automation_id, versions=versions)
        for r in raw.get("reports", []):
            self._reports.append(
                ExceptionReport(
                    automation_id=str(r.get("automation_id", "")),
                    version=int(r.get("version", 0)),
                    channel=r.get("channel"),
                    error_type=str(r.get("error_type", "")),
                    error_message=str(r.get("error_message", "")),
                    context=dict(r.get("context", {})),
                    at=float(r.get("at", 0.0)),
                    delivered=bool(r.get("delivered", False)),
                )
            )

    def _save(self) -> None:
        payload = {
            "templates": {
                automation_id: {"versions": [asdict(v) for v in tmpl.versions]}
                for automation_id, tmpl in self._templates.items()
            },
            "reports": [asdict(r) for r in self._reports],
        }
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._store_path)
        except OSError as e:
            logger.warning("could not persist templates to %s (%s)", self._store_path, e)

    # -- internals ---------------------------------------------------------

    def _require(self, automation_id: str) -> _Template:
        tmpl = self._templates.get(automation_id)
        if tmpl is None:
            raise KeyError(f"template {automation_id!r} is not registered")
        return tmpl

    @staticmethod
    def _get_version(tmpl: _Template, version: int) -> TemplateVersion:
        if version < 1 or version > len(tmpl.versions):
            raise IndexError(f"template {tmpl.automation_id!r} has no version {version}")
        return tmpl.versions[version - 1]
