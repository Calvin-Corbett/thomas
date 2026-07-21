"""Managed database provisioning for generated (app-builder) apps.

Design goals
------------
* **Own DB per generated app.** :class:`DbProvisioner` provisions a database for
  a generated app through an *injectable* backend. The real default
  (:class:`SqliteDbBackend`) creates a SQLite file the standalone app owns and
  returns a usable connection plus a connection string. A Postgres-style
  connection-string *builder* (:class:`PostgresDsnBackend`) covers the
  credential-gated managed-cloud lane -- it assembles a real DSN but makes **no
  live call** (``connection is None``); running its migrations is deferred to a
  real transport. A hermetic in-memory fake (:class:`FakeDbBackend`) keeps tests
  fully offline.
* **Vendored, standalone migration runner.** :class:`MigrationRunner` applies
  *ordered, versioned* steps to the app's own DB. Applied versions are recorded
  in a ``schema_migrations`` ledger, so already-applied migrations are skipped
  and a re-run is a no-op (idempotent). Each migration is applied inside an
  explicit transaction together with its ledger row, so a failing migration
  rolls back cleanly -- it stops, reports the failed step, and leaves **no
  partial-applied record** for it. The runner depends only on the stdlib and a
  DB-API connection; it is self-contained and travels with the generated app.
* **Deterministic.** ``applied_at`` timestamps come from an injected clock, so
  provisioning is reproducible under test.

Live lane (credential-gated, not exercised here): pair
:class:`PostgresDsnBackend` with a real driver/transport and live credentials,
open a connection from the built DSN, and hand that connection to
:class:`MigrationRunner`. That path is documented, not claimed to have run.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

# Concrete fault types the migration runner treats as a *migration failure* (as
# opposed to a programming error it should not swallow). A wide, specific tuple
# -- never a bare ``except Exception`` -- so an unexpected fault still surfaces.
MIGRATION_FAULT_TYPES: tuple[type[BaseException], ...] = (
    sqlite3.Error,
    ValueError,
    TypeError,
    KeyError,
    RuntimeError,
    ArithmeticError,
)

_LEDGER_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "version INTEGER PRIMARY KEY, "
    "name TEXT NOT NULL, "
    "applied_at TEXT NOT NULL, "
    "checksum TEXT NOT NULL)"
)


def _default_clock() -> float:
    return time.time()


def _redact(secret: str | None) -> str:
    """Return a non-reversible fingerprint of a secret, safe to log."""
    if not secret:
        return "<none>"
    text = str(secret)
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}…({len(text)} chars)"


# ---------------------------------------------------------------------------
# Migration model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Migration:
    """One ordered, versioned migration step.

    ``statements`` are executed in order on the app's connection; the optional
    ``apply`` callable runs afterwards for data migrations that need Python. Both
    run inside the same transaction as the ledger insert, so a failure at any
    point rolls the whole step back.
    """

    version: int
    name: str
    statements: tuple[str, ...] = ()
    apply: Callable[[Any], None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise ValueError(f"migration version must be an int, got {self.version!r}")
        if self.version < 1:
            raise ValueError(f"migration version must be >= 1, got {self.version}")
        if not self.name:
            raise ValueError(f"migration {self.version} must have a non-empty name")

    def checksum(self) -> str:
        """Deterministic fingerprint of the step's SQL (tamper visibility)."""
        h = hashlib.sha256()
        h.update(f"v{self.version}:{self.name}".encode())
        for stmt in self.statements:
            h.update(b"\x00")
            h.update(stmt.encode("utf-8"))
        if self.apply is not None:
            h.update(b"\x00callable:")
            h.update(getattr(self.apply, "__name__", "anonymous").encode("utf-8"))
        return h.hexdigest()


class MigrationError(RuntimeError):
    """Raised when a migration step fails; names the failed step."""

    def __init__(self, *, version: int, name: str, cause: str) -> None:
        self.version = version
        self.name = name
        self.cause = cause
        super().__init__(f"migration {version} ({name}) failed and was rolled back: {cause}")


