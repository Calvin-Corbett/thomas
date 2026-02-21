"""Telegram bot integration for Thomas.

Runs a polling bot that forwards chat messages into Thomas's agent loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.core.token_economy import normalize_token_economy_level
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

_TELEGRAM_MSG_LIMIT = 4096
_SESSION_HISTORY_LIMIT = 120


def parse_allowed_chat_ids(raw: Optional[str]) -> set[int]:
    """Parse a comma/semicolon-separated allowlist into chat ids."""
    out: set[int] = set()
    if not raw:
        return out

    for chunk in str(raw).replace(";", ",").split(","):
        s = chunk.strip()
        if not s:
            continue
        try:
            out.add(int(s))
        except ValueError:
            log.warning("Ignoring invalid Telegram chat id: %r", s)
    return out


def parse_telegram_command(text: str) -> Optional[tuple[str, str]]:
    """Return normalized command + args, or None if this is not a slash command."""
    s = str(text or "").strip()
    if not s.startswith("/"):
        return None

    head, _, tail = s.partition(" ")
    if head == "/":
        return None
    # Telegram may send commands as /cmd@bot_name in group chats.
    cmd = head.split("@", 1)[0].lower()
    return cmd, tail.strip()


def split_telegram_text(text: str, *, max_len: int = _TELEGRAM_MSG_LIMIT) -> list[str]:
    """Split long text into Telegram-sized chunks, preferring newline boundaries."""
    if max_len < 64:
        raise ValueError("max_len must be >= 64")
    payload = str(text or "")
    if len(payload) <= max_len:
        return [payload]

    out: list[str] = []
    start = 0
    n = len(payload)
    while start < n:
        end = min(start + max_len, n)
        if end >= n:
            out.append(payload[start:n])
            break

        split_at = payload.rfind("\n", start, end)
        if split_at <= start:
            split_at = end
        else:
            split_at += 1  # Keep the newline in this chunk.

        out.append(payload[start:split_at])
        start = split_at
    return out


@dataclass
class _TelegramSession:
    conversation: list[dict[str, Any]] = field(default_factory=list)
    model_name: str = "local"


def default_sessions_path(config: AppConfig) -> Path:
    """Default on-disk path for persisted Telegram sessions."""
    return config.memory.root_path / ".thomas" / "telegram_sessions.json"


def _sanitize_conversation(data: Any, *, max_messages: int = _SESSION_HISTORY_LIMIT) -> list[dict[str, Any]]:
    """Normalize external conversation payloads to assistant/user text messages."""
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data[-max_messages:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in ("system", "user", "assistant", "tool"):
            continue
        content = item.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
    return out


def load_sessions(path: Path, *, default_model: str) -> Dict[int, _TelegramSession]:
    """Load Telegram chat sessions from disk."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    sessions_obj = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(sessions_obj, dict):
        return {}

    out: Dict[int, _TelegramSession] = {}
    for key, value in sessions_obj.items():
        try:
            chat_id = int(str(key).strip())
        except ValueError:
            continue

        entry = value if isinstance(value, dict) else {}
        model_name = str(entry.get("model_name") or default_model).strip() or default_model
        conversation = _sanitize_conversation(entry.get("conversation"))
        out[chat_id] = _TelegramSession(conversation=conversation, model_name=model_name)
    return out


