"""CAP-089 acceptance tests: secret canaries prove zero occurrences.

Acceptance line: "Add secret canaries and prove zero occurrences across code,
logs, transcripts, and memory."

Covered here:
- (a) a canary pushed through the REAL audit-log redaction path
  (thomas.server.audit_log.AuditLog) never reaches persisted artifacts —
  the sweep over the audit directory returns zero occurrences;
- (b) a deliberately leaked canary (raw write to a log file and to a sqlite
  store) IS found by the sweep with exact location — the detector detects;
- (c) registry round-trip (mint -> persist -> load), env-overridable path;
- (d) the sweep skips oversized files and handles binary content safely.

Tokens are always minted at runtime — never written literally in this file —
so sweeping the test tree itself stays clean.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from thomas.security import secret_canaries as sc
from thomas.security.secret_canaries import (
    CANARY_RE,
    CanaryError,
    SweepReport,
    load_registry,
    main,
    mint_canary,
    plant_canary_secret,
    register_canary,
    registry_path,
    sweep,
)


@pytest.fixture()
def registry_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    reg = tmp_path / "registry" / "secret_canaries.json"
    monkeypatch.setenv(sc.REGISTRY_ENV, str(reg))
    return reg


# ---------------------------------------------------------------------------
# Minting
# ---------------------------------------------------------------------------


class TestMinting:
    def test_mint_is_deterministic_and_greppable(self) -> None:
        token_a = mint_canary("audit")
        token_b = mint_canary("audit")
        assert token_a == token_b
        assert CANARY_RE.fullmatch(token_a)
        assert token_a.startswith("THOMAS-CANARY-audit-")
        assert len(token_a.rsplit("-", 1)[1]) == 10

    def test_distinct_labels_yield_distinct_tokens(self) -> None:
        assert mint_canary("alpha") != mint_canary("beta")

    @pytest.mark.parametrize("bad", ["", "has space", "-leading", "x" * 80, "semi;colon"])
    def test_invalid_labels_rejected(self, bad: str) -> None:
        with pytest.raises(CanaryError):
            mint_canary(bad)


# ---------------------------------------------------------------------------
# (c) Registry round-trip
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_round_trip_via_env_override(self, registry_file: Path) -> None:
        assert registry_path() == registry_file
        token = register_canary("roundtrip")
        assert registry_file.exists()
        loaded = load_registry()
        assert loaded == {"roundtrip": token}
        # Idempotent re-register keeps the same token.
        assert register_canary("roundtrip") == token
        assert load_registry() == {"roundtrip": token}
        # File is well-formed JSON with a version field.
        data = json.loads(registry_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert data["canaries"]["roundtrip"] == token

    def test_missing_registry_is_empty(self, registry_file: Path) -> None:
        assert load_registry() == {}

    def test_corrupt_registry_raises(self, registry_file: Path) -> None:
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        registry_file.write_text("not json", encoding="utf-8")
        with pytest.raises(CanaryError):
            load_registry()


# ---------------------------------------------------------------------------
# (a) Canary through the REAL audit-log redaction path -> zero occurrences
# ---------------------------------------------------------------------------


class TestAuditRedactionPath:
    def _make_audit_log(self, tmp_path: Path, extra_patterns: list[str] | None = None):
        from thomas.policy.redact import Redactor
        from thomas.server.audit_log import AuditLog

        return AuditLog(path=tmp_path / "artifacts" / "audit.sqlite3", redactor=Redactor(extra_patterns))

    def test_stock_redaction_keeps_canary_out_of_audit_artifacts(self, tmp_path: Path, registry_file: Path) -> None:
        audit = self._make_audit_log(tmp_path)

        def store(token: str) -> None:
            # Realistic carrier forms a leaked secret takes on its way into
            # the audit log: assignment text plus sensitive payload keys.
            audit.log(
                kind="tool_call",
                tool_name="shell",
                reason=f"token={token}",
                payload={"api_key": token, "args": {"secret": token}},
            )

        token = plant_canary_secret(store, label="audit-path")
        report = sweep([tmp_path / "artifacts"])
        assert report.canary_count == 1
        assert report.files_scanned >= 1, "sqlite artifact must be scanned, not skipped"
        assert report.zero_occurrences, f"canary {token!r} leaked: {report.hits}"

    def test_canary_aware_redactor_masks_bare_canary(self, tmp_path: Path, registry_file: Path) -> None:
        # Hardened variant: register CANARY_PATTERN as an additional redaction
        # pattern so even a bare canary in a non-sensitive field is masked.
        audit = self._make_audit_log(tmp_path, extra_patterns=[sc.CANARY_PATTERN])
        token = plant_canary_secret(
            lambda t: audit.log(kind="chat", payload={"note": f"user pasted {t} in chat"}),
            label="bare-canary",
        )
        report = sweep([tmp_path / "artifacts"])
        assert report.zero_occurrences, f"canary {token!r} leaked: {report.hits}"


# ---------------------------------------------------------------------------
# (b) A deliberately leaked canary IS found, with exact location
# ---------------------------------------------------------------------------


class TestDetectorDetects:
    def test_leak_in_text_log_found_with_exact_location(self, tmp_path: Path, registry_file: Path) -> None:
        token = register_canary("leaky-log")
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text(f"line one\nline two\noops {token} leaked\n", encoding="utf-8")

        report = sweep([tmp_path])
        assert not report.zero_occurrences
        assert len(report.hits) == 1
        hit = report.hits[0]
        assert hit.canary == token
        assert hit.label == "leaky-log"
        assert hit.location == str(log_file)
        assert hit.line_no == 3

    def test_leak_inside_sqlite_store_found(self, tmp_path: Path, registry_file: Path) -> None:
        # An unredacted write into a binary (sqlite) memory/transcript store
        # must still be detected: the sweep byte-scans binary files.
        token = register_canary("leaky-db")
        db_path = tmp_path / "memory.sqlite3"
        con = sqlite3.connect(str(db_path))
        try:
            con.execute("CREATE TABLE notes (body TEXT)")
            con.execute("INSERT INTO notes VALUES (?)", (f"raw {token}",))
            con.commit()
        finally:
            con.close()

        report = sweep([tmp_path])
        assert not report.zero_occurrences
        assert any(h.canary == token and h.location == str(db_path) for h in report.hits)

    def test_registry_file_itself_is_never_a_hit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        reg = tmp_path / "secret_canaries.json"
        monkeypatch.setenv(sc.REGISTRY_ENV, str(reg))
        register_canary("self-exclusion")
        report = sweep([tmp_path])
        assert report.zero_occurrences


# ---------------------------------------------------------------------------
# (d) Oversized and binary files are handled safely
# ---------------------------------------------------------------------------


class TestSweepSafety:
    def test_oversized_file_is_skipped(self, tmp_path: Path, registry_file: Path) -> None:
        token = register_canary("oversized")
        big = tmp_path / "big.log"
        big.write_bytes(b"x" * 4096 + token.encode() + b"\n")
        report = sweep([tmp_path], max_file_bytes=1024)
        assert report.files_skipped == 1
        assert report.files_scanned == 0
        assert report.zero_occurrences  # skipped, so no hit — and no crash

    def test_binary_file_with_nul_bytes_scans_safely(self, tmp_path: Path, registry_file: Path) -> None:
        token = register_canary("binary")
        blob = tmp_path / "blob.bin"
        blob.write_bytes(b"\x00\x01\x02" * 100 + token.encode() + b"\x00\xff\xfe")
        report = sweep([tmp_path])
        assert any(h.canary == token for h in report.hits)

    def test_token_split_across_chunk_boundary_is_found(self, tmp_path: Path, registry_file: Path) -> None:
        token = register_canary("boundary")
        payload = b"a" * 10 + token.encode() + b"\n"
        target = tmp_path / "split.log"
        target.write_bytes(payload)
        # Force a tiny chunk size so the token straddles chunks.
        matches = sc._scan_file_for_tokens(target, {token.encode(): ("boundary", token)}, chunk_size=8)
        assert matches == [("boundary", token, 1)]

    def test_skip_dirs_are_pruned(self, tmp_path: Path, registry_file: Path) -> None:
        token = register_canary("gitdir")
        hidden = tmp_path / ".git" / "objects"
        hidden.mkdir(parents=True)
        (hidden / "leak.txt").write_text(token, encoding="utf-8")
        report = sweep([tmp_path])
        assert report.zero_occurrences

    def test_empty_registry_sweeps_to_zero(self, tmp_path: Path, registry_file: Path) -> None:
        (tmp_path / "a.log").write_text("nothing here\n", encoding="utf-8")
        report = sweep([tmp_path])
        assert isinstance(report, SweepReport)
        assert report.canary_count == 0
        assert report.zero_occurrences


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_sweep_exit_zero_and_json_on_clean_tree(
        self, tmp_path: Path, registry_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        register_canary("cli-clean")
        (tmp_path / "clean.log").write_text("all quiet\n", encoding="utf-8")
        rc = main(["--sweep", str(tmp_path / "clean.log")])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["zero_occurrences"] is True
        assert payload["canary_count"] == 1
        assert payload["hits"] == []

    def test_sweep_exit_one_with_hit_location(
        self, tmp_path: Path, registry_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = register_canary("cli-leak")
        leak = tmp_path / "leak.log"
        leak.write_text(f"{token}\n", encoding="utf-8")
        rc = main(["--sweep", str(tmp_path)])
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["zero_occurrences"] is False
        assert payload["hits"][0]["canary"] == token
        assert payload["hits"][0]["location"] == str(leak)
        assert payload["hits"][0]["line_no"] == 1

    def test_mint_registers_and_prints_token(self, registry_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["--mint", "cli-mint"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["label"] == "cli-mint"
        assert CANARY_RE.fullmatch(payload["canary"])
        assert load_registry()["cli-mint"] == payload["canary"]
