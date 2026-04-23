from __future__ import annotations

import threading
from pathlib import Path

import pytest

from thomas.desktop_operator.client import DesktopOperatorClient
from thomas.desktop_operator.contracts import CaptureArtifact, DesktopVmContext, Rect, WindowInfo
from thomas.desktop_operator.helper_service import DesktopOperatorHelperServer
from thomas.desktop_operator.runtime import DesktopOperatorRuntime


class FakeAdapter:
    def __init__(self) -> None:
        self.windows = {
            101: WindowInfo(
                handle=101,
                title="CapCut Desktop",
                executable_path=r"C:\Program Files\CapCut\CapCut.exe",
                process_id=4242,
                visible=True,
                minimized=False,
                monitor_id="DISPLAY1",
                bounds=Rect(100, 100, 900, 700),
                client_bounds=Rect(120, 140, 880, 660),
                class_name="FakeCapCutWindow",
            ),
            202: WindowInfo(
                handle=202,
                title="Open",
                executable_path=r"C:\Windows\System32\OpenFileDialog.exe",
                process_id=5252,
                visible=True,
                minimized=False,
                monitor_id="DISPLAY1",
                bounds=Rect(120, 120, 720, 520),
                client_bounds=Rect(140, 150, 700, 500),
                class_name="#32770",
            ),
            303: WindowInfo(
                handle=303,
                title="Example - Google Chrome",
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                process_id=6262,
                visible=True,
                minimized=False,
                monitor_id="DISPLAY2",
                bounds=Rect(50, 50, 1250, 850),
                client_bounds=Rect(70, 110, 1230, 830),
                class_name="Chrome_WidgetWin_1",
            ),
        }
        self.foreground = 303
        self.last_click = None
        self.last_type = None
        self.last_keys = None
        self.last_drag = None
        self.last_move_to_primary = False

    def list_windows(self) -> list[WindowInfo]:
        return list(self.windows.values())

    def get_window(self, handle: int) -> WindowInfo | None:
        return self.windows.get(int(handle))

    def capture_window(self, handle: int, output_path):
        output_path.write_bytes(b"fake-image")
        return CaptureArtifact(
            path=str(output_path), source="printwindow", timestamp_epoch_s=123.0, occlusion_safe=True
        )

    def snapshot_accessibility(self, handle: int):
        if int(handle) == 101:
            return {
                "available": True,
                "source": "uia",
                "nodes": [
                    {
                        "name": "New project",
                        "role": "Button",
                        "automation_id": "new-project",
                        "bounds": {"left": 220, "top": 200, "right": 320, "bottom": 240},
                    },
                    {
                        "name": "Import",
                        "role": "Button",
                        "automation_id": "import-button",
                        "bounds": {"left": 330, "top": 200, "right": 420, "bottom": 240},
                    },
                    {
                        "name": "Export",
                        "role": "Button",
                        "automation_id": "export-button",
                        "bounds": {"left": 430, "top": 200, "right": 520, "bottom": 240},
                    },
                    {
                        "name": "Timeline",
                        "role": "Pane",
                        "automation_id": "timeline",
                        "bounds": {"left": 160, "top": 560, "right": 840, "bottom": 640},
                    },
                ],
            }
        if int(handle) == 202:
            return {
                "available": True,
                "source": "uia",
                "nodes": [
                    {
                        "name": "File name:",
                        "role": "Edit",
                        "automation_id": "1148",
                        "bounds": {"left": 240, "top": 420, "right": 600, "bottom": 450},
                    },
                    {
                        "name": "Open",
                        "role": "Button",
                        "automation_id": "1",
                        "bounds": {"left": 610, "top": 420, "right": 680, "bottom": 450},
                    },
                    {
                        "name": "Cancel",
                        "role": "Button",
                        "automation_id": "2",
                        "bounds": {"left": 610, "top": 456, "right": 680, "bottom": 486},
                    },
                ],
            }
        return {
            "available": True,
            "source": "uia",
            "nodes": [
                {
                    "name": "Address and search bar",
                    "role": "Edit",
                    "automation_id": "address",
                    "bounds": {"left": 180, "top": 80, "right": 900, "bottom": 110},
                },
                {
                    "name": "Reload this page",
                    "role": "Button",
                    "automation_id": "reload",
                    "bounds": {"left": 120, "top": 80, "right": 160, "bottom": 110},
                },
                {
                    "name": "Page",
                    "role": "Document",
                    "automation_id": "page",
                    "bounds": {"left": 120, "top": 140, "right": 1180, "bottom": 800},
                },
            ],
        }

    def get_foreground_window(self) -> int | None:
        return self.foreground

    def ensure_visible(self, handle: int, *, move_to_primary: bool = False):
        self.last_move_to_primary = bool(move_to_primary)
        self.foreground = int(handle)
        return self.windows[int(handle)]

    def click(self, handle: int, x: int, y: int, *, button: str = "left", double: bool = False) -> None:
        self.last_click = {"handle": handle, "x": x, "y": y, "button": button, "double": double}

    def type_text(self, handle: int, text: str) -> None:
        self.last_type = {"handle": handle, "text": text}

    def press_keys(self, handle: int, keys) -> None:
        self.last_keys = {"handle": handle, "keys": list(keys)}

    def drag(self, handle: int, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self.last_drag = {"handle": handle, "start_x": start_x, "start_y": start_y, "end_x": end_x, "end_y": end_y}


def _isolated_vm() -> DesktopVmContext:
    return DesktopVmContext(
        vm_id="vm-magic-01", provider="hyperv_local_vm", isolation_mode="dedicated_vm", isolated=True
    )


def test_browser_session_actions_and_verification(tmp_path, monkeypatch) -> None:
    adapter = FakeAdapter()
    runtime = DesktopOperatorRuntime(
        adapter=adapter, artifacts_dir=tmp_path, session_ttl_s=300, vm_context=_isolated_vm()
    )
    monkeypatch.setattr(
        "thomas.desktop_operator.runtime.extract_text_from_images", lambda _paths: ["Example page loaded"]
    )

    session = runtime.start_session(
        workflow_profile="browser-session",
        metadata={"objective": "demo", "allowed_domains": ["thomas.ai"]},
    )
    session_id = session["session"]["session_id"]

    apps = runtime.list_apps(executable_contains="chrome")
    assert apps["count"] == 1

    bound = runtime.bind_app(session_id, window_handle=303, move_to_primary=True)
    assert bound["window"]["handle"] == 303
    assert bound["session"]["bound_app_title"] == "Example - Google Chrome"
    assert adapter.last_move_to_primary is True

    acted = runtime.act(session_id, action="open_url", params={"url": "https://thomas.ai"})
    assert acted["navigation_target"] == "https://thomas.ai"
    assert adapter.last_type == {"handle": 303, "text": "https://thomas.ai"}
    assert adapter.last_keys == {"handle": 303, "keys": ["enter"]}

    state = runtime.read_state(session_id)
    assert state["control_layer_used"] == "semantic"
    assert state["profile_state"]["ready"] is True
    assert state["session_state"] == "active"

    verification = runtime.verify(session_id, mode="ocr_contains", ocr_contains="page loaded")
    assert verification["ok"] is True
    assert verification["verification_status"] == "passed"
    assert Path(verification["artifact"]).exists()

    risk = runtime.get_risk_state(session_id)
    assert risk["risk_level"] == "low"
    assert risk["session_state"] == "active"


def test_browser_domain_allowlist_pauses_session(tmp_path, monkeypatch) -> None:
    adapter = FakeAdapter()
    runtime = DesktopOperatorRuntime(
        adapter=adapter, artifacts_dir=tmp_path, session_ttl_s=300, vm_context=_isolated_vm()
    )
    monkeypatch.setattr(
        "thomas.desktop_operator.runtime.extract_text_from_images", lambda _paths: ["Example page loaded"]
    )

    session = runtime.start_session(workflow_profile="browser-session", metadata={"allowed_domains": ["thomas.ai"]})
    session_id = session["session"]["session_id"]
    runtime.bind_app(session_id, window_handle=303)

    with pytest.raises(Exception) as exc:
        runtime.act(session_id, action="open_url", params={"url": "https://evil.example"})
    assert "allowlisted" in str(exc.value).lower()

    risk = runtime.get_risk_state(session_id)
    assert risk["session_state"] == "paused_for_approval"
    assert risk["risk_level"] == "high"

    resumed = runtime.resume_session(session_id, approved=True, reason="approved test override")
    assert resumed["session"]["session_state"] == "active"


def test_file_dialog_and_capcut_actions(tmp_path, monkeypatch) -> None:
    adapter = FakeAdapter()
    runtime = DesktopOperatorRuntime(
        adapter=adapter, artifacts_dir=tmp_path, session_ttl_s=300, vm_context=_isolated_vm()
    )
    monkeypatch.setattr("thomas.desktop_operator.runtime.extract_text_from_images", lambda _paths: ["Timeline ready"])

    capcut = runtime.start_session(workflow_profile="capcut-editing", metadata={"allowed_paths": [r"C:\tmp"]})
    capcut_id = capcut["session"]["session_id"]
    runtime.bind_app(capcut_id, window_handle=101)

    import_result = runtime.act(capcut_id, action="import_assets", params={"paths": [r"C:\tmp\asset.png"]})
    assert import_result["next_expected_workflow_profile"] == "windows-file-dialog"
    assert import_result["pending_asset_paths"] == [r"C:\tmp\asset.png"]

    timeline = runtime.act(capcut_id, action="read_timeline_state", params={})
    assert timeline["profile_state"]["ready"] is True

    exported = tmp_path / "export.mp4"
    exported.write_bytes(b"mp4")
    verification = runtime.verify(capcut_id, mode="artifact_exists", artifact_path=str(exported))
    assert verification["ok"] is True
    assert verification["verification_status"] == "passed"

    runtime.end_session(capcut_id)

    file_dialog = runtime.start_session(workflow_profile="windows-file-dialog", metadata={"allowed_paths": [r"C:\tmp"]})
    dialog_id = file_dialog["session"]["session_id"]
    runtime.bind_app(dialog_id, window_handle=202)
    set_path = runtime.act(dialog_id, action="set_file_path", params={"path": r"C:\tmp\asset.png"})
    assert set_path["selected_path"] == r"C:\tmp\asset.png"
    assert adapter.last_type == {"handle": 202, "text": r"C:\tmp\asset.png"}

    confirm = runtime.act(dialog_id, action="confirm_open", params={})
    assert confirm["ok"] is True
    assert adapter.last_click["handle"] == 202


def test_sensitive_screen_detection_pauses_and_redacts(tmp_path, monkeypatch) -> None:
    adapter = FakeAdapter()
    runtime = DesktopOperatorRuntime(
        adapter=adapter, artifacts_dir=tmp_path, session_ttl_s=300, vm_context=_isolated_vm()
    )
    monkeypatch.setattr(
        "thomas.desktop_operator.runtime.extract_text_from_images",
        lambda _paths: ["Enter password and MFA code to continue"],
    )

    session = runtime.start_session(workflow_profile="browser-session", metadata={"allowed_domains": ["thomas.ai"]})
    session_id = session["session"]["session_id"]
    runtime.bind_app(session_id, window_handle=303)

    state = runtime.read_state(session_id)
    assert state["secret_zone_detected"] is True
    assert state["session_state"] == "paused_for_approval"
    assert "[redacted]" in state["ocr_text_summary"].lower()

    with pytest.raises(Exception):
        runtime.act(session_id, action="refresh_page", params={})

    resumed = runtime.resume_session(session_id, approved=True, reason="user takeover complete")
    assert resumed["session"]["session_state"] == "active"


def test_runtime_recovery_and_shared_session_refusals(tmp_path) -> None:
    adapter = FakeAdapter()
    vm_context = DesktopVmContext(
        vm_id="host", provider="host_session", isolation_mode="shared_session", isolated=False
    )
    runtime = DesktopOperatorRuntime(adapter=adapter, artifacts_dir=tmp_path, session_ttl_s=300, vm_context=vm_context)

    session = runtime.start_session(workflow_profile="browser-session")
    session_id = session["session"]["session_id"]
    runtime.bind_app(session_id, window_handle=303)

    with pytest.raises(Exception) as exc:
        runtime.click(session_id, x=12, y=12)
    assert "requires an isolated desktop operator vm/session" in str(exc.value).lower()

    adapter.foreground = 303
    recovered = runtime.recover(session_id, strategy="rebind_foreground")
    assert recovered["window"]["handle"] == 303
    risk = runtime.get_risk_state(session_id)
    assert risk["risk_level"] in {"medium", "high"}


def test_helper_server_round_trip(tmp_path, monkeypatch) -> None:
    adapter = FakeAdapter()
    runtime = DesktopOperatorRuntime(
        adapter=adapter, artifacts_dir=tmp_path, session_ttl_s=300, vm_context=_isolated_vm()
    )
    monkeypatch.setattr(
        "thomas.desktop_operator.runtime.extract_text_from_images", lambda _paths: ["Example page loaded"]
    )
    server = DesktopOperatorHelperServer(host="127.0.0.1", port=0, bearer_token="token-123", runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = DesktopOperatorClient(base_url=f"http://127.0.0.1:{server.port}", token="token-123")
        session = client.call(
            "/start_session", {"workflow_profile": "browser-session", "metadata": {"allowed_domains": ["thomas.ai"]}}
        )
        session_id = session["session"]["session_id"]

        apps = client.call("/list_apps", {"executable_contains": "chrome"})
        assert apps["count"] == 1

        bound = client.call("/bind_app", {"session_id": session_id, "window_handle": 303})
        assert bound["window"]["handle"] == 303

        acted = client.call(
            "/act", {"session_id": session_id, "action": "open_url", "params": {"url": "https://thomas.ai"}}
        )
        assert acted["navigation_target"] == "https://thomas.ai"

        risk = client.call("/get_risk_state", {"session_id": session_id})
        assert risk["session_state"] == "active"

        verified = client.call("/verify", {"session_id": session_id, "mode": "ready"})
        assert verified["verification_status"] == "passed"

        paused = client.call("/pause_session", {"session_id": session_id, "reason": "manual"})
        assert paused["session"]["session_state"] == "paused_for_approval"

        resumed = client.call("/resume_session", {"session_id": session_id, "approved": True})
        assert resumed["session"]["session_state"] == "active"
    finally:
        server.shutdown()