@dataclass(frozen=True)
class MigrationOutcome:
    """Result of considering one migration during a run."""

    version: int
    name: str
    status: str  # "applied" | "skipped"
    checksum: str
    applied_at: str | None = None

    @property
    def applied(self) -> bool:
        return self.status == "applied"


@dataclass(frozen=True)
class MigrationRun:
    """Result of running the ordered migration set once."""

    outcomes: tuple[MigrationOutcome, ...]
    schema_version: int

    @property
    def applied(self) -> tuple[MigrationOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "applied")

    @property
    def skipped(self) -> tuple[MigrationOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "skipped")

    @property
    def is_noop(self) -> bool:
        return not self.applied


# ---------------------------------------------------------------------------
# Migration runner (vendored / standalone)
# ---------------------------------------------------------------------------


class MigrationRunner:
    """Applies ordered, versioned migrations to an app's DB-API connection.

    Idempotent: versions already present in ``schema_migrations`` are skipped, so
    a re-run is a no-op. Atomic: each migration and its ledger row commit
    together, so a failure leaves no partial-applied record.

    The connection MUST be in autocommit mode (``isolation_level=None`` for
    sqlite3) so the runner can manage explicit ``BEGIN``/``COMMIT``/``ROLLBACK``
    transactions that also wrap DDL. The provided backends open connections that
    way.
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        fault_types: tuple[type[BaseException], ...] = MIGRATION_FAULT_TYPES,
    ) -> None:
        self._clock = clock or _default_clock
        self._fault_types = fault_types

    @staticmethod
    def _order(migrations: Iterable[Migration]) -> list[Migration]:
        ordered = sorted(migrations, key=lambda m: m.version)
        seen: set[int] = set()
        for m in ordered:
            if m.version in seen:
                raise ValueError(f"duplicate migration version: {m.version}")
            seen.add(m.version)
        return ordered

    def _ensure_ledger(self, conn: Any) -> None:
        conn.execute(_LEDGER_DDL)

    def applied_versions(self, conn: Any) -> set[int]:
        """Return the set of versions recorded as applied (creates ledger)."""
        self._ensure_ledger(conn)
        cur = conn.execute("SELECT version FROM schema_migrations")
        return {int(row[0]) for row in cur.fetchall()}

    def current_version(self, conn: Any) -> int:
        applied = self.applied_versions(conn)
        return max(applied) if applied else 0

    def _existing_row(self, conn: Any, version: int) -> tuple[str, str, str] | None:
        cur = conn.execute(
            "SELECT name, applied_at, checksum FROM schema_migrations WHERE version = ?",
            (version,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return (str(row[0]), str(row[1]), str(row[2]))

    def _safe_rollback(self, conn: Any) -> None:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error as exc:  # concrete: rollback outside a txn is benign
            logger.debug("migration.rollback.noop error=%s", exc)

    def run(self, conn: Any, migrations: Iterable[Migration]) -> MigrationRun:
        """Apply ``migrations`` in version order; skip already-applied ones."""
        ordered = self._order(migrations)
        applied_versions = self.applied_versions(conn)
        outcomes: list[MigrationOutcome] = []

        for migration in ordered:
            checksum = migration.checksum()
            if migration.version in applied_versions:
                existing = self._existing_row(conn, migration.version)
                applied_at = existing[1] if existing else None
                outcomes.append(
                    MigrationOutcome(
                        version=migration.version,
                        name=migration.name,
                        status="skipped",
                        checksum=existing[2] if existing else checksum,
                        applied_at=applied_at,
                    )
                )
                continue

            applied_at = f"{float(self._clock()):.6f}"
            try:
                conn.execute("BEGIN")
                for statement in migration.statements:
                    conn.execute(statement)
                if migration.apply is not None:
                    migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, applied_at, checksum),
                )
                conn.execute("COMMIT")
            except self._fault_types as exc:
                self._safe_rollback(conn)
                logger.error(
                    "migration.failed version=%s name=%s error=%s",
                    migration.version,
                    migration.name,
                    exc,
                )
                raise MigrationError(version=migration.version, name=migration.name, cause=str(exc)) from exc

            applied_versions.add(migration.version)
            outcomes.append(
                MigrationOutcome(
                    version=migration.version,
                    name=migration.name,
                    status="applied",
                    checksum=checksum,
                    applied_at=applied_at,
                )
            )
            logger.info("migration.applied version=%s name=%s", migration.version, migration.name)

        schema_version = max(applied_versions) if applied_versions else 0
        return MigrationRun(outcomes=tuple(outcomes), schema_version=schema_version)


# ---------------------------------------------------------------------------
# Backend model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppSpec:
    """The generated app a database is being provisioned for."""

    app_id: str
    db_name: str = ""
    migrations: tuple[Migration, ...] = ()


@dataclass
class ProvisionedDb:
    """A provisioned database returned by a backend.

    ``connection`` is a live DB-API connection (autocommit) for backends that
    can connect locally, or ``None`` for the credential-gated DSN-only lane
    (migrations are then deferred to a real transport).
    """

    engine: str
    dsn: str
    connection: Any | None
    created: bool
    live_call_made: bool = False


@runtime_checkable
class DbBackend(Protocol):
    """Injectable database backend."""

    engine: str

    def provision(self, app: AppSpec) -> ProvisionedDb: ...


def sqlite_path_from_dsn(dsn: str) -> Path:
    """Extract the filesystem path from a ``sqlite:///`` DSN."""
    prefix = "sqlite:///"
    if not dsn.startswith(prefix):
        raise ValueError(f"not a sqlite DSN: {dsn!r}")
    return Path(dsn[len(prefix) :])


