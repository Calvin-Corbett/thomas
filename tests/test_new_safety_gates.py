"""Tests for safety gates added in the 2026-03-19 adversarial audit.

Each test verifies both the positive case (violation detected) and
negative case (clean code passes) to prevent false positives.
"""

import re
import sys
from pathlib import Path

import pytest

# Add scripts/ to import path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from forge.gates.circular_imports_gate import FORBIDDEN_PAIRS, _extract_thomas_imports
from forge.gates.duplicate_filename_gate import FORBIDDEN_PREFIXES, FORBIDDEN_SUFFIXES, _is_scoped_code_file
from forge.gates.exception_handler_gate import (
    _find_broad_handlers,
)
import check_protected_files_gate as protected_gate
from check_protected_files_gate import PROTECTED_ENFORCEMENT_SCRIPTS, PROTECTED_FILES

# ──────────────────────────────────────────────
# Exception Handler Gate Tests
# ──────────────────────────────────────────────


class TestExceptionHandlerGate:
    """Tests for exception_handler_gate.py."""

    def test_catches_bare_except(self):
        """Bare `except:` without logging+reraise should be caught."""
        source = "def f():\n    try:\n        x()\n    except:\n        pass\n"
        violations = _find_broad_handlers(source)
        assert len(violations) == 1

    def test_catches_except_exception(self):
        """except Exception without logging+reraise should be caught."""
        source = "def f():\n    try:\n        x()\n    except Exception:\n        pass\n"
        violations = _find_broad_handlers(source)
        assert len(violations) == 1

    def test_catches_except_base_exception(self):
        """except BaseException without logging+reraise should be caught."""
        source = "def f():\n    try:\n        x()\n    except BaseException:\n        pass\n"
        violations = _find_broad_handlers(source)
        assert len(violations) == 1

    def test_allows_specific_exception(self):
        """Specific exception types should always pass."""
        source = "def f():\n    try:\n        x()\n    except ValueError:\n        pass\n"
        violations = _find_broad_handlers(source)
        assert len(violations) == 0

    def test_allows_broad_with_log_and_reraise(self):
        """Broad except with BOTH logging and re-raise should pass."""
        source = (
            "def f():\n"
            "    try:\n"
            "        x()\n"
            "    except Exception as e:\n"
            '        logger.exception("failed")\n'
            "        raise\n"
        )
        violations = _find_broad_handlers(source)
        assert len(violations) == 0

    def test_rejects_broad_with_only_log(self):
        """Broad except with logging but NO re-raise should be caught."""
        source = (
            "def f():\n"
            "    try:\n"
            "        x()\n"
            "    except Exception as e:\n"
            '        logger.exception("failed")\n'
            "        return None\n"
        )
        violations = _find_broad_handlers(source)
        assert len(violations) == 1

    def test_rejects_broad_with_only_reraise(self):
        """Broad except with re-raise but NO logging should be caught."""
        source = "def f():\n" "    try:\n" "        x()\n" "    except Exception as e:\n" "        raise\n"
        violations = _find_broad_handlers(source)
        assert len(violations) == 1

    def test_multiple_handlers(self):
        """Only broad handlers should be flagged; specific ones should pass."""
        source = (
            "def f():\n"
            "    try:\n"
            "        x()\n"
            "    except ValueError:\n"
            "        pass\n"
            "    except Exception:\n"
            "        pass\n"
        )
        violations = _find_broad_handlers(source)
        assert len(violations) == 1

    def test_syntax_error_returns_empty(self):
        """Files with syntax errors should return empty (caught by other gate)."""
        source = "def f(\n    broken\n"
        violations = _find_broad_handlers(source)
        assert len(violations) == 0


# ──────────────────────────────────────────────
# Duplicate Filename Gate Tests
# ──────────────────────────────────────────────


