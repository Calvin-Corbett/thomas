"""Tests for the Thomas setup wizard, quickstart, and shortcuts system."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_cli_with_cp1252(cwd: Path, *args: str, user_input: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    repo_root = str(_project_root())
    env["PYTHONPATH"] = repo_root if not existing_pythonpath else repo_root + os.pathsep + existing_pythonpath
    return subprocess.run(
        [sys.executable, "-m", "thomas", *args],
        cwd=str(cwd),
        input=user_input,
        capture_output=True,
        text=True,
        env=env,
    )


class TestSetupWizardProviders(unittest.TestCase):
    """Test provider definitions and model recommendations."""

    def test_providers_list(self):
        from thomas.cli.commands.setup_wizard import PROVIDERS

        self.assertGreaterEqual(len(PROVIDERS), 5)
        ids = [p["id"] for p in PROVIDERS]
        self.assertIn("ollama", ids)
        self.assertIn("openai", ids)
        self.assertIn("anthropic", ids)

    def test_each_provider_has_required_fields(self):
        from thomas.cli.commands.setup_wizard import PROVIDERS

        for p in PROVIDERS:
            self.assertIn("id", p)
            self.assertIn("name", p)
            self.assertIn("desc", p)
            self.assertIn("base_url", p)
            self.assertIn("key_required", p)

    def test_model_recommendations(self):
        from thomas.cli.commands.setup_wizard import MODEL_RECOMMENDATIONS

        self.assertIn("openai", MODEL_RECOMMENDATIONS)
        self.assertIn("anthropic", MODEL_RECOMMENDATIONS)
        for provider, models in MODEL_RECOMMENDATIONS.items():
            for model, desc in models:
                self.assertTrue(len(model) > 0)
                self.assertTrue(len(desc) > 0)


class TestConfigGeneration(unittest.TestCase):
    """Test config file generation."""

    def test_generate_openai_config(self):
        from thomas.cli.commands.setup_wizard import _generate_config

        config = _generate_config("openai", "https://api.openai.com/v1", "sk-test123", "gpt-4o", "balanced")
        self.assertIn("[models.default]", config)
        self.assertIn('provider = "openai_compat"', config)
        self.assertIn('model = "gpt-4o"', config)
        self.assertIn('api_key = "sk-test123"', config)

    def test_generate_anthropic_config(self):
        from thomas.cli.commands.setup_wizard import _generate_config

        config = _generate_config(
            "anthropic", "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514", "casual"
        )
        self.assertIn('provider = "anthropic"', config)
        self.assertIn('style = "casual"', config)

    def test_generate_local_config_no_key(self):
        from thomas.cli.commands.setup_wizard import _generate_config

        config = _generate_config("ollama", "http://localhost:11434/v1", "", "llama3.2", "balanced")
        self.assertIn("# api_key", config)
        # The key line should be commented out, not an active setting
        for line in config.splitlines():
            stripped = line.strip()
            if stripped.startswith("api_key") and not stripped.startswith("#"):
                self.fail("Found uncommented api_key line for local model")

    def test_generate_google_config(self):
        from thomas.cli.commands.setup_wizard import _generate_config

        config = _generate_config(
            "google", "https://generativelanguage.googleapis.com/v1beta", "key123", "gemini-2.0-flash", "professional"
        )
        self.assertIn('provider = "google"', config)

    def test_config_has_memory_section(self):
        from thomas.cli.commands.setup_wizard import _generate_config

        config = _generate_config("openai", "https://api.openai.com/v1", "k", "m", "balanced")
        self.assertIn("[memory]", config)
        self.assertIn("[tools]", config)
        self.assertIn("[personality]", config)


class TestDetectExistingConfig(unittest.TestCase):
    """Test config detection."""

    def test_detect_no_config(self):
        from thomas.cli.commands.setup_wizard import _detect_existing_config

        with patch.object(Path, "exists", return_value=False):
            result = _detect_existing_config()
            # May or may not find config depending on environment
            # Just verify it returns Path or None
            self.assertTrue(result is None or isinstance(result, Path))


class TestOllamaDetection(unittest.TestCase):
    """Test Ollama detection."""

    def test_detect_ollama_not_running(self):
        from thomas.cli.commands.setup_wizard import _detect_ollama

        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            self.assertFalse(_detect_ollama())


class TestQuickstartDetection(unittest.TestCase):
    """Test quickstart Ollama model detection."""

    def test_detect_models_not_running(self):
        from thomas.cli.commands.quickstart import _detect_ollama_models

        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            result = _detect_ollama_models()
            self.assertEqual(result, [])

    def test_write_minimal_config(self):
        import tempfile

        from thomas.cli.commands.quickstart import _write_minimal_config

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                path = _write_minimal_config("https://api.openai.com/v1", "sk-test", "gpt-4o", "openai")
                self.assertTrue(path.exists())
                content = path.read_text(encoding="utf-8")
                self.assertIn("[models.default]", content)
                self.assertIn("gpt-4o", content)
            finally:
                os.chdir(old_cwd)

    def test_quickstart_subprocess_survives_cp1252_console(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "thomas.toml").write_text("# existing\n", encoding="utf-8")
            result = _run_cli_with_cp1252(cwd, "quickstart")
            output = (result.stdout or "") + (result.stderr or "")
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("Thomas Quick Start", output)
            self.assertIn("Config already exists", output)
            self.assertNotIn("Traceback", output)

    def test_setup_subprocess_survives_cp1252_console(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            (cwd / "thomas.toml").write_text("# existing\n", encoding="utf-8")
            result = _run_cli_with_cp1252(cwd, "setup", user_input="n\n")
            output = (result.stdout or "") + (result.stderr or "")
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("Thomas Setup Wizard", output)
            self.assertIn("Found existing config", output)
            self.assertIn("Keeping existing config. Done!", output)
            self.assertNotIn("Traceback", output)


class TestShortcutsPlatform(unittest.TestCase):
    """Test shortcut path generation per platform."""

    def test_get_platform(self):
        from thomas.cli.commands.shortcuts import _get_platform

        platform = _get_platform()
        self.assertIn(platform, ["linux", "macos", "windows"])

    def test_get_python_path(self):
        from thomas.cli.commands.shortcuts import _get_python_path

        path = _get_python_path()
        self.assertTrue(len(path) > 0)

    def test_install_shortcuts_returns_list(self):
        from thomas.cli.commands.shortcuts import install_shortcuts

        # On CI / test environments, shortcuts may or may not be created
        result = install_shortcuts("repl")
        self.assertIsInstance(result, list)

    def test_remove_shortcuts_returns_list(self):
        from thomas.cli.commands.shortcuts import remove_shortcuts

        result = remove_shortcuts()
        self.assertIsInstance(result, list)


class TestConnectionTest(unittest.TestCase):
    """Test the connection test function."""

    def test_connection_failure(self):
        from thomas.cli.commands.setup_wizard import _test_connection

        ok, msg = _test_connection("http://localhost:99999", "", "fake-model")
        self.assertFalse(ok)
        self.assertTrue(len(msg) > 0)


class TestCommandRegistration(unittest.TestCase):
    """Test that commands register without errors."""

    def test_register_setup_commands(self):
        from thomas.cli.commands.setup_wizard import register_setup_commands

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        group = click.Group("test")
        register_setup_commands(group)
        # Verify the command was registered
        self.assertIn("setup", group.commands)

    def test_register_quickstart_commands(self):
        from thomas.cli.commands.quickstart import register_quickstart_commands

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        group = click.Group("test")
        register_quickstart_commands(group)
        self.assertIn("quickstart", group.commands)

    def test_register_shortcuts_commands(self):
        from thomas.cli.commands.shortcuts import register_shortcuts_commands

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        group = click.Group("test")
        register_shortcuts_commands(group)
        # shortcuts is a group, check it exists
        self.assertIn("shortcuts", group.commands)


class TestInstallerScriptsExist(unittest.TestCase):
    """Verify installer scripts are present."""

    def _project_root(self):
        """Find the Thomas project root."""
        return _project_root()

    def test_install_sh_exists(self):
        path = self._project_root() / "install.sh"
        self.assertTrue(path.exists(), f"install.sh not found at {path}")

    def test_install_cmd_exists(self):
        path = self._project_root() / "install.cmd"
        self.assertTrue(path.exists(), f"install.cmd not found at {path}")

    def test_install_sh_executable(self):
        import os

        path = self._project_root() / "install.sh"
        if path.exists():
            self.assertTrue(os.access(str(path), os.X_OK))

    def test_install_sh_has_shebang(self):
        path = self._project_root() / "install.sh"
        if path.exists():
            first_line = path.read_text().split("\n")[0]
            self.assertTrue(first_line.startswith("#!/"), f"Missing shebang: {first_line}")


if __name__ == "__main__":
    unittest.main()
