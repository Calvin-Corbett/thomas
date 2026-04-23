from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def default_state_dir() -> Path:
    env = os.getenv("THOMAS_STATE_DIR") or os.getenv("THOMAS_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".thomas").resolve()


@dataclass
class IntakeServerConfig:
    token: str = ""
    max_bytes: int = 8 * 1024 * 1024
    dedupe_window_s: float = 120.0

    @staticmethod
    def from_env() -> IntakeServerConfig:
        token = os.getenv("THOMAS_INTAKE_TOKEN", "").strip()
        max_bytes = int(os.getenv("THOMAS_INTAKE_MAX_BYTES", str(8 * 1024 * 1024)))
        dedupe_window_s = float(os.getenv("THOMAS_INTAKE_DEDUPE_WINDOW_S", "120"))
        return IntakeServerConfig(token=token, max_bytes=max_bytes, dedupe_window_s=dedupe_window_s)


@dataclass
class IntakeStorageConfig:
    base_dir: Path

    @staticmethod
    def from_env() -> IntakeStorageConfig:
        return IntakeStorageConfig(base_dir=default_state_dir() / "intake")


@dataclass
class ClientConfig:
    server: str = "http://localhost:8000"
    token: str = ""
    send_text: bool = True
    send_images: bool = True
    screenshot_mode: str = "region"  # region|fullscreen
    poll_interval_s: float = 0.6  # used only in polling fallback
    request_timeout_s: float = 15.0
    active_chat_id: str = ""
    ocr_lang: str = "eng"
    tesseract_cmd: str = ""

    @staticmethod
    def path() -> Path:
        return default_state_dir() / "intake_client.json"

    @staticmethod
    def load() -> ClientConfig:
        p = ClientConfig.path()
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                return ClientConfig(**data)
        except json.JSONDecodeError:
            pass
        return ClientConfig()

    def save(self) -> None:
        p = ClientConfig.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.active_chat_id:
            h["X-Thomas-Chat-Id"] = self.active_chat_id
        return h