class TestDuplicateFilenameGate:
    """Tests for duplicate_filename_gate.py."""

    @pytest.mark.parametrize(
        "name",
        [
            "utils_v2.py",
            "helper_new.py",
            "config_fixed.py",
            "store_copy.py",
            "handler_backup.py",
            "routes_old.py",
            "service_updated.py",
            "parser_revised.py",
            "manager_alt.py",
            "worker_temp.py",
            "cache_wip.js",
        ],
    )
    def test_catches_forbidden_suffixes(self, name):
        """Files with duplication-signaling suffixes should be caught."""
        assert FORBIDDEN_SUFFIXES.search(name) is not None, f"{name} should be caught"

    @pytest.mark.parametrize(
        "name",
        [
            "utils-v2.py",
            "helper-fixed.py",
            "cache-temp.js",
        ],
    )
    def test_catches_hyphenated_suffixes(self, name):
        """Hyphenated duplication-signaling suffixes should be caught too."""
        assert FORBIDDEN_SUFFIXES.search(name) is not None, f"{name} should be caught"

    @pytest.mark.parametrize(
        "name",
        [
            "new_config.py",
            "copy_of_utils.py",
            "backup_store.py",
            "old_routes.py",
        ],
    )
    def test_catches_forbidden_prefixes(self, name):
        """Files with duplication-signaling prefixes should be caught."""
        assert FORBIDDEN_PREFIXES.match(name) is not None, f"{name} should be caught"

    @pytest.mark.parametrize(
        "name",
        [
            "curator_cleanup.py",
            "mission_routing.py",
            "memory_store.py",
            "fabric_weaving.py",
            "swarm_execution.py",
            "tone_definitions.py",
            "event_bus.py",
            "app_runtime_loader.js",
        ],
    )
    def test_allows_clean_names(self, name):
        """Descriptive split-strategy names should NOT be caught."""
        suffix_match = FORBIDDEN_SUFFIXES.search(name)
        prefix_match = FORBIDDEN_PREFIXES.match(name)
        assert suffix_match is None and prefix_match is None, f"{name} should be allowed"

    def test_scans_scripts_scope(self):
        """scripts/ should be scanned, not just thomas/."""
        assert _is_scoped_code_file("scripts/evil_v2.py") is True
        assert _is_scoped_code_file("docs/evil_v2.py") is False


# ──────────────────────────────────────────────
# Circular Imports Gate Tests
# ──────────────────────────────────────────────


class TestCircularImportsGate:
    """Tests for circular_imports_gate.py."""

    def test_detects_standard_import(self):
        """Standard `from thomas.X import Y` should be detected."""
        source = "from thomas.agent import loop\n"
        imports = _extract_thomas_imports(source)
        assert "thomas.agent" in imports

    def test_detects_import_module(self):
        """importlib.import_module('thomas.X') should be detected."""
        source = 'import importlib\nmod = importlib.import_module("thomas.browser.driver")\n'
        imports = _extract_thomas_imports(source)
        assert "thomas.browser" in imports

    def test_detects_plain_import(self):
        """Plain `import thomas.X.Y` should be detected."""
        source = "import thomas.memory.store\n"
        imports = _extract_thomas_imports(source)
        assert "thomas.memory" in imports

    def test_detects_string_reference(self):
        """String references like 'thomas.X' should be detected."""
        source = 'MODULE_NAME = "thomas.server.routes"\n'
        imports = _extract_thomas_imports(source)
        assert "thomas.server" in imports

    def test_ignores_non_thomas_imports(self):
        """Non-thomas imports should not appear."""
        source = "import os\nfrom pathlib import Path\nimport json\n"
        imports = _extract_thomas_imports(source)
        assert len(imports) == 0

    def test_forbidden_pairs_exist(self):
        """The forbidden pairs list should have entries."""
        assert len(FORBIDDEN_PAIRS) >= 5


# ──────────────────────────────────────────────
# Protected Files Gate Tests
# ──────────────────────────────────────────────


