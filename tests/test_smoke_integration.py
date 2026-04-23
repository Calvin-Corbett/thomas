"""Integration smoke test for Thomas server boot + core systems.

Verifies that the critical path works end-to-end:
  1. Config loads and validates
  2. Preferences store initializes (SQLite WAL)
  3. Tool registry populates (core + engineering tools)
  4. Context compaction works
  5. Verification hooks work
  6. Autonomy level parsing is coherent
  7. All modified files compile clean

Run:
  python -m pytest tests/test_smoke_integration.py -v
"""

from __future__ import annotations

import asyncio
import py_compile
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---- Test 1: Config loads and validates ----


class TestConfig:
    def test_config_loads(self):
        from thomas.core.config import load_config

        cfg = load_config()
        assert cfg is not None

    def test_config_validates(self):
        from thomas.core.config import load_config

        cfg = load_config()
        errors = cfg.validate()
        assert errors == [], f"Config validation errors: {errors}"

    def test_config_has_model(self):
        from thomas.core.config import load_config

        cfg = load_config()
        assert len(cfg.models) >= 1, "Must have at least one model configured"

    def test_config_bool_coercion_auto_discovers(self):
        from thomas.core.config import _auto_discover_bool_fields

        fields = _auto_discover_bool_fields()
        assert "allow_shell" in fields
        assert "enabled" in fields
        assert "enforce" in fields
        assert len(fields) >= 5, f"Expected 5+ bool fields, got {len(fields)}"


# ---- Test 2: Preferences store ----


class TestPreferences:
    def test_preferences_import(self):
        from thomas.preferences.store import PreferencesStore, get_db_path

        assert PreferencesStore is not None
        assert get_db_path is not None

    def test_preferences_store_init(self, tmp_path):
        from thomas.preferences.store import PreferencesStore

        db_path = str(tmp_path / "test_prefs.db")
        store = PreferencesStore(db_path=db_path)
        assert store is not None

    def test_preferences_get_patch_roundtrip(self, tmp_path):
        from thomas.preferences.store import PreferencesStore

        db_path = str(tmp_path / "test_prefs2.db")
        store = PreferencesStore(db_path=db_path)
        prefs = store.get(user_id="test_user")
        assert prefs is not None
        # Patch should work
        from thomas.preferences.store import PreferencesPatch

        patch = PreferencesPatch.model_validate({"appearance": {"theme": "dark"}})
        updated = store.patch(patch=patch, user_id="test_user")
        assert updated.appearance.theme == "dark"


# ---- Test 3: Tool registry ----


class TestToolRegistry:
    def test_core_tools_register(self):
        from thomas.tools.filesystem import register_filesystem_tools
        from thomas.tools.registry import ToolRegistry

        reg = ToolRegistry()
        register_filesystem_tools(reg, sandbox_root=Path("/tmp"))
        tools = list(reg._tools.keys())
        assert len(tools) >= 1

    def test_engineering_tools_register(self):
        from thomas.tools.engineering import register_engineering_tools
        from thomas.tools.registry import ToolRegistry

        reg = ToolRegistry()
        register_engineering_tools(reg)
        tools = list(reg._tools.keys())
        assert len(tools) == 13, f"Expected 13 engineering tools, got {len(tools)}"
        # Check key tools exist
        assert "eng.system_info" in tools
        assert "eng.lint" in tools
        assert "eng.security_scan" in tools


# ---- Test 4: Context compaction ----


class TestContextCompaction:
    def test_no_compaction_under_budget(self):
        from thomas.agent.context_compaction import compact_conversation

        msgs = [{"role": "user", "content": "Hello"}]
        result = compact_conversation(msgs, target_tokens=10000)
        assert len(result) == 1

    def test_compaction_reduces_size(self):
        from thomas.agent.context_compaction import (
            compact_conversation,
            estimate_conversation_tokens,
        )

        msgs = [{"role": "system", "content": "You are Thomas."}]
        for i in range(30):
            msgs.append({"role": "user", "content": f"Q{i}: " + "x" * 500})
            msgs.append({"role": "assistant", "content": f"A{i}: " + "y" * 1000})
        before = estimate_conversation_tokens(msgs)
        compacted = compact_conversation(msgs, target_tokens=5000, preserve_recent=4)
        after = estimate_conversation_tokens(compacted)
        assert after < before, "Compaction should reduce token count"
        assert after <= 6000, f"Should be near target, got {after}"

    def test_should_compact_detects_threshold(self):
        from thomas.agent.context_compaction import should_compact

        msgs = [{"role": "user", "content": "x" * 50000}]
        assert should_compact(msgs, budget=8000) is True
        small = [{"role": "user", "content": "hi"}]
        assert should_compact(small, budget=8000) is False