def connect_sqlite(dsn: str) -> sqlite3.Connection:
    """Open an autocommit sqlite connection from a ``sqlite:///`` DSN.

    Proves the connection string returned by provisioning is independently
    usable (not just the cached handle).
    """
    path = sqlite_path_from_dsn(dsn)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


class SqliteDbBackend:
    """Real default backend -- a SQLite file the standalone app owns.

    Creates (or reuses) ``<root>/<db_name>`` and returns a live autocommit
    connection plus a ``sqlite:///`` connection string. Fully local; no cloud
    call.
    """

    engine = "sqlite"

    def __init__(self, root: Path | str, *, connect: Callable[[str], sqlite3.Connection] | None = None) -> None:
        self._root = Path(root)
        self._connect = connect or self._default_connect

    @staticmethod
    def _default_connect(path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def provision(self, app: AppSpec) -> ProvisionedDb:
        self._root.mkdir(parents=True, exist_ok=True)
        db_name = app.db_name or f"{app.app_id}.db"
        path = (self._root / db_name).resolve()
        created = not path.exists()
        conn = self._connect(str(path))
        dsn = f"sqlite:///{path.as_posix()}"
        logger.info(
            "db.provisioned engine=sqlite app=%s path=%s created=%s",
            app.app_id,
            path.name,
            created,
        )
        return ProvisionedDb(engine=self.engine, dsn=dsn, connection=conn, created=created, live_call_made=False)


def build_postgres_dsn(
    *,
    host: str,
    database: str,
    user: str,
    password: str,
    port: int = 5432,
    sslmode: str = "require",
) -> str:
    """Assemble a standard ``postgresql://`` connection string (no live call)."""
    userinfo = quote(user, safe="")
    if password:
        userinfo = f"{userinfo}:{quote(password, safe='')}"
    query = f"?sslmode={quote(sslmode, safe='')}" if sslmode else ""
    return f"postgresql://{userinfo}@{host}:{int(port)}/{quote(database, safe='')}{query}"


class PostgresDsnBackend:
    """Credential-gated managed-Postgres lane -- builds a DSN, makes no call.

    Assembles the exact ``postgresql://`` connection string a managed instance
    would expose, but returns ``connection=None`` so migrations are deferred to a
    real transport. Credentials are held privately and only ever logged redacted.
    """

    engine = "postgres"

    def __init__(
        self,
        *,
        host: str,
        user: str,
        password: str,
        database: str = "",
        port: int = 5432,
        sslmode: str = "require",
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._database = database
        self._port = int(port)
        self._sslmode = sslmode

    def provision(self, app: AppSpec) -> ProvisionedDb:
        database = self._database or app.db_name or app.app_id
        dsn = build_postgres_dsn(
            host=self._host,
            database=database,
            user=self._user,
            password=self._password,
            port=self._port,
            sslmode=self._sslmode,
        )
        logger.info(
            "db.provisioned engine=postgres app=%s host=%s db=%s user=%s live_call=%s",
            app.app_id,
            self._host,
            database,
            _redact(self._user),
            False,
        )
        return ProvisionedDb(engine=self.engine, dsn=dsn, connection=None, created=False, live_call_made=False)


class FakeDbBackend:
    """Hermetic in-memory backend for tests -- no files, no network.

    Backs each app with a private ``:memory:`` sqlite database so the full
    migration runner still exercises real SQL, while nothing touches disk or the
    cloud.
    """

    engine = "fake"

    def __init__(self) -> None:
        self.provisioned: list[str] = []

    def provision(self, app: AppSpec) -> ProvisionedDb:
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.row_factory = sqlite3.Row
        self.provisioned.append(app.app_id)
        return ProvisionedDb(
            engine=self.engine,
            dsn=f"fake:///{app.app_id}",
            connection=conn,
            created=True,
            live_call_made=False,
        )


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of provisioning a database for a generated app."""

    app_id: str
    engine: str
    connection_ref: str
    connection: Any | None
    migrations: MigrationRun
    created: bool
    migrations_deferred: bool = False
    live_call_made: bool = False

    @property
    def schema_version(self) -> int:
        return self.migrations.schema_version

    @property
    def applied_migrations(self) -> tuple[MigrationOutcome, ...]:
        return self.migrations.applied


class DbProvisioner:
    """Provisions a managed database for a generated app and migrates it.

    ``provision(app)`` provisions the app's DB through the injected backend, runs
    the app's ordered migrations against it (when the backend yields a live
    connection), and returns a :class:`ProvisionResult` carrying the connection
    ref, the applied migrations, and the resulting schema version.
    """

    def __init__(
        self,
        backend: DbBackend,
        *,
        runner: MigrationRunner | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._backend = backend
        self._runner = runner or MigrationRunner(clock=clock)

    @property
    def backend(self) -> DbBackend:
        return self._backend

    def provision(self, app: AppSpec, *, migrations: Sequence[Migration] | None = None) -> ProvisionResult:
        steps: tuple[Migration, ...] = tuple(migrations) if migrations is not None else app.migrations
        provisioned = self._backend.provision(app)

        if provisioned.connection is None:
            # Credential-gated DSN-only lane: migrations deferred to a real
            # transport. Report honestly rather than pretending they ran.
            logger.info(
                "db.migrations.deferred engine=%s app=%s reason=no-live-connection",
                provisioned.engine,
                app.app_id,
            )
            return ProvisionResult(
                app_id=app.app_id,
                engine=provisioned.engine,
                connection_ref=provisioned.dsn,
                connection=None,
                migrations=MigrationRun(outcomes=(), schema_version=0),
                created=provisioned.created,
                migrations_deferred=True,
                live_call_made=provisioned.live_call_made,
            )

        run = self._runner.run(provisioned.connection, steps)
        logger.info(
            "db.provision.complete engine=%s app=%s applied=%d schema_version=%d",
            provisioned.engine,
            app.app_id,
            len(run.applied),
            run.schema_version,
        )
        return ProvisionResult(
            app_id=app.app_id,
            engine=provisioned.engine,
            connection_ref=provisioned.dsn,
            connection=provisioned.connection,
            migrations=run,
            created=provisioned.created,
            migrations_deferred=False,
            live_call_made=provisioned.live_call_made,
        )