class TestProtectedFilesGate:
    """Tests for check_protected_files_gate.py."""

    def test_agents_md_is_protected(self):
        """AGENTS.md is a core policy file and must be protected."""
        assert "AGENTS.md" in PROTECTED_FILES

    def test_guardrails_are_protected(self):
        """All GUARDRAILS.md files should be in the protected list."""
        assert "GUARDRAILS.md" in PROTECTED_FILES
        assert "thomas/server/GUARDRAILS.md" in PROTECTED_FILES
        assert "thomas/memory/GUARDRAILS.md" in PROTECTED_FILES
        assert "thomas/agent/GUARDRAILS.md" in PROTECTED_FILES

    def test_test_architecture_is_protected(self):
        """test_architecture.py should be protected."""
        assert "tests/test_architecture.py" in PROTECTED_FILES

    def test_architecture_module_is_protected(self):
        """_architecture.py should be protected."""
        assert "thomas/_architecture.py" in PROTECTED_FILES

    def test_enforcement_scripts_are_protected(self):
        """Key enforcement scripts should be protected."""
        assert "scripts/validate_agent_changes.py" in PROTECTED_ENFORCEMENT_SCRIPTS
        assert "scripts/check_precommit_skip_policy.py" in PROTECTED_ENFORCEMENT_SCRIPTS

    def test_regular_files_are_not_protected(self):
        """Regular code files should NOT be in the protected list."""
        all_protected = set(PROTECTED_FILES) | set(PROTECTED_ENFORCEMENT_SCRIPTS)
        assert "thomas/server/app.py" not in all_protected
        assert "thomas/agent/loop.py" not in all_protected
        assert "README.md" not in all_protected

    def test_run_blocks_mixed_staged_protected_and_regular_files(self, monkeypatch, capsys):
        """The live gate should fail when any staged path is protected, even in a mixed batch."""
        monkeypatch.setattr(
            protected_gate,
            "_staged_files",
            lambda: ["thomas/server/app.py", "agent_safety.toml", "scripts/agent_safety_config.py"],
        )

        rc = protected_gate.run([])
        out = capsys.readouterr().out

        assert rc == 1
        assert "SAFETY GATE FAILED: Protected Policy Files Modified" in out
        assert "agent_safety.toml" in out
        assert "scripts/agent_safety_config.py" in out
        assert "thomas/server/app.py" not in out

    def test_run_passes_when_only_regular_files_are_staged(self, monkeypatch, capsys):
        """The live gate should pass when staged files stay outside the protected set."""
        monkeypatch.setattr(protected_gate, "_staged_files", lambda: ["thomas/server/app.py", "README.md"])

        rc = protected_gate.run([])
        out = capsys.readouterr().out

        assert rc == 0
        assert "Protected files gate: PASS" in out

    def test_run_blocks_nested_agents_file(self, monkeypatch, capsys):
        """Nested AGENTS.md files should be protected even if config forgot the exact path."""
        monkeypatch.setattr(protected_gate, "_staged_files", lambda: ["apps/site/AGENTS.md"])

        rc = protected_gate.run([])
        out = capsys.readouterr().out

        assert rc == 1
        assert "apps/site/AGENTS.md" in out
        assert "immutable policy document" in out


# ──────────────────────────────────────────────
# Meta-Test: Skip Policy Coverage
# ──────────────────────────────────────────────


