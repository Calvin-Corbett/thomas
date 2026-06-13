"""Regression tests for the single-instance duplicate-server sweep.

The sweep in ``_check_single_instance`` used to SIGTERM every process whose
command line matched ``-m thomas.server`` / ``-m thomas serve`` — including
live servers from other installs/worktrees on other ports. The kill decision
is now scoped: a name match alone never kills; there must be positive
evidence the process holds OUR port.
"""

from __future__ import annotations

from thomas.server.app_lifecycle import (
    _explicit_cmdline_port,
    _filter_duplicate_server_candidates,
    _is_conflicting_duplicate,
    _process_family,
)


class TestExplicitCmdlinePort:
    def test_no_port_flag(self):
        assert _explicit_cmdline_port("python -m thomas serve") is None

    def test_space_form(self):
        assert _explicit_cmdline_port("python -m thomas serve --port 9001") == 9001

    def test_equals_form(self):
        assert _explicit_cmdline_port("python -m thomas serve --port=9001") == 9001

    def test_empty_and_none(self):
        assert _explicit_cmdline_port("") is None
        assert _explicit_cmdline_port(None) is None  # type: ignore[arg-type]


class TestIsConflictingDuplicate:
    PORT = 8899

    def test_explicit_other_port_never_killed(self):
        # Another worktree's server on its own port: must survive even if the
        # listener probe is unavailable or noisy.
        assert not _is_conflicting_duplicate(1234, "python -m thomas serve --port 9001", self.PORT, None)
        assert not _is_conflicting_duplicate(1234, "python -m thomas serve --port 9001", self.PORT, {1234})

    def test_explicit_same_port_killed(self):
        assert _is_conflicting_duplicate(1234, f"python -m thomas serve --port {self.PORT}", self.PORT, None)

    def test_listener_on_our_port_killed(self):
        assert _is_conflicting_duplicate(1234, "python -m thomas serve", self.PORT, {1234})

    def test_no_evidence_survives(self):
        # Name match alone, not listening on our port: leave it alone.
        assert not _is_conflicting_duplicate(1234, "python -m thomas serve", self.PORT, {5678})

    def test_probe_unavailable_fails_safe(self):
        # Listener probe unknowable + no explicit port: do NOT kill.
        assert not _is_conflicting_duplicate(1234, "python -m thomas serve", self.PORT, None)


SERVE_CMD = r"C:\x\.venv\Scripts\python.exe -u -m thomas serve --port 8899"


class TestProcessFamilyExclusion:
    """The Windows venv launcher runs the real interpreter as a child with an
    identical command line. The sweep must never offer up our own lineage —
    killing the launcher kills the new server via its job object."""

    def test_family_includes_ancestors_and_children(self):
        #  shell(1) -> venv launcher(10) -> us(20) -> our child(30); stranger(40)
        pid_to_ppid = {1: None, 10: 1, 20: 10, 30: 20, 40: 1}
        fam = _process_family(pid_to_ppid, 20)
        assert fam == {20, 10, 1, 30}

    def test_ppid_cycle_does_not_hang(self):
        pid_to_ppid = {10: 20, 20: 10}
        fam = _process_family(pid_to_ppid, 20)
        assert 20 in fam

    def test_own_venv_launcher_not_a_candidate(self):
        rows = [
            (10, 1, "python.exe", SERVE_CMD),  # our venv launcher (parent)
            (20, 10, "python.exe", SERVE_CMD),  # us
            (99, 1, "python.exe", SERVE_CMD),  # genuinely separate server
        ]
        assert _filter_duplicate_server_candidates(rows, 20) == [(99, SERVE_CMD)]

    def test_non_python_processes_ignored(self):
        rows = [(50, 1, "bash.exe", SERVE_CMD), (60, 1, "python.exe", "python -m other")]
        assert _filter_duplicate_server_candidates(rows, 20) == []

    def test_grandparent_excluded(self):
        rows = [
            (1, None, "python.exe", SERVE_CMD),  # grandparent shim
            (10, 1, "python.exe", SERVE_CMD),  # parent launcher
            (20, 10, "python.exe", SERVE_CMD),  # us
        ]
        assert _filter_duplicate_server_candidates(rows, 20) == []
