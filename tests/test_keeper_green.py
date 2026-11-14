"""Keeper capture v1 (design section 6, P0.3): a green is captured through the caged server's read-only file route,
by GET only and only from this machine, and what the route will not give is listed as at risk."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from scripts.keeper.capture import CaptureRefused, capture_green
from scripts.keeper.keep import restore

# world is a pytest fixture, shared through keeper_support
from tests.keeper_support import _manifest, keep_files, world


class _Green(BaseHTTPRequestHandler):
    files = {"thomas/work/store.py": "def store():\r\n    return 1\r\n", "docs/notes.md": "# notes\n"}
    methods: list[str] = []

    def do_GET(self):  # noqa: N802
        self.methods.append("GET")
        query = parse_qs(urlsplit(self.path).query)
        path = query.get("path", [""])[0]
        if path in self.files:
            body = {"ok": True, "content": self.files[path]}
        else:
            body = {"ok": False, "error": "binary files cannot be previewed as text"}
        data = json.dumps(body).encode()
        self.send_response(200 if body["ok"] else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        self.methods.append("POST")
        self.send_response(405)
        self.end_headers()

    def log_message(self, *_args):
        pass


def test_green_capture_reads_only_through_get_and_lists_what_it_could_not(world, tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Green)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Green.methods.clear()
    try:
        paths = [*_Green.files, "assets/logo.png"]
        url = f"http://127.0.0.1:{server.server_address[1]}"
        result = capture_green("fc_20260928T212447_f2ed21", paths, world.settings(), url, world.main_git)
    finally:
        server.shutdown()
    manifest = _manifest(world, result)
    assert set(_Green.methods) == {"GET"} and len(_Green.methods) == 3
    assert manifest["at_risk"] == ["assets/logo.png"] and len(manifest["holdings"]) == 2
    report = restore(world.keep, result["id"], tmp_path / "green")
    assert report["ok"]
    for rel, text in _Green.files.items():
        assert (tmp_path / "green" / "files" / rel).read_bytes() == text.encode("utf-8")


def test_green_capture_reads_only_from_this_machine(world):
    for bad in ("http://example.com", "https://127.0.0.1:8898", "http://127.0.0.1:8898/elsewhere"):
        with pytest.raises(CaptureRefused):
            capture_green("fc_1", ["a.py"], world.settings(), bad)
    with pytest.raises(CaptureRefused):
        capture_green("../../etc", ["a.py"], world.settings(), "http://127.0.0.1:8898")
    assert keep_files(world.keep) == []
