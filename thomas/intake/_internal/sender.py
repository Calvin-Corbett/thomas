from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict

import requests


@dataclass
class SendJob:
    url: str
    json_payload: Dict[str, Any]
    headers: Dict[str, str]
    timeout_s: float


class SenderQueue:
    """Background sender with retry/backoff.

    Keeps UI responsive and improves reliability during transient server/network outages.
    """

    def __init__(self, maxsize: int = 400):
        self.q: "queue.Queue[SendJob]" = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._worker, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def submit(self, job: SendJob) -> bool:
        try:
            self.q.put_nowait(job)
            return True
        except queue.Full:
            return False

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.q.get(timeout=0.2)
            except queue.Empty:
                continue

            backoff = 0.5
            for _ in range(7):
                try:
                    r = requests.post(job.url, json=job.json_payload, headers=job.headers, timeout=job.timeout_s)
                    r.raise_for_status()
                    try:
                        data = r.json()
                        summary = data.get("summary", "")
                        action = data.get("action_suggestion", "")
                        if summary or action:
                            print("\n[Thomas] Summary:", summary)
                            print("[Thomas] Suggestion:", action)
                    except Exception:
                        pass
                    break
                except Exception:
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, 10.0)

            self.q.task_done()
