"""Capture a green through the caged server's read-only file route: GET only, loopback only, no redirects.

Part of the capture tool; ``capture.py`` is its command line (see its notes).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from .capture_settings import CID, DEFAULT_SERVER, Budget, CaptureRefused, Settings
from .capture_steps import _archive, _base_manifest, _finish, _holding, _ready, _verdicts, _workspace
from .keep import UnsafePath, safe_rel


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect would send the GET somewhere else: refuse it
        return None


def _loopback(server: str) -> str:
    parts = urllib.parse.urlsplit(server)
    if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1") or parts.path.strip("/"):
        raise CaptureRefused(f"{server} is not the caged server on this machine; greens are read only from loopback")
    return f"http://{parts.netloc}"


def _get_json(opener, url: str, timeout: float) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read(16 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(1 << 20))
        except ValueError:
            return exc.code, {}


def listed_files(server: str, cid: str, timeout: float = 180.0) -> list[str]:
    """A project's changed files from ``GET /api/self/projects`` (no files: an empty list)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    _, body = _get_json(opener, f"{_loopback(server)}/api/self/projects", timeout)
    return next((p.get("changed_files") or [] for p in body.get("projects", []) if p.get("conversation_id") == cid), [])


def capture_green(
    cid: str,
    paths: Iterable[str],
    settings: Settings,
    server: str = DEFAULT_SERVER,
    main_git: Path | None = None,
    base: str | None = None,
) -> dict:
    """Save a green's files through the caged server's read-only route. Refused files are listed as at risk."""
    if not CID.fullmatch(cid) or ".." in cid:
        raise CaptureRefused(f"{cid!r} is not a conversation id")
    origin = _loopback(server)
    _ready(settings, None, main_git)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    key = f"green:{cid}"
    with _workspace(settings, key) as (cap_id, at, tmp, stack):
        manifest = _base_manifest(settings, cap_id, at, "green", key, f"{origin} conversation {cid}")
        manifest["base"] = base
        archive = _archive(stack, tmp, Budget(settings))
        holdings, refused = [], []
        for path in sorted(set(paths)):
            try:
                safe_rel(path)
            except UnsafePath:
                refused.append({"path": path, "code": "unsafe_path"})
                continue
            url = f"{origin}/api/evolve/agent/conversations/{cid}/file?path={urllib.parse.quote(path, safe='')}"
            try:
                status, body = _get_json(opener, url, 60.0)
            except (OSError, ValueError) as exc:
                refused.append({"path": path, "code": f"route did not answer: {exc}"})
                continue
            if status != 200 or not body.get("ok") or not isinstance(body.get("content"), str):
                refused.append({"path": path, "code": str(body.get("error") or f"HTTP {status}")})
                continue
            data = body["content"].encode("utf-8")
            h = _holding(path, data, status="green", via="green-route (text, re-encoded as UTF-8)")
            h["stored"] = f"files/{path}"
            h["sha256"] = archive.add(h["stored"], data, kind="file", path=path)["sha256"]
            holdings.append(h)
        manifest["dev"] = _verdicts(settings, tmp, main_git, holdings, by_path=True)
        manifest.update(holdings=holdings, refused=refused, at_risk=[r["path"] for r in refused])
        return _finish(settings, manifest, tmp, archive, None, None)
