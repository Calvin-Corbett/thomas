"""Guardrails policy state + Vault registry (Step 4)."""

from __future__ import annotations

import unittest

from thomas.core import vault_registry as vault
from thomas.server import guardrails_state as gs


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