def save_sessions(path: Path, sessions: Dict[int, _TelegramSession]) -> None:
    """Persist Telegram chat sessions atomically."""
    payload = {
        "version": 1,
        "sessions": {
            str(chat_id): {
                "model_name": sess.model_name,
                "conversation": _sanitize_conversation(sess.conversation),
            }
            for chat_id, sess in sessions.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class TelegramBridge:
    """Per-chat state bridge from Telegram to the Thomas agent loop."""

    def __init__(
        self,
        *,
        config: AppConfig,
        tools: ToolRegistry,
        memory: Optional[Any],
        default_model: str,
        allowed_chat_ids: Optional[set[int]] = None,
        sessions_path: Optional[Path] = None,
        shared_memory: bool = False,
        shared_memory_thread: str = "telegram:global",
        memory_retrieval_scope: str = "thread",
        include_global_memory: bool = True,
        include_profile_memory: bool = True,
    ) -> None:
        self._config = config
        self._tools = tools
        self._memory = memory
        self._default_model = default_model
        self._allowed_chat_ids = set(allowed_chat_ids or set())
        self._sessions_path = sessions_path
        self._shared_memory = bool(shared_memory)
        self._shared_memory_thread = str(shared_memory_thread or "telegram:global").strip() or "telegram:global"
        scope = str(memory_retrieval_scope or "thread").strip().lower()
        if scope == "all":
            # Raw all-thread recall causes memory contamination across channels.
            # Keep retrieval thread-scoped and use explicit global/profile signals.
            scope = "thread"
        self._memory_retrieval_scope = scope if scope in ("thread", "all") else "thread"
        self._include_global_memory = bool(include_global_memory)
        self._include_profile_memory = bool(include_profile_memory)
        self._sessions: Dict[int, _TelegramSession] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

        if self._sessions_path is not None:
            try:
                self._sessions = load_sessions(self._sessions_path, default_model=self._default_model)
            except Exception as e:
                log.warning("Failed to load Telegram session store (%s): %s", self._sessions_path, e)
                self._sessions = {}

    @property
    def default_model(self) -> str:
        return self._default_model

    def _is_allowed_chat(self, chat_id: int) -> bool:
        return (not self._allowed_chat_ids) or (chat_id in self._allowed_chat_ids)

    def _get_session(self, chat_id: int) -> _TelegramSession:
        session = self._sessions.get(chat_id)
        if session is None:
            session = _TelegramSession(model_name=self._default_model)
            self._sessions[chat_id] = session
        return session

    def _get_lock(self, chat_id: int) -> asyncio.Lock:
        lock = self._locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chat_id] = lock
        return lock

    def _thread_id_for_chat(self, chat_id: int) -> str:
        if self._shared_memory:
            return self._shared_memory_thread
        return f"telegram:{chat_id}"

    def _help_text(self, model_name: str) -> str:
        available = ", ".join(self._config.models.keys())
        memory_mode = (
            f"shared ({self._shared_memory_thread})" if self._shared_memory else "per-chat"
        )
        retrieval_mode = "this chat thread only"
        if self._include_global_memory:
            retrieval_mode += " + global facts"
        if self._include_profile_memory:
            retrieval_mode += " + profile hints"
        return (
            "Thomas Telegram bridge\n"
            "\n"
            "Commands:\n"
            "/help - Show this help\n"
            "/reset - Clear this chat's conversation memory\n"
            "/model - Show current model and available profiles\n"
            "/model <profile> - Switch this chat to a model profile\n"
            "\n"
            f"Current model: {model_name}\n"
            f"Memory mode: {memory_mode}\n"
            f"Memory retrieval: {retrieval_mode}\n"
            f"Available models: {available}"
        )

    def _apply_thread_memory_policy(self, thread_id: str) -> None:
        mem = self._memory
        if mem is None:
            return
        setter = getattr(mem, "set_thread_memory_policy", None)
        if not callable(setter):
            return
        try:
            setter(
                thread_id,
                enabled=True,
                include_global=self._include_global_memory,
                include_profile=self._include_profile_memory,
                pins_only=False,
            )
        except Exception as e:
            log.debug("Failed to apply Telegram thread memory policy for %s: %s", thread_id, e)

    def _save_sessions(self) -> None:
        if self._sessions_path is None:
            return
        try:
            save_sessions(self._sessions_path, self._sessions)
        except Exception as e:
            log.warning("Failed to save Telegram session store (%s): %s", self._sessions_path, e)

    async def _run_agent(self, *, chat_id: int, session: _TelegramSession, prompt: str) -> str:
        model_cfg = self._config.get_model(session.model_name)
        llm = LLMClient(
            model_cfg,
            fallback_configs=self._config.failover_chain(session.model_name),
            failover_enabled=self._config.failover.enabled,
            failover_cooldown_s=self._config.failover.cooldown_seconds,
            failover_on_auth_error=self._config.failover.fallback_on_auth_error,
        )
        thread_id = self._thread_id_for_chat(chat_id)
        self._apply_thread_memory_policy(thread_id)
        agent = AgentLoop(
            self._config,
            llm,
            self._tools,
            conversation=session.conversation,
            memory=self._memory,
            thread_id=thread_id,
            memory_retrieval_scope=self._memory_retrieval_scope,
        )

        deltas: list[str] = []
        done_text = ""
        error_text = ""
        try:
            token_economy = normalize_token_economy_level(
                os.environ.get("THOMAS_TOKEN_ECONOMY", "optimal")
            )
            async for event in agent.run(prompt, token_economy=token_economy):
                if event.type == EventType.TEXT_DELTA:
                    delta = str(event.data.get("text") or "")
                    if delta:
                        deltas.append(delta)
                elif event.type == EventType.AGENT_DONE:
                    done_text = str(event.data.get("text") or "")
                elif event.type == EventType.AGENT_ERROR:
                    error_text = str(event.data.get("error") or "unknown error")
        finally:
            await llm.close()

        if error_text:
            return f"Error: {error_text}"

        text = "".join(deltas).strip() or done_text.strip()
        if not text:
            return "I could not generate a response for that message."
        return text

    async def handle_text(self, *, chat_id: int, text: str) -> str:
        if not self._is_allowed_chat(chat_id):
            raise PermissionError(f"chat {chat_id} is not allowlisted")

        lock = self._get_lock(chat_id)
        async with lock:
            session = self._get_session(chat_id)
            cmd = parse_telegram_command(text)
            if cmd is not None:
                name, arg = cmd
                if name in ("/start", "/help"):
                    return self._help_text(session.model_name)
                if name == "/reset":
                    session.conversation.clear()
                    self._save_sessions()
                    return "Conversation cleared for this chat."
                if name == "/model":
                    if not arg:
                        available = ", ".join(self._config.models.keys())
                        return f"Current model: {session.model_name}\nAvailable models: {available}"
                    if arg not in self._config.models:
                        available = ", ".join(self._config.models.keys())
                        return f"Unknown model profile '{arg}'. Available: {available}"
                    session.model_name = arg
                    self._save_sessions()
                    return f"Switched this chat to model profile: {arg}"
                return "Unknown command. Use /help for supported commands."

            prompt = str(text or "").strip()
            if not prompt:
                return "Send a message, or use /help."
            reply = await self._run_agent(chat_id=chat_id, session=session, prompt=prompt)
            self._save_sessions()
            return reply


def run_telegram_polling(
    config: AppConfig,
    *,
    token: str,
    tools: ToolRegistry,
    memory: Optional[Any] = None,
    model_name: Optional[str] = None,
    allowed_chat_ids: Optional[set[int]] = None,
    sessions_path: Optional[Path] = None,
    shared_memory: bool = False,
    shared_memory_thread: str = "telegram:global",
    memory_retrieval_scope: str = "thread",
    include_global_memory: bool = True,
    include_profile_memory: bool = True,
) -> None:
    """Run the Telegram bot using long polling."""
    chosen_model = str(model_name or config.default_model).strip()
    if not chosen_model:
        raise ValueError("model_name must not be empty")
    if chosen_model not in config.models:
        available = ", ".join(config.models.keys())
        raise KeyError(f"Unknown model '{chosen_model}'. Available: {available}")
    if not str(token or "").strip():
        raise ValueError("Telegram token is required")

    try:
        from telegram.ext import Application, MessageHandler, filters
    except ImportError as e:
        raise RuntimeError(
            "Telegram integration requires python-telegram-bot. "
            "Install with: pip install -e \".[telegram]\""
        ) from e

    bridge = TelegramBridge(
        config=config,
        tools=tools,
        memory=memory,
        default_model=chosen_model,
        allowed_chat_ids=allowed_chat_ids,
        sessions_path=sessions_path,
        shared_memory=shared_memory,
        shared_memory_thread=shared_memory_thread,
        memory_retrieval_scope=memory_retrieval_scope,
        include_global_memory=include_global_memory,
        include_profile_memory=include_profile_memory,
    )

    async def _on_text(update, _context) -> None:  # type: ignore[no-untyped-def]
        msg = update.effective_message
        chat = update.effective_chat
        if msg is None or chat is None:
            return
        raw_text = getattr(msg, "text", None)
        if not isinstance(raw_text, str):
            return

        cid = int(chat.id)
        try:
            reply = await bridge.handle_text(chat_id=cid, text=raw_text)
        except PermissionError:
            log.warning("Ignoring message from non-allowlisted chat id: %s", cid)
            return
        except Exception as e:
            log.exception("Telegram message handling failed: %s", e)
            try:
                await msg.reply_text("Sorry, I hit an internal error while handling that message.")
            except Exception as send_err:
                log.debug("Failed to send Telegram error message: %s", send_err)
            return

        for part in split_telegram_text(reply):
            await msg.reply_text(part, disable_web_page_preview=True)

    app = Application.builder().token(str(token).strip()).build()
    # Route all text through one handler so slash commands can be processed with
    # per-chat model/session state.
    app.add_handler(MessageHandler(filters.TEXT, _on_text))

    log.info(
        "Starting Telegram bot polling (model=%s, allowlist=%s, shared_memory=%s, retrieval=%s, global=%s, profile=%s, sessions=%s)",
        bridge.default_model,
        sorted(bridge._allowed_chat_ids) if bridge._allowed_chat_ids else "ALL",
        bridge._shared_memory_thread if bridge._shared_memory else "disabled",
        bridge._memory_retrieval_scope,
        bridge._include_global_memory,
        bridge._include_profile_memory,
        str(sessions_path) if sessions_path is not None else "disabled",
    )
    app.run_polling()
