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
        os.environ["THOMAS_FAILOVER_CHAT_AUTO_FAILOVER"] = "true"
        os.environ["THOMAS_FAILOVER_PROFILES"] = "openai,anthropic"
        os.environ["THOMAS_FAILOVER_COOLDOWN_SECONDS"] = "45"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.failover.enabled, True)
        self.assertEqual(cfg.failover.chat_auto_failover, True)
        self.assertEqual(cfg.failover.profiles, ["openai", "anthropic"])
        self.assertEqual(cfg.failover.cooldown_seconds, 45)

    def test_server_section_override(self) -> None:
        os.environ["THOMAS_SERVER_ACCESS_MODE"] = "remote"
        os.environ["THOMAS_SERVER_API_TOKEN"] = "secret-token"
        os.environ["THOMAS_SERVER_ALLOW_UNAUTHENTICATED_VERSION"] = "false"
        os.environ["THOMAS_SERVER_RATE_LIMIT_ENABLED"] = "false"
        os.environ["THOMAS_SERVER_RATE_LIMIT_MAX_REQUESTS"] = "55"
        os.environ["THOMAS_SERVER_RATE_LIMIT_WINDOW_SECONDS"] = "22"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.server.access_mode, "remote")
        self.assertEqual(cfg.server.api_token, "secret-token")
        self.assertEqual(cfg.server.allow_unauthenticated_version, False)
        self.assertEqual(cfg.server.rate_limit_enabled, False)
        self.assertEqual(cfg.server.rate_limit_max_requests, 55)
        self.assertEqual(cfg.server.rate_limit_window_seconds, 22)

    def test_remote_mode_requires_api_token(self) -> None:
        os.environ["THOMAS_SERVER_ACCESS_MODE"] = "remote"
        cfg = load_config(Path("__does_not_exist__.toml"))
        errs = cfg.validate()
        self.assertTrue(any("server.api_token is required" in e for e in errs))

    def test_server_rate_limit_validation(self) -> None:
        os.environ["THOMAS_SERVER_RATE_LIMIT_MAX_REQUESTS"] = "0"
        os.environ["THOMAS_SERVER_RATE_LIMIT_WINDOW_SECONDS"] = "0"
        cfg = load_config(Path("__does_not_exist__.toml"))
        errs = cfg.validate()
        self.assertTrue(any("server.rate_limit_max_requests must be >= 1" in e for e in errs))
        self.assertTrue(any("server.rate_limit_window_seconds must be >= 1" in e for e in errs))

    def test_quality_section_override(self) -> None:
        os.environ["THOMAS_QUALITY_ENABLED"] = "true"
        os.environ["THOMAS_QUALITY_ENFORCE"] = "true"
        os.environ["THOMAS_QUALITY_MAX_AUTO_RETRIES"] = "2"
        os.environ["THOMAS_QUALITY_REQUIRE_VERIFICATION_FOR_CODING"] = "false"
        os.environ["THOMAS_QUALITY_REQUIRE_TESTS_FOR_CODE_EDITS"] = "true"
        os.environ["THOMAS_QUALITY_REQUIRE_MONOLITH_GUARD_FOR_CODING"] = "false"
        cfg = load_config(Path("__does_not_exist__.toml"))
        self.assertEqual(cfg.quality.enabled, True)
        self.assertEqual(cfg.quality.enforce, True)
        self.assertEqual(cfg.quality.max_auto_retries, 2)
        self.assertEqual(cfg.quality.require_verification_for_coding, False)
        self.assertEqual(cfg.quality.require_tests_for_code_edits, True)
        self.assertEqual(cfg.quality.require_monolith_guard_for_coding, False)

    def test_unknown_core_keys_are_reported(self) -> None:
        cfg_path = Path("__tmp_bad_core_key__.toml")
        try:
            cfg_path.write_text(
                "\n".join(
                    [
                        'default_model = "local"',
                        "",
                        "[models.local]",
                        'model = "dummy"',
                        "",
                        "[server]",
                        'access_mode = "local"',
                        "rat_limit_enabled = true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cfg = load_config(cfg_path)
            errs = cfg.validate()
            self.assertTrue(any("Unknown core config key 'server.rat_limit_enabled'" in e for e in errs))
        finally:
            if cfg_path.exists():
                cfg_path.unlink()

    def test_quality_retry_cap_validation(self) -> None:
        os.environ["THOMAS_QUALITY_MAX_AUTO_RETRIES"] = "9"
        cfg = load_config(Path("__does_not_exist__.toml"))
        errs = cfg.validate()
        self.assertTrue(any("quality.max_auto_retries must be <= 3" in e for e in errs))
