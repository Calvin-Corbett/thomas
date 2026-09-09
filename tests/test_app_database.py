"""Hermetic acceptance tests for CAP-117 managed DB provisioning.

Proves the exact L2 acceptance line against a temp SQLite database (no network,
injected clock, temp dirs):

* provisioning creates the DB and returns a usable connection ref;
* the migration runner applies ordered migrations and records them;
* a re-run skips already-applied migrations (idempotent no-op);
* a failing migration stops and reports the failed step without leaving a
  partial-applied record for it;
* the schema version reflects the latest applied migration;
* full round-trip read/write through the returned connection ref.
"""

from __future__ import annotations

import sqlite3

import pytest

from thomas.marketplace.app_provisioning.database import (
    AppSpec,
    DbProvisioner,
    FakeDbBackend,
    Migration,
    MigrationError,
    MigrationRunner,
    PostgresDsnBackend,
    ProvisionResult,
    SqliteDbBackend,
    build_postgres_dsn,
    connect_sqlite,
    sqlite_path_from_dsn,
)


class _FixedClock:
    """Deterministic injected clock -- advances by a fixed step per call."""

    def __init__(self, start: float = 1000.0, step: float = 1.0) -> None:
        self._t = start
        self._step = step

    def __call__(self) -> float:
        value = self._t
        self._t += self._step
        return value


def _todo_migrations() -> tuple[Migration, ...]:
    return (
        Migration(
            version=1,
            name="create_todos",
            statements=(
                "CREATE TABLE todos (id INTEGER PRIMARY KEY, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)",
            ),
        ),
        Migration(
            version=2,
            name="add_priority",
            statements=("ALTER TABLE todos ADD COLUMN priority INTEGER NOT NULL DEFAULT 0",),
        ),
        Migration(
            version=3,
            name="seed_default",
            statements=("INSERT INTO todos (title, done, priority) VALUES ('welcome', 0, 5)",),
        ),
    )


def _provisioner(tmp_path) -> DbProvisioner:
    backend = SqliteDbBackend(tmp_path / "apps")
    return DbProvisioner(backend, runner=MigrationRunner(clock=_FixedClock()))


# ---------------------------------------------------------------------------
# Provisioning creates the DB + returns a usable connection ref
# ---------------------------------------------------------------------------


