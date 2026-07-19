"""Small fail-closed HTTP contracts shared by the directed Code routes."""

from __future__ import annotations

import logging
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.server.app_keys import APP_SECRETS
from thomas.server.openai_codex_oauth import OpenAICodexOAuthError, ensure_openai_codex_access_token

log = logging.getLogger(__name__)

_HTML_LOCAL_REF = re.compile(r"(?:src|href)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_CSS_LOCAL_REF = re.compile(r"url\(\s*['\"]?([^)'\"]+)", re.IGNORECASE)
_CSS_IMPORT_REF = re.compile(r"@import\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)
_JS_LOCAL_REF = re.compile(
    r"(?:\bfrom\s+|\bimport\s*(?:\(\s*)?|\bfetch\s*\(\s*|"
    r"\bnew\s+(?:Shared)?Worker\s*\(\s*)['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def chatgpt_auth_unavailable_response() -> web.Response:
    """Return the stable public failure contract without exposing OAuth detail."""
    return web.json_response(
        {
            "ok": False,
            "error": "ChatGPT authentication is temporarily unavailable. Retry or reconnect in Easy Setup.",
            "code": "chatgpt_auth_unavailable",
            "retryable": True,
        },
        status=503,
    )


async def prepare_code_oauth_credential(app: web.Application, family: str) -> tuple[str, web.Response | None]:
    """Resolve the one-run OAuth credential without exposing it in argv or env."""
    if family != "gpt":
        return "", None
    try:
        secret_store = app.get(APP_SECRETS)
        token = (
            await ensure_openai_codex_access_token("openai_codex", secret_store=secret_store)
            if secret_store is not None
            else ""
        )
    except (OpenAICodexOAuthError, OSError, TypeError, ValueError):
        log.info("Code could not prepare the ChatGPT OAuth credential")
        return "", chatgpt_auth_unavailable_response()
    if not token:
        return "", chatgpt_auth_unavailable_response()
    return token, None


def git_status_unavailable_response(exc: forge_code_git.ForgeCodeGitError) -> web.Response:
    """Keep missing Git proof distinct from an honestly clean workspace."""
    return web.json_response(
        {"ok": False, "error": str(exc), "code": "git_status_unavailable", "retryable": True},
        status=503,
    )


def validate_active_run_request(body: object, session: object) -> web.Response | None:
    """Reject missing or stale control commands before they can stop another run."""
    requested = str((body if isinstance(body, dict) else {}).get("run_id") or "").strip()
    active = str((session if isinstance(session, dict) else {}).get("run_id") or "").strip()
    if not requested:
        return web.json_response({"ok": False, "error": "run_id is required", "code": "run_id_required"}, status=400)
    if not active or requested != active:
        return web.json_response(
            {"ok": False, "error": "that Code run is not active", "code": "run_not_active"}, status=409
        )
    return None


def conversation_artifact_allowlist(root: Path, conversation: object) -> set[str]:
    """Allow result files plus local dependencies explicitly referenced by them."""
    turns = conversation.get("turns") if isinstance(conversation, dict) else []
    changed = {
        str(file or "").replace("\\", "/")
        for turn in (turns if isinstance(turns, list) else [])
        if isinstance(turn, dict)
        for file in (turn.get("changed_files") or [])
        if str(file or "").strip()
    }
    allowed = {str(item["file"]) for item in forge_code_store.detect_artifacts(sorted(changed))}
    pending = list(allowed)
    while pending:
        rel = pending.pop()
        suffix = Path(rel).suffix.lower()
        if suffix not in {".html", ".htm", ".css", ".js", ".mjs", ".cjs"}:
            continue
        target = (root / rel).resolve()
        if not target.is_file() or not target.is_relative_to(root.resolve()):
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")[:1_000_000]
        except OSError:
            continue
        if suffix == ".css":
            refs = _CSS_LOCAL_REF.findall(text) + _CSS_IMPORT_REF.findall(text)
        elif suffix in {".js", ".mjs", ".cjs"}:
            refs = _JS_LOCAL_REF.findall(text)
        else:
            refs = _HTML_LOCAL_REF.findall(text)
        for raw in refs:
            parsed = urlsplit(str(raw).strip())
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            dependency = (
                posixpath.normpath(parsed.path.lstrip("/"))
                if parsed.path.startswith("/")
                else posixpath.normpath(posixpath.join(posixpath.dirname(rel), parsed.path))
            )
            if dependency.startswith("../") or dependency not in changed or dependency in allowed:
                continue
            allowed.add(dependency)
            pending.append(dependency)
    return allowed
