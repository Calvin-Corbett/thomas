from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .ingest import WatcherConfig, load_watcher_config

router = APIRouter(tags=["watcher"])


class StatusResponse(BaseModel):
    running: bool
    enabled: bool
    recursive: bool
    paths: list[str]
    queue_depth: int
    processed: int
    skipped: int
    failed: int
    last_event_path: str | None = None
    last_error: str | None = None
    config: dict


class PathsRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)
    persist: bool = True


def _config_path() -> str:
    return os.environ.get("THOMAS_CONFIG_PATH") or "thomas.toml"


def _toml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_paths_multiline(paths: list[str]) -> str:
    if not paths:
        return "paths = []\n"
    inner = ",\n  ".join(_toml_quote(p) for p in paths)
    return "paths = [\n  " + inner + "\n]\n"


def patch_watcher_section(toml_text: str, cfg: WatcherConfig) -> str:
    """
    Patch (or append) [watcher] section.
    Updates only watcher keys managed by WatcherConfig, preserving unknown keys where possible.
    """
    lines = toml_text.splitlines(keepends=True)
    section_re = re.compile(r"^\s*\[watcher\]\s*$")
    any_section_re = re.compile(r"^\s*\[.*\]\s*$")

    start = None
    for i, line in enumerate(lines):
        if section_re.match(line.strip()):
            start = i
            break

    def render_cfg(c: WatcherConfig) -> str:
        out = ""
        out += f"enabled = {'true' if c.enabled else 'false'}\n"
        out += f"recursive = {'true' if c.recursive else 'false'}\n"
        out += _render_paths_multiline(c.paths)
        out += f"max_file_size_mb = {int(c.max_file_size_mb)}\n"
        out += f"max_hash_bytes_mb = {int(c.max_hash_bytes_mb)}\n"
        out += f"read_retry_attempts = {int(c.read_retry_attempts)}\n"
        out += f"read_retry_sleep_ms = {int(c.read_retry_sleep_ms)}\n"
        out += f"ocr_lang = {_toml_quote(str(c.ocr_lang))}\n"
        out += f"dedupe = {'true' if c.dedupe else 'false'}\n"
        out += f"dedupe_ttl_seconds = {int(c.dedupe_ttl_seconds)}\n"
        out += "ignore_suffixes = [" + ", ".join(_toml_quote(x) for x in c.ignore_suffixes) + "]\n"
        out += "ignore_prefixes = [" + ", ".join(_toml_quote(x) for x in c.ignore_prefixes) + "]\n"
        out += "ignore_globs = [" + ", ".join(_toml_quote(x) for x in c.ignore_globs) + "]\n"
        out += f"worker_threads = {int(c.worker_threads)}\n"
        if c.include_exts:
            out += "include_exts = [" + ", ".join(_toml_quote(x) for x in c.include_exts) + "]\n"
        return out

    managed = {
        "enabled",
        "recursive",
        "paths",
        "max_file_size_mb",
        "max_hash_bytes_mb",
        "read_retry_attempts",
        "read_retry_sleep_ms",
        "ocr_lang",
        "dedupe",
        "dedupe_ttl_seconds",
        "ignore_suffixes",
        "ignore_prefixes",
        "ignore_globs",
        "worker_threads",
        "include_exts",
    }

    if start is None:
        suffix = "" if toml_text.endswith("\n") else "\n"
        return toml_text + suffix + "\n[watcher]\n" + render_cfg(cfg)

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if any_section_re.match(lines[j].strip()):
            end = j
            break

    watcher_block = lines[start:end]

    key_re = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")

    out_block: list[str] = [watcher_block[0]]
    # Always write managed keys at the top; then keep unknown lines from the old block.
    out_block.append(render_cfg(cfg))

    i = 1
    while i < len(watcher_block):
        line = watcher_block[i]
        m = key_re.match(line)
        if m:
            key = m.group(1)
            if key in managed:
                # Skip old managed key lines. For paths (multiline), skip until ']' is found.
                if key == "paths":
                    if "]" in line:
                        i += 1
                        continue
                    i += 1
                    while i < len(watcher_block) and "]" not in watcher_block[i]:
                        i += 1
                    if i < len(watcher_block):
                        i += 1
                    continue
                i += 1
                continue
        out_block.append(line)
        i += 1

    new_lines = lines[:start] + out_block + lines[end:]
    return "".join(new_lines)


def persist_config(cfg: WatcherConfig, config_path: str | None = None) -> None:
    cp = Path(config_path or _config_path())
    existing = cp.read_text(encoding="utf-8", errors="replace") if cp.exists() else ""
    patched = patch_watcher_section(existing, cfg)
    cp.write_text(patched, encoding="utf-8")


def _get_watcher_service(*, notifier=None, config_path: str):
    from .watcher import get_watcher_service as _factory

    return _factory(notifier=notifier, config_path=config_path)


def _get_notifier_from_app(request: Request):
    fn = getattr(getattr(request.app, "state", object()), "watcher_notifier", None)
    return fn if callable(fn) else None


@router.get("/api/watcher/status", response_model=StatusResponse)
def watcher_status(request: Request):
    svc = _get_watcher_service(notifier=_get_notifier_from_app(request), config_path=_config_path())
    return svc.status().to_dict()


@router.post("/api/watcher/paths", response_model=StatusResponse)
def watcher_paths(req: PathsRequest, request: Request):
    normalized: list[str] = []
    for p in req.paths:
        if not p:
            continue
        ap = str(Path(p).expanduser().resolve())
        if not Path(ap).exists() or not Path(ap).is_dir():
            raise HTTPException(status_code=400, detail=f"Not a directory: {p}")
        normalized.append(ap)

    cfg = load_watcher_config(config_path=_config_path())
    cfg.paths = normalized

    if req.persist:
        persist_config(cfg, config_path=_config_path())

    svc = _get_watcher_service(notifier=_get_notifier_from_app(request), config_path=_config_path())
    svc.apply_config(cfg)
    if cfg.enabled:
        svc.start()
    else:
        svc.stop()

    return svc.status().to_dict()


def bind_watcher_lifecycle(app: FastAPI) -> None:
    """
    Starts/stops watcher with the server.
    Uses FastAPI startup/shutdown hooks for broad compatibility.
    """

    @app.on_event("startup")
    def _startup():
        svc = _get_watcher_service(config_path=_config_path())
        svc.reload_config()
        if svc.status().enabled:
            svc.start()

    @app.on_event("shutdown")
    def _shutdown():
        svc = _get_watcher_service(config_path=_config_path())
        svc.stop()