# ---- Test 5: Verification hooks ----


class TestVerification:
    def test_non_write_tool_no_issues(self):
        from thomas.agent.verification import verify_after_tool

        loop = asyncio.get_event_loop()
        issues = loop.run_until_complete(verify_after_tool("eng.system_info", {}, True))
        assert issues == []

    def test_format_empty_issues(self):
        from thomas.agent.verification import format_verification_feedback

        assert format_verification_feedback([]) is None

    def test_format_with_issues(self):
        from thomas.agent.verification import format_verification_feedback

        issues = [
            {"level": "error", "check": "syntax", "message": "bad syntax"},
            {"level": "warning", "check": "lint", "message": "unused import"},
        ]
        result = format_verification_feedback(issues)
        assert "ERRORS" in result
        assert "WARNINGS" in result
        assert "bad syntax" in result

    def test_syntax_check_on_valid_py(self, tmp_path):
        from thomas.agent.verification import verify_after_tool

        f = tmp_path / "good.py"
        f.write_text("x = 1\n")
        loop = asyncio.get_event_loop()
        issues = loop.run_until_complete(verify_after_tool("fs.write", {"path": str(f)}, True))
        syntax_errors = [i for i in issues if i["check"] == "syntax"]
        assert len(syntax_errors) == 0

    def test_syntax_check_on_bad_py(self, tmp_path):
        from thomas.agent.verification import verify_after_tool

        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")
        loop = asyncio.get_event_loop()
        issues = loop.run_until_complete(verify_after_tool("fs.write", {"path": str(f)}, True))
        syntax_errors = [i for i in issues if i["check"] == "syntax"]
        assert len(syntax_errors) >= 1


# ---- Test 6: Autonomy level coherence ----


class TestAutonomy:
    def test_parse_string_format(self):
        from thomas.core.autonomy import parse_autonomy_level

        assert parse_autonomy_level("L1") == 1
        assert parse_autonomy_level("L2") == 2
        assert parse_autonomy_level("L3") == 3
        assert parse_autonomy_level("L4") == 4

    def test_parse_int_format(self):
        from thomas.core.autonomy import parse_autonomy_level

        assert parse_autonomy_level(1) == 1
        assert parse_autonomy_level(3) == 3

    def test_parse_name_format(self):
        from thomas.core.autonomy import parse_autonomy_level

        assert parse_autonomy_level("chat") == 1
        assert parse_autonomy_level("Agent") == 4

    def test_parse_clamps(self):
        from thomas.core.autonomy import parse_autonomy_level

        assert parse_autonomy_level(0) == 1
        assert parse_autonomy_level(99) == 4

    def test_roundtrip(self):
        from thomas.core.autonomy import autonomy_level_to_pref, parse_autonomy_level

        for i in range(1, 5):
            pref = autonomy_level_to_pref(i)
            assert parse_autonomy_level(pref) == i


# ---- Test 7: All modified files compile ----


class TestCompilation:
    MODIFIED_FILES = [
        "thomas/preferences/store.py",
        "thomas/server/routes/preferences_aiohttp.py",
        "thomas/server/routes/chat_aiohttp.py",
        "thomas/server/routes/gateway/p141_openai_chat_completions_stream.py",
        "thomas/agent/loop.py",
        "thomas/agent/loop_tool_exec.py",
        "thomas/cli/main.py",
        "thomas/memory/v2/db.py",
        "thomas/core/config.py",
        "thomas/memory/store.py",
        "thomas/core/persistence.py",
        "thomas/server/app.py",
        "thomas/tools/engineering.py",
        "thomas/agent/verification.py",
        "thomas/agent/context_compaction.py",
        "thomas/server/tool_extensions.py",
        "thomas/core/autonomy.py",
    ]

    @pytest.mark.parametrize("filepath", MODIFIED_FILES)
    def test_file_compiles(self, filepath):
        full = _PROJECT_ROOT / filepath
        assert full.exists(), f"File not found: {full}"
        py_compile.compile(str(full), doraise=True)
