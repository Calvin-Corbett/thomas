from __future__ import annotations

import types
import zipfile

from thomas.desktop_operator.contracts import DesktopVmContext
from thomas.desktop_operator.manager import DesktopOperatorServiceManager
from thomas.desktop_operator.vm import HyperVDesktopVmSupervisor, create_vm_supervisor, resolve_vm_context


def test_resolve_vm_context_defaults_to_local_dedicated_vm(monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_DESKTOP_VM_ISOLATED", raising=False)
    monkeypatch.delenv("THOMAS_DESKTOP_VM_ID", raising=False)
    monkeypatch.delenv("THOMAS_DESKTOP_VM_PROVIDER", raising=False)
    monkeypatch.delenv("THOMAS_DESKTOP_VM_MODE", raising=False)

    vm = resolve_vm_context()

    assert vm.isolated is True
    assert vm.provider == "hyperv_local_vm"
    assert vm.isolation_mode == "dedicated_vm"
    assert vm.vm_id.endswith("-desktop-vm")
    assert vm.viewer_mode == "hyperv_console"
    assert vm.viewer_takeover_supported is True


def test_vm_supervisor_builds_bridge_and_ready_bootstrap(tmp_path) -> None:
    vm_context = DesktopVmContext(
        vm_id="vm-magic-01",
        provider="hyperv_local_vm",
        isolation_mode="dedicated_vm",
        isolated=True,
    )
    supervisor = create_vm_supervisor(
        vm_context,
        artifacts_dir=tmp_path,
        env={
            "THOMAS_DESKTOP_HELPER_BASE_URL": "http://127.0.0.1:8899",
            "THOMAS_DESKTOP_HELPER_TOKEN": "token-abc",
        },
    )

    bootstrap = supervisor.ensure_ready()

    assert bootstrap.helper_ready is True
    assert bootstrap.launch_mode == "remote_helper"
    assert bootstrap.helper_base_url == "http://127.0.0.1:8899"
    assert bootstrap.helper_token == "token-abc"
    assert bootstrap.bootstrap_manifest_path
    assert bootstrap.guest_launch_script_path.endswith("launch-helper.ps1")
    assert bootstrap.guest_register_task_script_path.endswith("register-helper-task.ps1")
    assert bootstrap.guest_bundle_zip_path.endswith("guest-helper-bundle.zip")
    assert bootstrap.startup_command.startswith("python -m thomas.desktop_operator.helper_main")
    assert bootstrap.viewer_mode == "hyperv_console"
    assert bootstrap.viewer_label == "Hyper-V console"
    assert "vmconnect.exe localhost" in bootstrap.viewer_command
    bundle_path = tmp_path / "vm_bridge" / "vm-magic-01" / "control" / "guest-helper-bundle.zip"
    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
    assert "thomas/desktop_operator/helper_main.py" in names
    assert "thomas/desktop_operator/runtime.py" in names
    assert (tmp_path / "vm_bridge" / "vm-magic-01" / "ingress").exists()
    assert (tmp_path / "vm_bridge" / "vm-magic-01" / "egress").exists()
    assert (tmp_path / "vm_bridge" / "vm-magic-01" / "control").exists()


def test_vm_supervisor_manage_invokes_hyperv(tmp_path) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    vm_context = DesktopVmContext(
        vm_id="vm-magic-02",
        provider="hyperv_local_vm",
        isolation_mode="dedicated_vm",
        isolated=True,
    )
    supervisor = HyperVDesktopVmSupervisor(
        vm_context=vm_context,
        artifacts_dir=tmp_path,
        env={
            "THOMAS_DESKTOP_VM_MANAGE": "1",
            "THOMAS_DESKTOP_VM_NAME": "ThomasWorker",
            "THOMAS_DESKTOP_VM_SNAPSHOT": "thomas-clean",
            "THOMAS_DESKTOP_VM_ADDRESS": "127.0.0.1",
            "THOMAS_DESKTOP_HELPER_PORT": "9900",
            "THOMAS_DESKTOP_HELPER_TOKEN": "token-xyz",
            "THOMAS_DESKTOP_VM_GUEST_USERNAME": "thomas",
            "THOMAS_DESKTOP_VM_GUEST_PASSWORD": "secret-pass",
        },
        run_command=fake_run,
    )

    bootstrap = supervisor.ensure_ready()

    assert bootstrap.managed is True
    assert bootstrap.helper_ready is True
    assert bootstrap.powershell_direct_available is True
    assert len(calls) == 3
    assert "Restore-VMSnapshot" in " ".join(calls[0][0])
    assert "Start-VM" in " ".join(calls[1][0])
    assert "Invoke-Command -VMName 'ThomasWorker'" in " ".join(calls[2][0])


def test_manager_prefers_remote_vm_bootstrap(monkeypatch, tmp_path) -> None:
    vm_context = DesktopVmContext(
        vm_id="vm-magic-03",
        provider="hyperv_local_vm",
        isolation_mode="dedicated_vm",
        isolated=True,
    )
    bootstrap = types.SimpleNamespace(
        helper_ready=True,
        helper_base_url="http://127.0.0.1:7777",
        helper_token="token-777",
        launch_mode="remote_helper",
        refusal_reason="",
        to_dict=lambda: {"vm_name": "vm-magic-03", "helper_ready": True},
    )

    class _FakeSupervisor:
        def ensure_ready(self):
            return bootstrap

    monkeypatch.setattr("thomas.desktop_operator.manager.resolve_vm_context", lambda: vm_context)
    monkeypatch.setattr(
        "thomas.desktop_operator.manager.create_vm_supervisor", lambda *args, **kwargs: _FakeSupervisor()
    )
    monkeypatch.setattr("thomas.desktop_operator.manager.DesktopOperatorClient.health", lambda self: {"ok": True})

    manager = DesktopOperatorServiceManager(artifacts_dir=tmp_path)
    manager.start()
    try:
        assert manager.connection_mode == "remote_vm"
        assert manager.base_url == "http://127.0.0.1:7777"
        assert manager.token == "token-777"
        assert manager.vm_bootstrap is bootstrap
    finally:
        manager.stop()
