from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

from thomas.desktop_operator.host_pipe import DesktopHostPipeServer
from thomas.desktop_operator.host_service import (
    DEFAULT_HOST_BOOTSTRAP_PATH,
    DEFAULT_PIPE_NAME,
    DEFAULT_SERVICE_NAME,
    DesktopHostCapabilityService,
    get_global_desktop_host_service,
)

try:  # pragma: no cover - Windows-only integration surface
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
except ImportError:  # pragma: no cover
    servicemanager = None
    win32event = None
    win32service = None
    win32serviceutil = None


def _service(root_dir: str | None) -> DesktopHostCapabilityService:
    if root_dir:
        return DesktopHostCapabilityService(root_dir=Path(root_dir))
    return get_global_desktop_host_service()


def _dispatch(service: DesktopHostCapabilityService, action: str, payload: dict) -> dict:
    if action == "get_host_posture":
        return {"ok": True, "data": service.status().to_dict()}
    if action == "install_host_capability":
        return {
            "ok": True,
            "data": service.install_host_capability(stage_only=bool(payload.get("stage_only", True))).to_dict(),
        }
    if action == "ensure_local_vm_ready":
        return {"ok": True, "data": service.ensure_local_vm_ready().to_dict()}
    if action == "set_remote_trust_mode":
        return {
            "ok": True,
            "data": service.set_remote_trust_mode(str(payload.get("trust_mode") or "ask_every_time")).to_dict(),
        }
    if action == "get_remote_fallback_options":
        return {"ok": True, "data": service.get_remote_fallback_options()}
    if action == "request_opt_in":
        return {
            "ok": True,
            "data": service.request_opt_in(hidden_by_default=bool(payload.get("hidden_by_default", True))).to_dict(),
        }
    if action == "disable":
        return {"ok": True, "data": service.disable().to_dict()}
    if action == "launch_viewer":
        return {"ok": True, "data": service.launch_viewer()}
    return {"ok": False, "error": {"code": "unsupported", "message": f"unsupported action: {action}"}}


def _authkey_for_service(service: DesktopHostCapabilityService) -> bytes:
    authkey_text = service.authkey_path.read_text(encoding="utf-8").strip() if service.authkey_path.exists() else ""
    if not authkey_text:
        service.install_host_capability(stage_only=True)
        authkey_text = service.authkey_path.read_text(encoding="utf-8").strip()
    return base64.urlsafe_b64decode(authkey_text.encode("ascii"))


def _load_service_runtime_settings() -> dict[str, Any]:
    settings: dict[str, Any] = {
        "service_name": DEFAULT_SERVICE_NAME,
        "pipe_name": DEFAULT_PIPE_NAME,
        "root_dir": None,
    }
    config_path = Path(os.environ.get("THOMAS_DESKTOP_HOST_BOOTSTRAP_PATH") or DEFAULT_HOST_BOOTSTRAP_PATH)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        service_name = str(payload.get("service_name") or "").strip()
        pipe_name = str(payload.get("pipe_name") or "").strip()
        root_dir = str(payload.get("root_dir") or "").strip()
        if service_name:
            settings["service_name"] = service_name
        if pipe_name:
            settings["pipe_name"] = pipe_name
        if root_dir:
            settings["root_dir"] = root_dir
    return settings


_SERVICE_RUNTIME_SETTINGS = _load_service_runtime_settings()


if all((win32serviceutil, win32service, win32event, servicemanager)):

    class ThomasDesktopHostWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = str(_SERVICE_RUNTIME_SETTINGS.get("service_name") or DEFAULT_SERVICE_NAME)
        _svc_display_name_ = "Thomas Desktop Host Service"
        _svc_description_ = "Thomas-managed isolated desktop host capability."
        _thomas_pipe_name_ = str(_SERVICE_RUNTIME_SETTINGS.get("pipe_name") or DEFAULT_PIPE_NAME)
        _thomas_root_dir_: str | None = _SERVICE_RUNTIME_SETTINGS.get("root_dir")

        def __init__(self, args):
            super().__init__(args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._server: DesktopHostPipeServer | None = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self._server is not None:
                self._server.close()
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self):
            service_name = str(getattr(self, "_svc_name_", DEFAULT_SERVICE_NAME) or DEFAULT_SERVICE_NAME)
            pipe_name = str(getattr(self, "_thomas_pipe_name_", DEFAULT_PIPE_NAME) or DEFAULT_PIPE_NAME)
            root_dir = getattr(self, "_thomas_root_dir_", None)
            servicemanager.LogInfoMsg(f"{service_name}: starting Thomas desktop host service")
            service = _service(root_dir)
            authkey = _authkey_for_service(service)
            self._server = DesktopHostPipeServer(pipe_name=pipe_name, authkey=authkey)
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            try:
                self._server.serve_forever(
                    lambda message: _dispatch(
                        service,
                        str(message.get("action") or ""),
                        message.get("payload") if isinstance(message.get("payload"), dict) else {},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                servicemanager.LogErrorMsg(f"{service_name}: host service crashed: {type(exc).__name__}: {exc}")
                raise
            finally:
                if self._server is not None:
                    self._server.close()
                servicemanager.LogInfoMsg(f"{service_name}: Thomas desktop host service stopped")
else:  # pragma: no cover
    ThomasDesktopHostWindowsService = None


def _build_service_class(*, service_name: str, pipe_name: str, root_dir: str | None):
    if ThomasDesktopHostWindowsService is None:
        raise RuntimeError("pywin32 service modules are unavailable")
    ThomasDesktopHostWindowsService._svc_name_ = service_name
    ThomasDesktopHostWindowsService._thomas_pipe_name_ = pipe_name
    ThomasDesktopHostWindowsService._thomas_root_dir_ = root_dir
    return ThomasDesktopHostWindowsService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Thomas Desktop Host Service runner")
    parser.add_argument("--pipe-name", default=DEFAULT_PIPE_NAME)
    parser.add_argument("--root-dir", default="")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--status-json", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("service_command", nargs="*")
    args, extra = parser.parse_known_args(argv)

    service = _service(args.root_dir or None)
    if args.status_json:
        print(json.dumps(service.status().to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.install:
        print(json.dumps(service.install_host_capability(stage_only=False).to_dict(), ensure_ascii=False, indent=2))
        return 0

    service_command = [*args.service_command, *extra]
    if service_command:
        if win32serviceutil is None:
            raise SystemExit("pywin32 service support is unavailable")
        service_cls = _build_service_class(
            service_name=str(args.service_name or DEFAULT_SERVICE_NAME).strip() or DEFAULT_SERVICE_NAME,
            pipe_name=str(args.pipe_name or DEFAULT_PIPE_NAME).strip() or DEFAULT_PIPE_NAME,
            root_dir=str(args.root_dir or "").strip() or None,
        )
        forwarded_command = list(service_command)
        if forwarded_command[0] in {"install", "update"} and len(forwarded_command) > 1:
            forwarded_command = [*forwarded_command[1:], forwarded_command[0]]
        win32serviceutil.HandleCommandLine(service_cls, argv=[args.service_name, *forwarded_command])
        return 0

    if not args.serve:
        print(json.dumps(service.status().to_dict(), ensure_ascii=False, indent=2))
        return 0

    authkey = _authkey_for_service(service)
    server = DesktopHostPipeServer(pipe_name=args.pipe_name, authkey=authkey)
    server.serve_forever(
        lambda message: _dispatch(
            service,
            str(message.get("action") or ""),
            message.get("payload") if isinstance(message.get("payload"), dict) else {},
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
