from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from thomas.desktop_operator.host_service import DesktopHostCapabilityService


def test_host_service_request_opt_in_stages_install_assets(tmp_path: Path) -> None:
    service = DesktopHostCapabilityService(root_dir=tmp_path)
    posture = service.request_opt_in(hidden_by_default=True)
    payload = posture.to_dict()
    assert payload["enabled"] is True
    assert payload["installation_state"] == "host_service_not_installed"
    assert Path(payload["install_script_path"]).exists()
    assert Path(payload["uninstall_script_path"]).exists()
    assert Path(payload["state_path"]).exists()


def test_host_service_trust_mode_persists(tmp_path: Path) -> None:
    service = DesktopHostCapabilityService(root_dir=tmp_path)
    service.request_opt_in(hidden_by_default=True)
    posture = service.set_remote_trust_mode("remembered")
    assert posture.trust_mode == "remembered"
    stored = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert stored["trust_mode"] == "remembered"


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "ok", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_host_service_launch_install_updates_state(tmp_path: Path) -> None:
    called: list[list[str]] = []

    def _run(cmd, **kwargs):
        called.append(list(cmd))
        return _Completed(returncode=0, stdout="launched")

    service = DesktopHostCapabilityService(root_dir=tmp_path, run_command=_run)
    service.request_opt_in(hidden_by_default=True)
    launch = service.launch_host_service_install()
    assert launch["ok"] is True
    assert launch["launched"] is True
    assert called
    posture = launch["posture"]
    assert posture["installation_state"] == "host_service_installing"


def test_host_service_install_script_uses_pywin32_wrapper(tmp_path: Path) -> None:
    service = DesktopHostCapabilityService(root_dir=tmp_path)
    posture = service.request_opt_in(hidden_by_default=True)
    install_script = Path(posture.install_script_path).read_text(encoding="utf-8")
    uninstall_script = Path(posture.uninstall_script_path).read_text(encoding="utf-8")
    assert "install', '--startup', 'auto" in install_script
    assert "@('start')" in install_script
    assert "sc.exe create" not in install_script
    assert "@('remove')" in uninstall_script


def test_host_service_launch_viewer_uses_launch_process(tmp_path: Path) -> None:
    launched: list[list[str]] = []

    def _popen(cmd, **kwargs):
        launched.append(list(cmd))

        class _Dummy:
            pass

        return _Dummy()

    service = DesktopHostCapabilityService(root_dir=tmp_path, launch_process=_popen)
    service.request_opt_in(hidden_by_default=True)
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["viewer"] = {
        "available": True,
        "mode": "hyperv_console",
        "label": "Hyper-V console",
        "url": "",
        "command": 'vmconnect.exe localhost "ThomasDesktopVm"',
        "takeover_supported": True,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = service.launch_viewer()
    assert result["ok"] is True
    assert result["launched"] is True
    assert launched


def test_host_service_runner_forwards_service_extra_args(monkeypatch) -> None:
    from thomas.desktop_operator import host_service_runner as runner

    called: dict[str, object] = {}

    class _FakeServiceUtil:
        @staticmethod
        def HandleCommandLine(service_cls, argv=None):
            called["service_cls"] = service_cls
            called["argv"] = list(argv or [])

    monkeypatch.setattr(runner, "win32serviceutil", _FakeServiceUtil)
    monkeypatch.setattr(runner, "_build_service_class", lambda **kwargs: object())

    exit_code = runner.main(["--service-name", "ThomasDesktopHostService", "install", "--startup", "auto"])

    assert exit_code == 0
    assert called["argv"] == ["ThomasDesktopHostService", "--startup", "auto", "install"]


def test_host_service_runner_status_json_supports_script_entrypoint(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runner_path = repo_root / "thomas" / "desktop_operator" / "host_service_runner.py"

    completed = subprocess.run(
        [sys.executable, str(runner_path), "--status-json", "--root-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["service_name"] == "ThomasDesktopHostService"


def test_host_service_configure_local_vm_source_persists(tmp_path: Path) -> None:
    service = DesktopHostCapabilityService(root_dir=tmp_path)
    service.request_opt_in(hidden_by_default=True)
    posture = service.configure_local_vm_source(
        source_type="template_disk",
        vm_name="ThomasWorker",
        template_vhdx=r"C:\VMs\ThomasWorkerTemplate.vhdx",
        switch_name="Default Switch",
    )
    assert posture.local_vm["source_type"] == "template_disk"
    assert posture.local_vm["vm_name"] == "ThomasWorker"
    assert posture.local_vm["template_vhdx"] == r"C:\VMs\ThomasWorkerTemplate.vhdx"
    stored = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert stored["local_vm"]["switch_name"] == "Default Switch"
