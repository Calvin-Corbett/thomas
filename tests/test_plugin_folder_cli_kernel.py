"""Exercise the advertised folder install through the CLI and live kernel routes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from click.testing import CliRunner

from thomas.agent.kernel_wiring import default_kernel
from thomas.cli.main import cli
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner, resolve_plugins_install_root
from thomas.server.plugin_startup import APP_PLUGIN_SUPERVISOR
from thomas.server.plugin_supervisor import start_plugin_supervisor
from thomas.server.routes.plugin_kernel_routes import register_plugin_kernel_routes


class PluginFolderCliKernelTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        self.source = self.home / "source"
        self.source.mkdir()
        (self.source / "plugin.json").write_text(json.dumps({"name": "folder_demo"}), encoding="utf-8")
        (self.source / "__init__.py").write_text(
            'class Plugin:\n    name = "folder_demo"\n'
            "    def before_tool(self, payload):\n        return payload\n\n"
            "def get_plugin():\n    return Plugin()\n",
            encoding="utf-8",
        )
        self.data = self.home / "data"
        self.data.mkdir()
        env = patch.dict(
            os.environ,
            {
                "THOMAS_HOME": str(self.data),
                "THOMAS_PLUGINS_DIR": "",
                "THOMAS_PLUGIN_ENABLEMENT_STORE": str(self.home / "enablement.json"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.root = self.data / "plugins"
        self.kernel = default_kernel()
        self.supervisor = start_plugin_supervisor(kernel=self.kernel)
        self.addCleanup(self.supervisor.dispose)
        app = web.Application()
        app[APP_PLUGIN_SUPERVISOR] = self.supervisor
        register_plugin_kernel_routes(
            app,
            require_api_access=lambda _request: None,
            require_loopback=lambda _request: None,
            read_json=lambda request: request.json(),
        )
        return app

    async def test_cli_installs_where_live_supervisor_syncs_and_swaps(self) -> None:
        assert self.supervisor.mounted_names() == []
        help_result = CliRunner().invoke(cli, ["plugins", "install-from-local-path", "--help"])
        assert help_result.exit_code == 0
        assert "SOURCE_PATH" in help_result.output
        assert "--overwrite" in help_result.output
        assert "--name" in help_result.output
        assert "--run / --describe" not in help_result.output

        if os.name == "nt":
            repo = Path(__file__).resolve().parents[1]
            # Run the actual launcher from a temporary checkout-shaped folder.
            # Never create a .venv in the source tree or rely on python on PATH.
            launcher_home = self.home / "launcher"
            launcher_home.mkdir()
            launcher = launcher_home / "thomas.cmd"
            shutil.copyfile(repo / "thomas.cmd", launcher)
            venv.create(launcher_home / ".venv", system_site_packages=True)
            launcher_python = launcher_home / ".venv" / "Scripts" / "python.exe"
            assert launcher_python.is_file()
            windows_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            windows_only_path = os.pathsep.join([str(windows_root / "System32"), str(windows_root)])
            launcher_env = {**os.environ, "PATH": windows_only_path}
            cli_help = subprocess.run(
                ["cmd", "/d", "/c", str(launcher), "plugins", "install-from-local-path", "--help"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env=launcher_env,
            )
            assert cli_help.returncode == 0, cli_help.stderr
            assert "SOURCE_PATH" in cli_help.stdout
            missing = subprocess.run(
                ["cmd", "/d", "/c", str(launcher), "plugins", "install-from-local-path", str(self.home / "missing")],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env=launcher_env,
            )
            assert missing.returncode != 0
            assert "invalid_path" in missing.stderr

        if os.name == "nt":
            result = subprocess.run(
                [
                    "cmd",
                    "/d",
                    "/c",
                    str(launcher),
                    "--data-dir",
                    str(self.data),
                    "plugins",
                    "install-from-local-path",
                    str(self.source),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env={**launcher_env, "THOMAS_HOME": str(self.home / "other-data"), "THOMAS_PLUGINS_DIR": ""},
            )
            output = result.stdout + result.stderr
            exit_code = result.returncode
        else:
            with patch.dict(os.environ, {"THOMAS_HOME": str(self.home / "other-data")}):
                result = CliRunner().invoke(
                    cli, ["--data-dir", str(self.data), "plugins", "install-from-local-path", str(self.source)]
                )
                assert Path(os.environ["THOMAS_HOME"]).resolve() == self.data.resolve()
                assert Path(resolve_plugins_install_root()).resolve() == self.root.resolve()
            output = result.output
            exit_code = result.exit_code
        assert exit_code == 0, output
        assert "Installed plugin 'folder_demo'" in output
        assert Path(self.supervisor.install_root).resolve() == self.root.resolve()
        assert (self.root / "folder_demo" / "__init__.py").is_file()
        assert "folder_demo" in json.loads((self.root / "installed_plugins.json").read_text())["plugins"]

        sync = await self.client.post("/api/plugins/kernel/sync", json={})
        assert sync.status == 200
        assert (await sync.json())["changes"]["mounted"] == ["folder_demo"]
        runner = make_plugin_hook_runner(install_root=str(self.root), kernel=self.kernel)
        assert (await runner("before_tool", {"value": 1}))["value"] == 1
        status = await (await self.client.get("/api/plugins/kernel")).json()
        assert status["runtime"]["mounted"] == ["folder_demo"]
        assert "before_tool" in status["runtime"]["plugins"][0]["hooks"]

        unplugged = await (await self.client.post("/api/plugins/kernel/unplug", json={"name": "folder_demo"})).json()
        assert unplugged["ok"] and unplugged["mounted"] == []
        replugged = await (await self.client.post("/api/plugins/kernel/replug", json={"name": "folder_demo"})).json()
        assert replugged["ok"] and replugged["mounted"] == ["folder_demo"]
        reloaded = await (
            await self.client.post("/api/plugins/kernel/reload", json={"name": "folder_demo", "force": True})
        ).json()
        assert reloaded["ok"] and reloaded["outcome"] == "reloaded"
        assert (await runner("before_tool", {"value": 2}))["value"] == 2

    async def test_bad_folder_does_not_report_success(self) -> None:
        result = CliRunner().invoke(
            cli, ["--data-dir", str(self.data), "plugins", "install-from-local-path", str(self.home / "missing")]
        )
        assert result.exit_code != 0
        stub = CliRunner().invoke(cli, ["plugins", "install-from-local-path", "--run"])
        assert stub.exit_code != 0
        assert not (self.root / "installed_plugins.json").exists()
