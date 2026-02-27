"""Live browser smoke testing for the Thomas web UI via CDP."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


class LiveBrowserSmokeError(RuntimeError):
    """Raised when live browser smoke validation cannot run or fails."""


@dataclass(frozen=True)
class LiveBrowserSmokeResult:
    ok: bool
    expected: str
    matched_expected: bool
    final_text: str
    page_url: str
    cdp_url: str
    launched_browser: bool
    stdout: str
    stderr: str


def _devtools_probe_url(cdp_url: str) -> str:
    return cdp_url.rstrip("/") + "/json/version"


def _cdp_ready(cdp_url: str, timeout_s: float = 0.75) -> bool:
    probe = _devtools_probe_url(cdp_url)
    try:
        r = httpx.get(probe, timeout=max(0.1, float(timeout_s)))
    except (ConnectionError, TimeoutError):
        return False
    if r.status_code != 200:
        return False
    try:
        data = r.json()
    except (ConnectionError, TimeoutError):
        return False
    return isinstance(data, dict) and bool(data.get("webSocketDebuggerUrl"))


def _parse_cdp_port(cdp_url: str) -> int:
    parsed = urlparse(cdp_url)
    if parsed.scheme not in ("http", "https"):
        raise LiveBrowserSmokeError(f"CDP URL must be http(s), got: {cdp_url}")
    if not parsed.hostname:
        raise LiveBrowserSmokeError(f"CDP URL missing host: {cdp_url}")
    return int(parsed.port or 9222)


def _find_browser_exe(browser: str) -> str | None:
    b = str(browser or "").strip().lower()
    if b not in ("chrome", "edge"):
        raise LiveBrowserSmokeError(f"Unsupported browser: {browser}")

    if b == "chrome":
        names = ["chrome.exe", "chrome"]
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    else:
        names = ["msedge.exe", "msedge"]
        paths = [
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]

    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for p in paths:
        if Path(p).exists():
            return p
    return None


def _launch_browser_with_cdp(
    browser: str,
    cdp_url: str,
    app_url: str,
    runtime_root: Path,
) -> subprocess.Popen:
    exe = _find_browser_exe(browser)
    if not exe:
        raise LiveBrowserSmokeError(f"Could not find {browser} executable. Install it or pass a reachable CDP URL.")

    port = _parse_cdp_port(cdp_url)
    profile_dir = runtime_root / ".thomas" / "live_browser_cdp_profile" / f"{browser}_{port}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={str(profile_dir)}",
        "--new-window",
        app_url,
    ]
    return subprocess.Popen(  # nosec B603
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_cdp(cdp_url: str, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    while time.monotonic() < deadline:
        if _cdp_ready(cdp_url):
            return True
        time.sleep(0.35)
    return False


def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.35)
            return s.connect_ex((host, int(port))) == 0
    except (ConnectionError, TimeoutError):
        return False


def _find_fallback_cdp_url(cdp_url: str, max_hops: int = 30) -> str | None:
    parsed = urlparse(cdp_url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    base_port = int(parsed.port or 9222)
    for port in range(base_port + 1, base_port + 1 + max_hops):
        if not _port_in_use(host, port):
            return f"{scheme}://{host}:{port}"
    return None


def _list_page_targets(cdp_url: str) -> list[dict[str, Any]]:
    endpoint = cdp_url.rstrip("/") + "/json"
    try:
        r = httpx.get(endpoint, timeout=2.0)
        r.raise_for_status()
    except Exception as e:
        raise LiveBrowserSmokeError(f"Failed to list CDP targets at {endpoint}: {e}") from e
    data = r.json()
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "") != "page":
            continue
        if not row.get("webSocketDebuggerUrl"):
            continue
        out.append(row)
    return out


class _CdpClient:
    def __init__(self, ws_url: str):
        try:
            import websocket  # type: ignore
        except Exception as e:  # pragma: no cover - env-dependent
            raise LiveBrowserSmokeError(
                "Missing dependency: websocket-client. Install with `pip install websocket-client`."
            ) from e
        try:
            self._ws = websocket.create_connection(ws_url, timeout=20.0)
        except Exception as e:
            msg = str(e)
            hint = ""
            if "remote-allow-origins" in msg.lower():
                hint = (
                    " Browser rejected CDP websocket origin. "
                    "Launch browser with --remote-allow-origins=* "
                    "(or a specific allowed origin)."
                )
            raise LiveBrowserSmokeError(f"Failed to connect CDP websocket: {msg}.{hint}") from e
        self._next_id = 1

    def close(self) -> None:
        try:
            self._ws.close()
        except (ConnectionError, TimeoutError):
            pass

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        msg_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        try:
            self._ws.send(json.dumps(payload))
        except Exception as e:
            raise LiveBrowserSmokeError(f"CDP send failed for {method}: {e}") from e
        while True:
            try:
                raw = self._ws.recv()
            except Exception as e:
                raise LiveBrowserSmokeError(f"CDP receive failed for {method}: {e}") from e
            msg = json.loads(raw)
            if int(msg.get("id") or 0) != msg_id:
                continue
            if "error" in msg:
                err = msg.get("error") or {}
                raise LiveBrowserSmokeError(f"CDP {method} failed: {err}")
            result = msg.get("result")
            if isinstance(result, dict):
                return result
            return {}


def _eval_js(client: _CdpClient, expression: str) -> Any:
    result = client.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
    )
    if result.get("exceptionDetails"):
        details = result.get("exceptionDetails") or {}
        text = str(details.get("text") or "JavaScript evaluation failed")
        raise LiveBrowserSmokeError(text)
    obj = result.get("result") or {}
    if not isinstance(obj, dict):
        return None
    if "value" in obj:
        return obj.get("value")
    return None


def run_live_browser_smoke(
    *,
    app_url: str,
    cdp_url: str,
    prompt: str,
    expect: str,
    type_delay_ms: int,
    wait_timeout_s: float,
    launch_browser: bool,
    browser: str,
    runtime_root: Path,
) -> LiveBrowserSmokeResult:
    active_cdp_url = cdp_url
    launched = False
    if not _cdp_ready(active_cdp_url):
        if not launch_browser:
            raise LiveBrowserSmokeError(
                f"CDP is not reachable at {active_cdp_url}. Start browser with --remote-debugging-port first."
            )
        _launch_browser_with_cdp(
            browser=browser,
            cdp_url=active_cdp_url,
            app_url=app_url,
            runtime_root=runtime_root,
        )
        launched = True
        if not _wait_for_cdp(active_cdp_url, timeout_s=15.0):
            raise LiveBrowserSmokeError(f"Timed out waiting for CDP endpoint: {_devtools_probe_url(active_cdp_url)}")

    def _open_client_for(url: str) -> tuple[_CdpClient, dict[str, Any]]:
        targets = _list_page_targets(url)
        if not targets:
            raise LiveBrowserSmokeError("No page targets found in browser. Open at least one tab and rerun.")
        selected = None
        for t in targets:
            page_url = str(t.get("url") or "")
            if page_url.startswith(app_url):
                selected = t
                break
        if selected is None:
            selected = targets[0]
        ws_url = str(selected.get("webSocketDebuggerUrl") or "").strip()
        if not ws_url:
            raise LiveBrowserSmokeError("Selected target missing webSocketDebuggerUrl.")
        return _CdpClient(ws_url), selected

    selected: dict[str, Any]
    try:
        client, selected = _open_client_for(active_cdp_url)
    except LiveBrowserSmokeError as e:
        if launch_browser and not launched and "remote-allow-origins" in str(e).lower():
            alt = _find_fallback_cdp_url(active_cdp_url)
            if not alt:
                raise
            _launch_browser_with_cdp(
                browser=browser,
                cdp_url=alt,
                app_url=app_url,
                runtime_root=runtime_root,
            )
            launched = True
            if not _wait_for_cdp(alt, timeout_s=15.0):
                raise LiveBrowserSmokeError(
                    f"Timed out waiting for fallback CDP endpoint: {_devtools_probe_url(alt)}"
                ) from e
            active_cdp_url = alt
            client, selected = _open_client_for(active_cdp_url)
        else:
            raise
    try:
        client.call("Runtime.enable")
        client.call("Page.enable")
        client.call("Page.bringToFront")

        current_url = str(selected.get("url") or "")
        if not current_url.startswith(app_url):
            client.call("Page.navigate", {"url": app_url})

        wait_deadline = time.monotonic() + max(5.0, float(wait_timeout_s))
        composer_ready = False
        while time.monotonic() < wait_deadline:
            ready = _eval_js(
                client, "Boolean(document.querySelector('#composerTextarea') && document.querySelector('#sendBtn'))"
            )
            if bool(ready):
                composer_ready = True
                break
            time.sleep(0.25)
        if not composer_ready:
            raise LiveBrowserSmokeError("Composer not found (#composerTextarea / #sendBtn).")

        before = _eval_js(
            client,
            """
