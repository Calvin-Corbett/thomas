"""Guardrails policy state + Vault registry (Step 4)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from thomas.core import vault_registry as vault
from thomas.server import guardrails_state as gs
from thomas.tools import filesystem as fs

# The four control files that are the runtime-protection *bypass mechanism*.
# filesystem.py blocks writes to them; the Vault registry does not list them.
_BYPASS_CONTROL_FILES = (
    "runtime/.runtime_protection_disabled",
    "runtime/.runtime_protection_key",
    "runtime/.breakglass_window",
    "runtime/.breakglass_window_key",
)


def _filesystem_guard_blocks(rel_path: str) -> bool:
    """Ask filesystem.py's real guard about *rel_path*, in a clean temp sandbox.

    A temp root keeps the answer independent of whether this machine happens to
    have a runtime-protection disable flag or a breakglass window open.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        return fs._is_protected_runtime_path(root, root / rel_path) is not None


class TestVaultRegistry(unittest.TestCase):
    def test_top_level_protected_files_are_vault(self):
        self.assertTrue(vault.is_vault_protected("agent_safety.toml"))
        self.assertTrue(vault.is_vault_protected("pyproject.toml"))

    def test_engine_dirs_are_vault(self):
        self.assertTrue(vault.is_vault_protected("thomas/core/config.py"))
        self.assertTrue(vault.is_vault_protected("thomas/agent/loop.py"))
        self.assertTrue(vault.is_vault_protected("scripts/forge/ship.py"))

    def test_ordinary_paths_are_not_vault(self):
        self.assertFalse(vault.is_vault_protected("README.md"))
        self.assertFalse(vault.is_vault_protected("plans/thomas/notes.md"))
        self.assertFalse(vault.is_vault_protected(""))

    def test_windows_separators_normalize(self):
        self.assertTrue(vault.is_vault_protected("thomas\\core\\config.py"))

    def test_registry_is_nonempty(self):
        self.assertTrue(vault.vault_protected_files())
        self.assertTrue(vault.vault_protected_dirs())


