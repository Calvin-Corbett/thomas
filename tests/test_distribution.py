"""Tests for Thomas distribution, auto-update, and release system."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestPackageManifest(unittest.TestCase):
    """Verify the package excludes personal data."""

    def _project_root(self):
        return Path(__file__).resolve().parent.parent

    def test_manifest_in_exists(self):
        path = self._project_root() / "MANIFEST.in"
        self.assertTrue(path.exists())

    def test_manifest_excludes_runtime(self):
        text = (self._project_root() / "MANIFEST.in").read_text()
        self.assertIn("prune runtime", text)

    def test_manifest_excludes_thomas_dir(self):
        text = (self._project_root() / "MANIFEST.in").read_text()
        self.assertIn("prune .thomas", text)

    def test_manifest_excludes_sqlite(self):
        text = (self._project_root() / "MANIFEST.in").read_text()
        self.assertIn("sqlite3", text)

    def test_pyproject_has_exclude(self):
        text = (self._project_root() / "pyproject.toml").read_text()
        self.assertIn("runtime", text)
        self.assertIn("exclude", text)

    def test_pyproject_name_is_thomas_ai(self):
        """Package name on PyPI should be thomas-ai."""
        text = (self._project_root() / "pyproject.toml").read_text()
        self.assertIn('name = "thomas-ai"', text)


class TestVersionParsing(unittest.TestCase):
    """Test version comparison logic."""

    def test_parse_version(self):
        from thomas.cli.commands.updater import _parse_version

        self.assertEqual(_parse_version("0.11.78"), (0, 11, 78))
        self.assertEqual(_parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(_parse_version("2.3.4"), (2, 3, 4))

    def test_is_newer(self):
        from thomas.cli.commands.updater import _is_newer

        self.assertTrue(_is_newer("0.12.0", "0.11.78"))
        self.assertTrue(_is_newer("1.0.0", "0.99.99"))
        self.assertFalse(_is_newer("0.11.78", "0.11.78"))
        self.assertFalse(_is_newer("0.11.77", "0.11.78"))

    def test_get_current_version(self):
        from thomas.cli.commands.updater import _get_current_version

        version = _get_current_version()
        self.assertRegex(version, r"\d+\.\d+\.\d+")


class TestDevDetection(unittest.TestCase):
    """Test editable/dev install detection."""

    def test_is_dev_install_returns_bool(self):
        from thomas.cli.commands.updater import _is_dev_install

        result = _is_dev_install()
        self.assertIsInstance(result, bool)


class TestUpdateState(unittest.TestCase):
    """Test update state persistence."""

    def test_state_file_path(self):
        from thomas.cli.commands.updater import _state_file

        path = _state_file()
        self.assertTrue(str(path).endswith("state.json"))

    def test_save_and_load_state(self):
        from thomas.cli.commands.updater import _load_state, _save_state

        test_state = {"test_key": "test_value", "last_check_ts": 12345}
        _save_state(test_state)
        loaded = _load_state()
        self.assertEqual(loaded["test_key"], "test_value")

    def test_should_check_rate_limiting(self):
        import time

        from thomas.cli.commands.updater import _save_state, _should_check

        # Just checked — should not check again
        _save_state({"last_check_ts": time.time()})
        self.assertFalse(_should_check())

        # Long ago — should check
        _save_state({"last_check_ts": 0})
        self.assertTrue(_should_check())


class TestAutoUpdateSkips(unittest.TestCase):
    """Test that startup update checks correctly skip in dev/disabled scenarios."""

    def test_skips_dev_install(self):
        from thomas.cli.commands.updater import check_and_auto_update

        with patch("thomas.cli.commands.updater._is_dev_install", return_value=True):
            result = check_and_auto_update(silent=True)
            self.assertIsNone(result)

    def test_skips_when_env_disabled(self):
        from thomas.cli.commands.updater import check_and_auto_update

        with (
            patch.dict(os.environ, {"THOMAS_NO_AUTO_UPDATE": "1"}),
            patch("thomas.cli.commands.updater._is_dev_install", return_value=False),
        ):
            result = check_and_auto_update(silent=True)
            self.assertIsNone(result)

    def test_startup_check_records_available_update_without_applying(self):
        from thomas.cli.commands.updater import _load_state, check_and_auto_update

        with (
            patch("thomas.cli.commands.updater._is_dev_install", return_value=False),
            patch("thomas.cli.commands.updater._should_check", return_value=True),
            patch(
                "thomas.cli.commands.updater._fetch_latest_release",
                return_value={"version": "9.9.9", "published_at": "2026-04-01T12:00:00Z"},
            ),
            patch("thomas.cli.commands.updater._get_current_version", return_value="9.9.8"),
            patch("thomas.cli.commands.updater._run_pip_upgrade") as run_upgrade,
        ):
            result = check_and_auto_update(silent=True)

        self.assertIn("9.9.8 -> 9.9.9", str(result))
        run_upgrade.assert_not_called()
        state = _load_state()
        self.assertEqual(state.get("last_check_version"), "9.9.9")
        self.assertEqual(state.get("latest_release_published_at"), "2026-04-01T12:00:00Z")
        self.assertEqual(state.get("update_available"), True)


class TestFetchLatestVersion(unittest.TestCase):
    """Test PyPI version fetching."""

    def test_returns_none_on_failure(self):
        from thomas.cli.commands.updater import _fetch_latest_release

        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            result = _fetch_latest_release(timeout=1.0)
            self.assertIsNone(result)


class TestReleaseBump(unittest.TestCase):
    """Test version bumping logic."""

    def test_bump_patch(self):
        from thomas.cli.commands.release import _bump

        self.assertEqual(_bump("0.11.78", "patch"), "0.11.79")

    def test_bump_minor(self):
        from thomas.cli.commands.release import _bump

        self.assertEqual(_bump("0.11.78", "minor"), "0.12.0")

    def test_bump_major(self):
        from thomas.cli.commands.release import _bump

        self.assertEqual(_bump("0.11.78", "major"), "1.0.0")

    def test_parse_version(self):
        from thomas.cli.commands.release import _parse_version

        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))

    def test_parse_invalid_raises(self):
        from thomas.cli.commands.release import _parse_version

        with self.assertRaises(ValueError):
            _parse_version("not.a.version")


class TestWriteVersion(unittest.TestCase):
    """Test version file writing."""

    def test_write_version_updates_pyproject(self):
        from thomas.cli.commands.release import _write_version

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text('version = "0.1.0"\n')
            (root / "thomas").mkdir()
            (root / "thomas" / "__init__.py").write_text('__version__ = "0.1.0"\n')

            updated = _write_version(root, "0.2.0")
            self.assertEqual(len(updated), 2)

            pyproject = (root / "pyproject.toml").read_text()
            self.assertIn('"0.2.0"', pyproject)

            init = (root / "thomas" / "__init__.py").read_text()
            self.assertIn('"0.2.0"', init)


class TestCommandRegistration(unittest.TestCase):
    """Test that update/version/release commands register."""

    def test_register_update_commands(self):
        from thomas.cli.commands.updater import register_update_commands

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        group = click.Group("test")
        register_update_commands(group)
        self.assertIn("update", group.commands)
        self.assertIn("version", group.commands)

    def test_register_release_commands(self):
        from thomas.cli.commands.release import register_release_commands

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        group = click.Group("test")
        register_release_commands(group)
        self.assertIn("release", group.commands)


class TestGithubWorkflow(unittest.TestCase):
    """Verify the publish workflow exists and is valid."""

    def _project_root(self):
        return Path(__file__).resolve().parent.parent

    def test_publish_workflow_exists(self):
        path = self._project_root() / ".github" / "workflows" / "publish.yml"
        self.assertTrue(path.exists())

    def test_workflow_triggers_on_tags(self):
        text = (self._project_root() / ".github" / "workflows" / "publish.yml").read_text()
        self.assertIn("tags:", text)
        self.assertIn("'v*'", text)

    def test_workflow_uses_trusted_publishing(self):
        text = (self._project_root() / ".github" / "workflows" / "publish.yml").read_text()
        self.assertIn("id-token: write", text)

    def test_workflow_checks_for_data_leaks(self):
        text = (self._project_root() / ".github" / "workflows" / "publish.yml").read_text()
        self.assertIn("runtime/", text)
        self.assertIn("sqlite3", text)


class TestExplicitUpdatePolicy(unittest.TestCase):
    def test_update_apply_is_blocked_in_locked_profile(self):
        from click.testing import CliRunner

        from thomas.cli.commands.updater import register_update_commands
        from thomas.core.config import AppConfig, ModelConfig, SecurityConfig

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        runner = CliRunner()
        root = click.Group("root")
        register_update_commands(root)
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            security=SecurityConfig(profile="locked"),
        )
        with (
            patch("thomas.cli.commands.updater._get_current_version", return_value="1.0.0"),
            patch(
                "thomas.cli.commands.updater._fetch_latest_release",
                return_value={"version": "1.0.1", "published_at": "2026-04-02T00:00:00Z"},
            ),
            patch("thomas.cli.commands.updater._is_dev_install", return_value=False),
            patch("thomas.cli.commands.updater._run_pip_upgrade") as run_upgrade,
        ):
            result = runner.invoke(root, ["update", "apply"], obj={"config": cfg})

        self.assertEqual(result.exit_code, 0)
        self.assertIn("blocked by security profile", result.output)
        run_upgrade.assert_not_called()

    def test_update_apply_fail_closed_when_config_cannot_load(self):
        from click.testing import CliRunner

        from thomas.cli.commands.updater import register_update_commands

        try:
            import click
        except ImportError:
            from thomas._vendor import click_shim as click
        runner = CliRunner()
        root = click.Group("root")
        register_update_commands(root)
        with (
            patch("thomas.cli.commands.updater._load_runtime_config", return_value=None),
            patch("thomas.cli.commands.updater._get_current_version", return_value="1.0.0"),
            patch(
                "thomas.cli.commands.updater._fetch_latest_release",
                return_value={"version": "1.0.1", "published_at": "2026-04-02T00:00:00Z"},
            ),
            patch("thomas.cli.commands.updater._is_dev_install", return_value=False),
            patch("thomas.cli.commands.updater._run_pip_upgrade") as run_upgrade,
        ):
            result = runner.invoke(root, ["update", "apply"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("blocked by security profile", result.output)
        self.assertIn("config could not be loaded", result.output.lower())
        run_upgrade.assert_not_called()


if __name__ == "__main__":
    unittest.main()