(() => Array.from(document.querySelectorAll('.message'))
  .filter((m) => (m.querySelector('.message-role')?.textContent || '').trim() === 'Thomas').length)()
""".strip(),
        )
        before_count = int(before or 0)

        prep = _eval_js(
            client,
            """
(() => {
  const ta = document.querySelector('#composerTextarea');
  const btn = document.querySelector('#sendBtn');
  if (!ta || !btn) return { ok: false, error: 'composer_missing' };
  ta.focus();
  ta.value = '';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  return { ok: true };
})()
""".strip(),
        )
        if not isinstance(prep, dict) or not bool(prep.get("ok")):
            raise LiveBrowserSmokeError(f"Failed to prepare composer: {prep}")

        per_char_delay_s = max(0, int(type_delay_ms)) / 1000.0
        for ch in str(prompt or ""):
            appended = _eval_js(
                client,
                f"""
(() => {{
  const ta = document.querySelector('#composerTextarea');
  if (!ta) return false;
  ta.value = ta.value + {json.dumps(ch)};
  ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
  return true;
}})()
""".strip(),
            )
            if not bool(appended):
                raise LiveBrowserSmokeError("Composer disappeared while typing.")
            if per_char_delay_s > 0:
                time.sleep(per_char_delay_s)

        send_res = _eval_js(
            client,
            """
