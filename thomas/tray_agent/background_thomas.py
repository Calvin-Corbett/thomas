"""Read-only, independently polled snapshot for the Background Thomas tray menu."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime

BACKGROUND_PORT = 8898
BASE_URL = f"http://127.0.0.1:{BACKGROUND_PORT}/"
HEALTH_URL = BASE_URL + "api/health"
PROJECTS_URL = BASE_URL + "api/self/projects"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _get_json(url: str, timeout: int) -> object:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, method="GET")
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Unexpected status")
        return json.load(response)


class BackgroundThomas:
    """Health and listing use separate workers; the last good listing stays visible."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listing_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._on = False
        self._projects: list[dict] | None = None
        self.last_listing_at: float | None = None

    @property
    def running(self) -> bool:
        return bool(self._threads) and not self._stop.is_set()

    def poll_health_once(self) -> None:
        try:
            answer = _get_json(HEALTH_URL, 5)
            on = isinstance(answer, dict) and answer.get("status") == "ok"
        except Exception:
            on = False
        with self._lock:
            self._on = on

    def poll_projects_once(self) -> None:
        # Do not overlap requests even when asked directly during a worker poll.
        if not self._listing_lock.acquire(blocking=False):
            return
        try:
            try:
                answer = _get_json(PROJECTS_URL, 600)
                if not isinstance(answer, dict) or not isinstance(answer.get("projects"), list):
                    return
                projects = answer["projects"]
                if not all(isinstance(project, dict) for project in projects):
                    return
                with self._lock:
                    self._projects = projects
                    self.last_listing_at = time.time()
            except Exception:
                pass  # Keep the last good answer and its original timestamp.
        finally:
            self._listing_lock.release()

    def _poll_loop(self, poll, interval: int) -> None:
        while not self._stop.is_set():
            poll()
            if self._stop.wait(interval):
                break

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(
                target=self._poll_loop, args=(self.poll_health_once, 30), daemon=True, name="tray-background-health"
            ),
            threading.Thread(
                target=self._poll_loop, args=(self.poll_projects_once, 60), daemon=True, name="tray-background-projects"
            ),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        # A listing may be inside a 600-second socket timeout; do not hold up Quit.
        for thread in self._threads:
            thread.join(timeout=0.2)
        self._threads = []

    def lines(self, now: float | None = None) -> tuple[str, ...]:
        with self._lock:
            on = self._on
            projects = self._projects
            received_at = self.last_listing_at
        lines = [f"Background Thomas: {'on' if on else 'off'}"]
        if projects is None or received_at is None:
            return (*lines, "Project listing has not answered yet")
        age = max(0, int(((time.time() if now is None else now) - received_at) // 60))
        running = sum(
            str(row.get("state") or "").lower() == "running"
            or str(row.get("state") or "").lower().startswith("repair round")
            for row in projects
        )
        waiting = sum(str(row.get("state") or "").lower() == "awaiting verdict" for row in projects)
        lines.extend(
            (
                f"{running} Build team{'s' if running != 1 else ''} running",
                f"{waiting} hand-in{'s' if waiting != 1 else ''} waiting for your card",
                f"Project listing: {age} minute{'s' if age != 1 else ''} old",
            )
        )
        landed = []
        for row in projects:
            if row.get("state") != "landed" or not row.get("updated_at"):
                continue
            try:
                local_time = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00")).astimezone()
            except (TypeError, ValueError, OverflowError):
                continue
            landed.append((local_time, row))
        if landed:
            local_time, latest = max(landed, key=lambda item: item[0])
            title = " ".join(str(latest.get("title") or "Untitled").split())
            if len(title) > 44:
                title = title[:43] + "…"
            lines.append(f"Last landing: {title} · handed in {local_time:%Y-%m-%d %H:%M}")
        else:
            lines.append("Last landing: none yet")
        return tuple(lines)
