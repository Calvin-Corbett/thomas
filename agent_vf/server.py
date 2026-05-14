from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from agent_vf.cli_runtime import build_agent


class Handler(BaseHTTPRequestHandler):
    agent = None

    def _send(self, code: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": True})
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/chat":
            self._send(404, {"ok": False, "error": "not_found"})
            return
        n = int(self.headers.get("Content-Length","0") or "0")
        raw = self.rfile.read(n).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            self._send(400, {"ok": False, "error":"bad_json"})
            return
        user_text = body.get("text","")
        if not user_text:
            self._send(400, {"ok": False, "error":"missing_text"})
            return
        ans = self.agent.chat(user_text)
        self._send(200, {"ok": True, "text": ans})

def serve(host: str="127.0.0.1", port: int=8899, root: str="./runtime"):
    agent = build_agent(root=root)
    Handler.agent = agent
    httpd = HTTPServer((host, port), Handler)
    try:
        print(f"agent_vf server on http://{host}:{port}")
        httpd.serve_forever()
    finally:
        try: agent.close()
        except Exception: pass