(() => {
  const btn = document.querySelector('#sendBtn');
  if (!btn) return { ok: false, error: 'send_missing' };
  if (btn.disabled) return { ok: false, error: 'send_disabled' };
  btn.click();
  return { ok: true };
})()
""".strip(),
        )
        if not isinstance(send_res, dict) or not bool(send_res.get("ok")):
            raise LiveBrowserSmokeError(f"Failed to click send: {send_res}")

        reply_deadline = time.monotonic() + max(5.0, float(wait_timeout_s))
        latest_text = ""
        latest_url = app_url
        got_reply = False
        while time.monotonic() < reply_deadline:
            snap = _eval_js(
                client,
                """
(() => {
  const assistant = Array.from(document.querySelectorAll('.message'))
    .filter((m) => (m.querySelector('.message-role')?.textContent || '').trim() === 'Thomas');
  const last = assistant[assistant.length - 1];
  const text = (last?.querySelector('.message-content')?.innerText || '').trim();
  const status = (document.querySelector('#statusText')?.textContent || '').toLowerCase();
  return {
    assistantCount: assistant.length,
    lastText: text,
    status,
    url: location.href,
  };
})()
""".strip(),
            )
            if isinstance(snap, dict):
                latest_text = str(snap.get("lastText") or "")
                latest_url = str(snap.get("url") or latest_url)
                count = int(snap.get("assistantCount") or 0)
                status = str(snap.get("status") or "")
                if count > before_count and ("done" in status or "ready" in status):
                    got_reply = True
                    break
            time.sleep(0.4)

        if not got_reply:
            raise LiveBrowserSmokeError("Timed out waiting for assistant completion in UI.")

        expected = str(expect or "")
        matched = (expected == "") or (expected in latest_text)
        return LiveBrowserSmokeResult(
            ok=bool(matched),
            expected=expected,
            matched_expected=bool(matched),
            final_text=latest_text,
            page_url=latest_url,
            cdp_url=active_cdp_url,
            launched_browser=launched,
            stdout="",
            stderr="",
        )
    finally:
        client.close()
