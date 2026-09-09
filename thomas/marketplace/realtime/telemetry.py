from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Telemetry:
    # Basic timeline markers (ms)
    hello_ms: int = 0
    last_user_submit_ms: int = 0
    first_assistant_delta_ms: int = 0
    assistant_done_ms: int = 0
    last_stt_final_ms: int = 0

    # Rolling counters
    ws_pings: int = 0
    ws_pongs: int = 0
    stt_duplicates_suppressed: int = 0
    interruptions: int = 0
    errors: int = 0

    # Optional usage
    tokens_in: int = 0
    tokens_out: int = 0

    # Current mode
    mode: str = "balanced"

    # arbitrary latest values
    last_rtt_ms: int = 0
    last_stt_latency_ms: int = 0
    last_first_token_latency_ms: int = 0

    def mark_hello(self):
        self.hello_ms = now_ms()

    def mark_user_submit(self):
        self.last_user_submit_ms = now_ms()
        self.first_assistant_delta_ms = 0
        self.assistant_done_ms = 0
        self.last_first_token_latency_ms = 0

    def mark_assistant_delta(self):
        if not self.first_assistant_delta_ms:
            self.first_assistant_delta_ms = now_ms()
            if self.last_user_submit_ms:
                self.last_first_token_latency_ms = self.first_assistant_delta_ms - self.last_user_submit_ms

    def mark_assistant_done(self):
        self.assistant_done_ms = now_ms()

    def mark_stt_final(self):
        self.last_stt_final_ms = now_ms()

    def set_rtt(self, ms: int):
        self.last_rtt_ms = ms

    def set_stt_latency(self, ms: int):
        self.last_stt_latency_ms = ms

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