class TestVaultIsNotTheEnforcementPath(unittest.TestCase):
    """The Vault registry describes the policy; filesystem.py enforces it.

    Measured 2026-07-31, on the module docstring's claim that "the rest of the
    system consults ``is_vault_protected`` instead of re-deriving the list":

      * Production modules importing ``thomas.core.vault_registry``: 0 of 5121
        tracked .py files.  (Control, same scanner: ``thomas.core.config`` has
        125 production importers, ``thomas.core.rules_of_road`` has 2 — so the
        scan can show a wired-up module; it showed zero for this one.)
      * Protected dirs:  vault 7, filesystem 7, identical.
      * Protected files: vault 7, filesystem 11 — filesystem protects 4 more.
        Behavioural probe over 7 paths: the two agreed on 3 and disagreed on 4,
        and all 4 disagreements are the bypass-control files below.

    So the docstring was false in both halves.  It now says the lists are
    deliberately separate; these tests hold that line, because "unifying" them
    would silently unprotect the four files that gate the bypass — the exact
    regression PR runtime-protection-fix-2026-05-27 closed.
    """

    def test_the_engine_dirs_are_the_same_in_both_lists(self):
        """Control: the halves that DO agree, so a disagreement below is real."""
        self.assertEqual(
            sorted(d.strip("/") for d in vault.vault_protected_dirs()),
            sorted(d.strip("/") for d in fs._HARDCODED_PROTECTED_DIRS),
        )
        for rel in ("thomas/core/config.py", "thomas/agent/loop.py", "scripts/forge/ship.py"):
            with self.subTest(rel=rel):
                self.assertTrue(vault.is_vault_protected(rel))
                self.assertTrue(_filesystem_guard_blocks(rel))

    def test_an_ordinary_file_is_free_in_both_lists(self):
        """Control: neither decider is simply answering True to everything."""
        for rel in ("README.md", "plans/thomas/notes.md"):
            with self.subTest(rel=rel):
                self.assertFalse(vault.is_vault_protected(rel))
                self.assertFalse(_filesystem_guard_blocks(rel))

    def test_the_bypass_control_files_are_guarded_only_by_the_filesystem_layer(self):
        """The measured difference: 4 files filesystem blocks and the Vault omits.

        If someone makes filesystem.py consult ``is_vault_protected``, these
        paths stop being blocked and this test goes red.  That is the point.
        """
        for rel in _BYPASS_CONTROL_FILES:
            with self.subTest(rel=rel):
                self.assertTrue(
                    _filesystem_guard_blocks(rel),
                    f"{rel} is the runtime-protection bypass mechanism and must stay blocked",
                )
                self.assertFalse(
                    vault.is_vault_protected(rel),
                    f"{rel} is now in the Vault registry — the module docstring says the two "
                    f"lists differ by exactly these 4 files; update it if that changed",
                )

    def test_a_corrupt_config_empties_the_vault_but_must_not_reach_enforcement(self):
        """Why the filesystem guard must not delegate: the Vault fails OPEN.

        Measured: with a corrupt ``agent_safety.toml``, ``vault_protected_dirs()``
        goes 7 -> 0 and ``is_vault_protected('thomas/core/config.py')`` goes
        True -> False.  The filesystem guard, being hardcoded, still blocks it.
        """
        self.assertTrue(vault.is_vault_protected("thomas/core/config.py"))
        self.assertEqual(len(vault.vault_protected_dirs()), 7)

        original_root = vault._REPO_ROOT
        with tempfile.TemporaryDirectory() as td:
            broken = Path(td)
            (broken / "agent_safety.toml").write_text("not valid toml {{{", encoding="utf-8")
            try:
                vault._REPO_ROOT = broken
                vault._load.cache_clear()
                self.assertEqual(vault.vault_protected_dirs(), ())
                self.assertFalse(vault.is_vault_protected("thomas/core/config.py"))

                # The whole reason the lists stay separate: enforcement must be
                # unaffected *while* the config is unreadable.  A filesystem
                # guard that delegated to this module would answer False here
                # and Thomas's entire runtime would become agent-writable.
                self.assertTrue(
                    _filesystem_guard_blocks("thomas/core/config.py"),
                    "filesystem.py stopped protecting thomas/core/ when agent_safety.toml "
                    "was corrupt — the hardcoded guard has been made config-dependent",
                )
            finally:
                vault._REPO_ROOT = original_root
                vault._load.cache_clear()

        self.assertTrue(vault.is_vault_protected("thomas/core/config.py"))


class TestGuardrailsState(unittest.TestCase):
    def test_default_is_all_standard(self):
        st = gs.GuardrailsState()
        for group in gs.GUARDRAIL_GROUPS:
            self.assertEqual(st.mode_for(group), "standard")
        self.assertEqual(st.spend_cap_tokens, 0)

    def test_presets(self):
        self.assertTrue(all(m == "strict" for m in gs.from_preset("fortress").modes.values()))
        self.assertTrue(all(m == "permissive" for m in gs.from_preset("open").modes.values()))
        # unknown preset -> standard
        self.assertTrue(all(m == "standard" for m in gs.from_preset("bogus").modes.values()))

    def test_normalize_rejects_bad_modes_and_caps(self):
        st = gs.normalize_state({"modes": {"sprawl_guard": "nonsense", "reach": "strict"}, "spend_cap_tokens": "-5"})
        self.assertEqual(st.mode_for("sprawl_guard"), "standard")
        self.assertEqual(st.mode_for("reach"), "strict")
        self.assertEqual(st.spend_cap_tokens, 0)

    def test_roundtrip_to_dict(self):
        st = gs.from_preset("fortress")
        st2 = gs.normalize_state(st.to_dict())
        self.assertEqual(st.modes, st2.modes)


if __name__ == "__main__":
    unittest.main()
