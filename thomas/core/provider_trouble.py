"""Recognise provider-side failures and group them into per-provider episodes.

This module only classifies failures; callers decide whether to switch or wait.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from thomas.core.provider_limits import read_limit

_OVERLOAD = re.compile(
    r"\boverloaded\b|\bover capacity\b|\bhigh demand\b|\bserver_is_overloaded\b|\boverloaded_error\b", re.I
)
_DISCONNECT = re.compile(
    r"\b(?:ChatGPT/Codex|Codex) (?:text )?stream disconnected\b"
    r"|\b(?:connection|model stream|provider stream) (?:dropped|lost|reset|closed|disconnected)\b"
    r"|\bconnection (?:reset|aborted) by peer\b",
    re.I,
)
_LOGIN = re.compile(
    r"\binvalidated oauth\b|\bnot logged in\b|\bplease run /login\b"
    r"|\b(?:sign[ -]?in|login|(?:access|auth|oauth) token|session) (?:has )?expired\b",
    re.I,
)
_HTTP = re.compile(r"\bHTTP (\d{3})\b", re.I)
_LOCAL = re.compile(r"\b(?:localhost|127\.\d+\.\d+\.\d+|loopback)\b|(?<![\w:])::1(?![\w:])", re.I)
_NETWORK = re.compile(r"\b(?:connection|connect|proxy|network|refused|unreachable|timeout|timed out)\b", re.I)
_PLAN_WORDS = re.compile(
    r"\b(?:usage limit reached|you've hit your (?:session|usage) limit|you're out of usage credits)\b", re.I
)
_EVIDENCE_LENGTH = 160
_CHAT_WINDOW = 600
_IDLE_WINDOW = 1200
_REOPEN_WINDOW = 600


@dataclass(frozen=True)
class Trouble:
    """A recognised provider failure and a short excerpt from its cause."""

    kind: str
    evidence: str


def classify(text: str, status: int | None = None) -> Trouble | None:
    """Return provider trouble, excluding local connectivity and short 429 bursts."""
    detail = str(text or "")
    code = status if status is not None else next((int(value) for value in _HTTP.findall(detail)), None)
    # A loopback connection failure cannot be fixed by changing the provider.
    if _LOCAL.search(detail) and _NETWORK.search(detail):
        return None
    if (
        "proxy" in detail.lower()
        and _NETWORK.search(detail)
        and re.search(
            r"\b(?:down|failed|failure|refused|unreachable|cannot connect|could not connect|timed out|connection error)\b",
            detail,
            re.I,
        )
    ):
        return None

    kind = None
    if code == 529 or _OVERLOAD.search(detail):
        kind = "overloaded"
    else:
        # The shared reader needs an HTTP marker. Supply it for a caller that
        # already extracted the status, without interpreting a bare 429 as a limit.
        limit_text = detail if _HTTP.search(detail) else f"HTTP {code} {detail}" if code is not None else detail
        limit = read_limit(limit_text, at=time.time())
        if (limit is not None and limit.is_account_limit(time.time())) or (code == 429 and _PLAN_WORDS.search(detail)):
            kind = "plan_limit"
        elif code in (401, 403) or _LOGIN.search(detail):
            kind = "signed_out"
        elif code in (500, 502, 503, 504) or _DISCONNECT.search(detail):
            kind = "server_error"
    if kind is None:
        return None
    excerpt = " ".join(detail.split())[:_EVIDENCE_LENGTH]
    return Trouble(kind, excerpt or f"HTTP {code}")


@dataclass
class Episode:
    """One provider outage, including its last failure and optional close time."""

    id: str
    provider: str
    trouble: Trouble
    opened_at: float
    last_failure_at: float
    closed_at: float | None = None


class EpisodeTracker:
    """Track independent provider episodes using an injectable Unix-seconds clock."""

    def __init__(self, *, clock: Callable[[], float], path: str | Path | None = None) -> None:
        self.clock = clock
        self.path = Path(path) if path is not None else None
        self._open: dict[str, Episode] = {}
        self._closed: dict[str, Episode] = {}
        self._chat: dict[str, dict[str, float]] = {}

    def _expire(self, now: float) -> None:
        for provider, episode in list(self._open.items()):
            if now - episode.last_failure_at >= _IDLE_WINDOW:
                episode.closed_at = episode.last_failure_at + _IDLE_WINDOW
                self._closed[provider] = self._open.pop(provider)
        for provider, episode in list(self._closed.items()):
            if now - episode.closed_at > _REOPEN_WINDOW:
                del self._closed[provider]
        for provider, requests in list(self._chat.items()):
            self._chat[provider] = {request: at for request, at in requests.items() if now - at <= _CHAT_WINDOW}

    @property
    def open_episodes(self) -> dict[str, Episode]:
        """Current open episodes, after expiring idle ones."""
        self._expire(self.clock())
        return dict(self._open)

    def failure(self, provider: str, surface: str, request_id: str, trouble: Trouble | None) -> Episode | None:
        """Record a failed request; return the episode if one is open."""
        now = self.clock()
        self._expire(now)
        if trouble is None:
            return None
        episode = self._open.get(provider)
        if episode is not None:
            episode.last_failure_at = now
            episode.trouble = trouble
            return episode
        if trouble.kind in ("overloaded", "server_error") and surface.lower() == "chat":
            requests = self._chat.setdefault(provider, {})
            requests.setdefault(request_id, now)
            if len(requests) < 2:
                return None
        self._chat.pop(provider, None)
        episode = self._closed.pop(provider, None)
        if episode is None:
            episode = Episode(uuid4().hex, provider, trouble, now, now)
        else:
            episode.closed_at = None
            episode.trouble = trouble
            episode.last_failure_at = now
        self._open[provider] = episode
        return episode

    def success(self, provider: str) -> None:
        """Close the provider's episode and clear any pending Chat strikes."""
        now = self.clock()
        self._expire(now)
        self._chat.pop(provider, None)
        episode = self._open.pop(provider, None)
        if episode is not None:
            episode.closed_at = now
            self._closed[provider] = episode

    def save(self) -> None:
        """Persist open episodes and recent closures to the configured JSON path."""
        if self.path is None:
            raise ValueError("An episode path is required to save")
        self._expire(self.clock())
        payload = {
            "open": [asdict(episode) for episode in self._open.values()],
            "closed": [asdict(episode) for episode in self._closed.values()],
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def load(self) -> None:
        """Restore saved episodes; stale ones expire against the supplied clock."""
        if self.path is None:
            raise ValueError("An episode path is required to load")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self._open = {
            item["provider"]: Episode(**{**item, "trouble": Trouble(**item["trouble"])})
            for item in payload.get("open", [])
        }
        self._closed = {
            item["provider"]: Episode(**{**item, "trouble": Trouble(**item["trouble"])})
            for item in payload.get("closed", [])
        }
        self._chat.clear()
        self._expire(self.clock())
