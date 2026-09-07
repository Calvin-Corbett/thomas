"""Regressions for the remaining 2026-06-03 latent-surface hardening.

These checks cover the live HTTP-client SSRF guard and chat-log redaction.
"""

from __future__ import annotations

import asyncio


def test_http_client_refuses_cloud_metadata_endpoint() -> None:
    from thomas.tools.http_client import HttpClientTool

    tool = HttpClientTool()
    result = asyncio.run(tool.request("GET", "http://169.254.169.254/latest/meta-data/"))
    assert result.ok is False
    assert "SSRF" in (result.error or "")


def test_chat_logger_redacts_secrets_before_disk(tmp_path) -> None:
    from thomas.chat_logger import ChatLogger

    logger = ChatLogger()
    logger.configure(log_dir=str(tmp_path), enabled=True)
    logger.set_session("sess-1")
    logger.log_event("tool_call", {"api_key": "sk-DEADBEEFsecrettoken12345", "note": "keepme"})
    logger.flush()

    files = list(tmp_path.glob("chat_*.jsonl"))
    assert files, "no chat log written"
    text = files[0].read_text(encoding="utf-8")
    assert "sk-DEADBEEFsecrettoken12345" not in text  # secret masked
    assert "keepme" in text  # non-secret field survives