def test_provision_creates_db_and_usable_connection_ref(tmp_path):
    provisioner = _provisioner(tmp_path)
    app = AppSpec(app_id="notes-app", migrations=_todo_migrations())

    result = provisioner.provision(app)

    assert isinstance(result, ProvisionResult)
    assert result.created is True
    assert result.engine == "sqlite"
    assert result.connection_ref.startswith("sqlite:///")

    # The DB file the app owns was actually created on disk.
    db_path = sqlite_path_from_dsn(result.connection_ref)
    assert db_path.exists()
    assert db_path.parent == (tmp_path / "apps").resolve()

    # The connection ref is independently usable: reopen a *fresh* connection
    # from the DSN string and read schema through it.
    fresh = connect_sqlite(result.connection_ref)
    try:
        names = {row[0] for row in fresh.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        fresh.close()
    assert "todos" in names
    assert "schema_migrations" in names


# ---------------------------------------------------------------------------
# Ordered migrations applied + recorded; schema version reflects latest
# ---------------------------------------------------------------------------


def test_migrations_applied_in_order_and_recorded(tmp_path):
    provisioner = _provisioner(tmp_path)
    app = AppSpec(app_id="notes-app", migrations=_todo_migrations())

    result = provisioner.provision(app)

    applied = [o.version for o in result.applied_migrations]
    assert applied == [1, 2, 3]  # ordered
    assert result.schema_version == 3  # latest applied

    # Every applied step is recorded in the ledger with a deterministic ts.
    rows = result.connection.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    recorded = [(int(r[0]), str(r[1])) for r in rows]
    assert recorded == [(1, "create_todos"), (2, "add_priority"), (3, "seed_default")]
    # Deterministic clock -> deterministic applied_at values.
    assert [str(r[2]) for r in rows] == ["1000.000000", "1001.000000", "1002.000000"]


def test_migrations_applied_even_when_versions_supplied_unordered(tmp_path):
    provisioner = _provisioner(tmp_path)
    app = AppSpec(app_id="scrambled")
    m1, m2, m3 = _todo_migrations()

    result = provisioner.provision(app, migrations=(m3, m1, m2))

    assert [o.version for o in result.applied_migrations] == [1, 2, 3]
    assert result.schema_version == 3


# ---------------------------------------------------------------------------
# Re-run is an idempotent no-op
# ---------------------------------------------------------------------------


def test_rerun_skips_already_applied(tmp_path):
    root = tmp_path / "apps"
    app = AppSpec(app_id="notes-app", migrations=_todo_migrations())

    first = DbProvisioner(SqliteDbBackend(root), runner=MigrationRunner(clock=_FixedClock())).provision(app)
    assert first.created is True
    assert len(first.applied_migrations) == 3

    # Re-provision the same app (same file on disk).
    second = DbProvisioner(SqliteDbBackend(root), runner=MigrationRunner(clock=_FixedClock())).provision(app)

    assert second.created is False  # DB already existed
    assert second.migrations.is_noop is True
    assert second.applied_migrations == ()  # nothing re-applied
    assert {o.status for o in second.migrations.outcomes} == {"skipped"}
    assert second.schema_version == 3  # unchanged

    # No duplicate ledger rows.
    count = second.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 3


# ---------------------------------------------------------------------------
# Failing migration: stops, reports the step, no partial-applied record
# ---------------------------------------------------------------------------


def test_failing_migration_stops_without_partial_record(tmp_path):
    provisioner = _provisioner(tmp_path)
    app = AppSpec(app_id="broken")
    migrations = (
        Migration(version=1, name="create_a", statements=("CREATE TABLE a (id INTEGER PRIMARY KEY)",)),
        Migration(version=2, name="create_b", statements=("CREATE TABLE b (id INTEGER PRIMARY KEY)",)),
        # v3: first statement is valid, second is invalid SQL -> whole step must
        # roll back, including the valid first statement (no partial apply).
        Migration(
            version=3,
            name="broken_step",
            statements=(
                "CREATE TABLE c (id INTEGER PRIMARY KEY)",
                "CREATE TABLE c_bad (this is not valid sql",
            ),
        ),
    )

    with pytest.raises(MigrationError) as excinfo:
        provisioner.provision(app, migrations=migrations)

    # Reports the failed step precisely.
    assert excinfo.value.version == 3
    assert excinfo.value.name == "broken_step"

    # Inspect the DB directly: earlier migrations survived, the failed one left
    # no ledger row and no partially-created table.
    backend = SqliteDbBackend(tmp_path / "apps")
    prov = backend.provision(app)
    conn = prov.connection
    try:
        runner = MigrationRunner()
        assert runner.applied_versions(conn) == {1, 2}  # v3 NOT recorded
        assert runner.current_version(conn) == 2  # schema version = latest good

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "a" in tables
        assert "b" in tables
        assert "c" not in tables  # first statement of v3 was rolled back
        assert "c_bad" not in tables
    finally:
        conn.close()


def test_runner_run_raises_and_leaves_prior_state(tmp_path):
    # Direct runner-level assertion of atomic rollback semantics.
    conn = sqlite3.connect(":memory:", isolation_level=None)
    runner = MigrationRunner(clock=_FixedClock())
    good = Migration(version=1, name="ok", statements=("CREATE TABLE t (id INTEGER)",))
    bad = Migration(version=2, name="boom", statements=("INSERT INTO does_not_exist VALUES (1)",))

    with pytest.raises(MigrationError) as excinfo:
        runner.run(conn, (good, bad))

    assert excinfo.value.version == 2
    assert runner.applied_versions(conn) == {1}
    assert runner.current_version(conn) == 1


# ---------------------------------------------------------------------------
# Round-trip write/read through the provisioned connection
# ---------------------------------------------------------------------------


def test_round_trip_through_provisioned_connection(tmp_path):
    provisioner = _provisioner(tmp_path)
    app = AppSpec(app_id="notes-app", migrations=_todo_migrations())

    result = provisioner.provision(app)
    conn = result.connection

    conn.execute("INSERT INTO todos (title, done, priority) VALUES (?, ?, ?)", ("write tests", 0, 9))
    row = conn.execute("SELECT title, done, priority FROM todos WHERE title = ?", ("write tests",)).fetchone()
    assert (row[0], row[1], row[2]) == ("write tests", 0, 9)

    # The seed migration row is also present -> ordered migrations + writes coexist.
    seeded = conn.execute("SELECT title FROM todos WHERE title = 'welcome'").fetchone()
    assert seeded is not None

    # Round-trip survives reopening from the connection ref.
    conn.close()
    reopened = connect_sqlite(result.connection_ref)
    try:
        titles = {r[0] for r in reopened.execute("SELECT title FROM todos").fetchall()}
    finally:
        reopened.close()
    assert titles == {"welcome", "write tests"}


# ---------------------------------------------------------------------------
# Injectable adapters: hermetic fake + credential-gated Postgres DSN lane
# ---------------------------------------------------------------------------


def test_fake_backend_runs_full_migration_cycle_in_memory():
    backend = FakeDbBackend()
    provisioner = DbProvisioner(backend, runner=MigrationRunner(clock=_FixedClock()))
    app = AppSpec(app_id="hermetic", migrations=_todo_migrations())

    result = provisioner.provision(app)

    assert backend.provisioned == ["hermetic"]
    assert result.engine == "fake"
    assert result.schema_version == 3
    assert [o.version for o in result.applied_migrations] == [1, 2, 3]


def test_postgres_dsn_lane_builds_connection_string_without_live_call():
    backend = PostgresDsnBackend(host="db.internal", user="app_user", password="s3cr3t/pw", database="appdb")
    provisioner = DbProvisioner(backend)
    app = AppSpec(app_id="cloud-app", migrations=_todo_migrations())

    result = provisioner.provision(app)

    assert result.engine == "postgres"
    assert result.connection is None
    assert result.live_call_made is False
    assert result.migrations_deferred is True  # migrations deferred, not faked
    assert result.applied_migrations == ()
    assert result.schema_version == 0
    # A real, correctly-escaped DSN was assembled.
    assert result.connection_ref.startswith("postgresql://app_user:")
    assert "@db.internal:5432/appdb" in result.connection_ref
    assert "sslmode=require" in result.connection_ref
    # Special characters in the password are percent-encoded.
    assert "s3cr3t%2Fpw" in result.connection_ref


def test_build_postgres_dsn_escapes_credentials():
    dsn = build_postgres_dsn(host="h", database="d", user="u@x", password="p:w/d", port=6543, sslmode="disable")
    assert dsn == "postgresql://u%40x:p%3Aw%2Fd@h:6543/d?sslmode=disable"


def test_duplicate_migration_versions_rejected(tmp_path):
    provisioner = _provisioner(tmp_path)
    app = AppSpec(app_id="dup")
    migrations = (
        Migration(version=1, name="a", statements=("CREATE TABLE a (id INTEGER)",)),
        Migration(version=1, name="b", statements=("CREATE TABLE b (id INTEGER)",)),
    )
    with pytest.raises(ValueError, match="duplicate migration version"):
        provisioner.provision(app, migrations=migrations)


def test_migration_validation_rejects_bad_version():
    with pytest.raises(ValueError, match="version must be >= 1"):
        Migration(version=0, name="x")
    with pytest.raises(ValueError, match="non-empty name"):
        Migration(version=1, name="")
