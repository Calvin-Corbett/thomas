import os
import unittest
from pathlib import Path

from thomas.core.config import load_config


class TestEnvOverride(unittest.TestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_models_leaf_with_underscore(self) -> None:
        os.environ["THOMAS_MODELS_LOCAL_BASE_URL"] = "http://example.com/v1"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.models["local"].base_url, "http://example.com/v1")

    def test_models_int_coercion(self) -> None:
        os.environ["THOMAS_MODELS_LOCAL_MAX_TOKENS"] = "123"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.models["local"].max_tokens, 123)

    def test_top_level_override(self) -> None:
        os.environ["THOMAS_DEFAULT_MODEL"] = "openai"
        os.environ["THOMAS_MAX_AGENT_ITERATIONS"] = "7"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.default_model, "openai")
        self.assertEqual(cfg.max_agent_iterations, 7)

    def test_section_override(self) -> None:
        os.environ["THOMAS_TOOLS_ALLOW_SHELL"] = "false"
        os.environ["THOMAS_MEMORY_ROOT"] = "./tmp_runtime"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.tools.allow_shell, False)
        self.assertEqual(cfg.memory.root, "./tmp_runtime")

    def test_failover_section_override(self) -> None:
        os.environ["THOMAS_FAILOVER_ENABLED"] = "true"
        os.environ["THOMAS_FAILOVER_PROFILES"] = "openai,anthropic"
        os.environ["THOMAS_FAILOVER_COOLDOWN_SECONDS"] = "45"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.failover.enabled, True)
        self.assertEqual(cfg.failover.profiles, ["openai", "anthropic"])
        self.assertEqual(cfg.failover.cooldown_seconds, 45)