class TestSkipPolicyCoverage:
    """Verify that every local pre-commit hook is protected by config-backed skip policy.

    This prevents the gap where a new hook gets added to
    .pre-commit-config.yaml but nobody remembers to add it to
    agent_safety.toml [skip_policy], allowing agents to SKIP it freely.
    """

    def test_all_local_hooks_are_skip_protected(self):
        """Every local hook in .pre-commit-config.yaml should be in the protected skip policy."""
        from check_precommit_skip_policy import _protected_skip_hooks

        config_path = Path(__file__).resolve().parent.parent / ".pre-commit-config.yaml"
        if not config_path.exists():
            pytest.skip("No .pre-commit-config.yaml found")

        content = config_path.read_text(encoding="utf-8")

        # Extract hook IDs from YAML (simple regex — good enough for this)
        hook_ids = re.findall(r"^\s+-\s+id:\s+(.+)$", content, re.MULTILINE)
        local_hooks = [h.strip() for h in hook_ids if h.strip().startswith("thomas-")]

        protected_set = set(_protected_skip_hooks())
        unprotected = [h for h in local_hooks if h not in protected_set]

        assert not unprotected, (
            "These hooks are in .pre-commit-config.yaml but NOT in agent_safety.toml [skip_policy].protected_hooks:\n"
            + "\n".join(f"  - {h}" for h in unprotected)
            + "\n\nAdd them to agent_safety.toml [skip_policy].protected_hooks"
        )


# ──────────────────────────────────────────────
# Worktree Cleanliness Check Tests
# ──────────────────────────────────────────────


class TestWorktreeCleanCheck:
    """Tests for the _check_worktree_clean function in agent_preflight.py."""

    def test_preflight_includes_worktree_check(self):
        """evaluate_preflight should include a worktree-clean check."""
        from agent_preflight import evaluate_preflight

        # We can't guarantee the state, but we CAN verify the check exists
        result = evaluate_preflight()
        check_ids = [c["id"] for c in result["checks"]]
        assert "worktree-clean" in check_ids, (
            "evaluate_preflight() must include a worktree-clean check. "
            "See agent_preflight.py _check_worktree_clean()."
        )

    def test_worktree_check_returns_valid_status(self):
        """Worktree check should return a valid status (ok or degraded)."""
        from agent_preflight import evaluate_preflight

        result = evaluate_preflight()
        wt_check = next(c for c in result["checks"] if c["id"] == "worktree-clean")
        assert wt_check["status"] in (
            "ok",
            "degraded",
            "blocked",
        ), f"worktree-clean returned unexpected status: {wt_check['status']}"


# ──────────────────────────────────────────────
# Type Safety Gate Tests
# ──────────────────────────────────────────────


class TestTypeSafetyGate:
    """Tests for type_safety_gate.py."""

    def test_enabled_modules_exist(self):
        """All configured type-safety files should exist in the repo."""
        from forge.gates.type_safety_gate import _enabled_modules

        repo_root = Path(__file__).resolve().parent.parent
        for module_path in _enabled_modules():
            full_path = repo_root / module_path
            assert full_path.exists(), (
                f"type_safety enabled_files references {module_path} but it doesn't exist. "
                "Remove it from the list or create the file."
            )

    def test_is_enabled_matches_exact_files(self):
        """_is_enabled should match exact file paths."""
        from forge.gates.type_safety_gate import _is_enabled

        assert _is_enabled("thomas/core/__init__.py") is True

    def test_is_enabled_rejects_non_enabled(self):
        """_is_enabled should reject files not in the enabled list."""
        from forge.gates.type_safety_gate import _is_enabled

        assert _is_enabled("thomas/agent/loop.py") is False
        assert _is_enabled("thomas/server/app.py") is False
        assert _is_enabled("README.md") is False


class TestWindowsSafeConsoleOutput:
    """Verify hook output banners stay ASCII-safe on Windows consoles."""

    @pytest.mark.parametrize(
        "script_name",
        [
            "validate_agent_changes.py",
            "forge/gates/duplicate_filename_gate.py",
            "forge/gates/boot_smoke_gate.py",
            "forge/gates/exception_handler_gate.py",
        ],
    )
    def test_no_emoji_banners_in_targeted_hooks(self, script_name):
        script_text = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
        banned_markers = (chr(0x274C), chr(0x2705), chr(0x26A0) + chr(0xFE0F))
        for banned in banned_markers:
            assert banned not in script_text, f"{script_name} still contains {banned!r}"
