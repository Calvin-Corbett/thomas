from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .contracts import DesktopOperatorError, invalid_input
from .runtime import DesktopOperatorRuntime


class _HelperRequestHandler(BaseHTTPRequestHandler):
    runtime: DesktopOperatorRuntime
    bearer_token: str

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/health":
                self._write_json(HTTPStatus.OK, {"ok": True, "status": "ok"})
                return
            if self.path == "/status":
                self._require_auth()
                self._write_json(HTTPStatus.OK, {"ok": True, "data": self.runtime.status_payload()})
                return
            self._write_json(
                HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "not_found", "message": "not found"}}
            )
        except DesktopOperatorError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": exc.to_dict()})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._require_auth()
            payload = self._read_json_body()
            data = self._dispatch(self.path, payload)
            self._write_json(HTTPStatus.OK, {"ok": True, "data": data})
        except DesktopOperatorError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": exc.to_dict()})
        except Exception as exc:  # noqa: BLE001
            err = DesktopOperatorError(
                "external_failure", "Desktop helper request failed.", details={"type": type(exc).__name__}
            )
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": err.to_dict()})

    def _dispatch(self, path: str, payload: dict[str, Any]) -> Any:
        if path == "/start_session":
            return self.runtime.start_session(
                workflow_profile=str(payload.get("workflow_profile") or ""),
                session_type=str(payload.get("session_type") or ""),
                session_ttl_s=int(payload["session_ttl_s"]) if payload.get("session_ttl_s") is not None else None,
                metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            )
        if path == "/pause_session":
            return self.runtime.pause_session(
                str(payload.get("session_id") or ""),
                reason=str(payload.get("reason") or ""),
            )
        if path == "/resume_session":
            return self.runtime.resume_session(
                str(payload.get("session_id") or ""),
                approved=bool(payload.get("approved", False)),
                reason=str(payload.get("reason") or ""),
            )
        if path == "/terminate_session":
            return self.runtime.terminate_session(
                str(payload.get("session_id") or ""),
                reason=str(payload.get("reason") or ""),
            )
        if path == "/get_risk_state":
            return self.runtime.get_risk_state(str(payload.get("session_id") or ""))
        if path == "/list_apps":
            return self.runtime.list_apps(
                title_contains=str(payload.get("title_contains") or ""),
                executable_contains=str(payload.get("executable_contains") or ""),
                visible_only=bool(payload.get("visible_only", True)),
                limit=int(payload.get("limit") or 40),
            )
        if path == "/bind_app":
            return self.runtime.bind_app(
                str(payload.get("session_id") or ""),
                window_handle=int(payload["window_handle"]) if payload.get("window_handle") is not None else None,
                title_contains=str(payload.get("title_contains") or ""),
                executable_contains=str(payload.get("executable_contains") or ""),
                move_to_primary=bool(payload.get("move_to_primary", False)),
            )
        if path == "/capture":
            return self.runtime.capture(str(payload.get("session_id") or ""))
        if path == "/act":
            return self.runtime.act(
                str(payload.get("session_id") or ""),
                action=str(payload.get("action") or ""),
                params=payload.get("params") if isinstance(payload.get("params"), dict) else None,
            )
        if path == "/verify":
            return self.runtime.verify(
                str(payload.get("session_id") or ""),
                mode=str(payload.get("mode") or "ready"),
                title_contains=str(payload.get("title_contains") or ""),
                ocr_contains=str(payload.get("ocr_contains") or ""),
                artifact_path=str(payload.get("artifact_path") or ""),
                capture_source=str(payload.get("capture_source") or ""),
            )
        if path == "/recover":
            return self.runtime.recover(
                str(payload.get("session_id") or ""),
                strategy=str(payload.get("strategy") or "ensure_visible"),
            )
        if path == "/end_session":
            return self.runtime.end_session(str(payload.get("session_id") or ""))

        if path == "/list_windows":
            return self.runtime.list_windows(
                title_contains=str(payload.get("title_contains") or ""),
                executable_contains=str(payload.get("executable_contains") or ""),
                visible_only=bool(payload.get("visible_only", True)),
                limit=int(payload.get("limit") or 40),
            )
        if path == "/bind_window":
            return self.runtime.bind_window(
                window_handle=int(payload["window_handle"]) if payload.get("window_handle") is not None else None,
                title_contains=str(payload.get("title_contains") or ""),
                executable_contains=str(payload.get("executable_contains") or ""),
                move_to_primary=bool(payload.get("move_to_primary", False)),
                session_ttl_s=int(payload["session_ttl_s"]) if payload.get("session_ttl_s") is not None else None,
                workflow_profile=str(payload.get("workflow_profile") or ""),
            )
        if path == "/capture_window":
            return self.runtime.capture_window(str(payload.get("session_id") or ""))
        if path == "/ax_snapshot":
            return self.runtime.ax_snapshot(str(payload.get("session_id") or ""))
        if path == "/read_state":
            return self.runtime.read_state(str(payload.get("session_id") or ""))
        if path == "/click":
            return self.runtime.click(
                str(payload.get("session_id") or ""),
                x=int(payload["x"]) if payload.get("x") is not None else None,
                y=int(payload["y"]) if payload.get("y") is not None else None,
                selector=payload.get("selector") if isinstance(payload.get("selector"), dict) else None,
                button=str(payload.get("button") or "left"),
                double=bool(payload.get("double", False)),
            )
        if path == "/type":
            return self.runtime.type_text(str(payload.get("session_id") or ""), text=str(payload.get("text") or ""))
        if path == "/press_keys":
            return self.runtime.press_keys(
                str(payload.get("session_id") or ""),
                keys=[str(x) for x in (payload.get("keys") or []) if str(x or "").strip()],
            )
        if path == "/drag":
            return self.runtime.drag(
                str(payload.get("session_id") or ""),
                start_x=int(payload.get("start_x") or 0),
                start_y=int(payload.get("start_y") or 0),
                end_x=int(payload.get("end_x") or 0),
                end_y=int(payload.get("end_y") or 0),
            )
        if path == "/ensure_visible":
            return self.runtime.ensure_visible(
                str(payload.get("session_id") or ""),
                move_to_primary=bool(payload.get("move_to_primary", False)),
            )
        raise invalid_input("Unknown desktop helper endpoint.", path=path)

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(max(0, length)) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise invalid_input("Request body must be valid JSON.", reason=type(exc).__name__) from None
        if not isinstance(payload, dict):
            raise invalid_input("Request body must be a JSON object.")
        return payload

    def _require_auth(self) -> None:
        header = str(self.headers.get("Authorization") or "")
        expected = f"Bearer {self.bearer_token}"
        if header != expected:
            raise DesktopOperatorError("unauthorized", "Missing or invalid desktop helper token.")

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class DesktopOperatorHelperServer:
    def __init__(self, *, host: str, port: int, bearer_token: str, runtime: DesktopOperatorRuntime) -> None:
        handler = type(
            "DesktopOperatorBoundHandler",
            (_HelperRequestHandler,),
            {"runtime": runtime, "bearer_token": bearer_token},
        )
        self._server = ThreadingHTTPServer((host, int(port)), handler)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.2)

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
