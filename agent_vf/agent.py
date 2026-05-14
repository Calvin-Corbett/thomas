from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent_vf.config import AppConfig
from agent_vf.llm_client import LLMError, OpenAICompatClient
from agent_vf.memory_engine import AgentMemoryApp
from agent_vf.tools.base import ToolRegistry

SYSTEM_CORE = """You are a local-first autonomous assistant.
Rules:
- Do not ask many questions unless blocked.
- Use tools when needed.
- Respect mode: fast, deep, learning, auto, no_memory.
"""

def _pick_mode(cfg_mode: str, user_text: str) -> str:
    if cfg_mode != "auto":
        return cfg_mode
    t = user_text.lower()
    deep_triggers = ("remember", "earlier", "last time", "previous", "plan", "design", "architecture", "spec", "prove", "cite", "exactly", "build")
    return "deep" if any(x in t for x in deep_triggers) else "fast"

@dataclass
class Agent:
    cfg: AppConfig
    tools: ToolRegistry
    llm: OpenAICompatClient
    memory: AgentMemoryApp

    def close(self):
        self.memory.close()

    def _tool_dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        t = self.tools.get(name)
        if not t:
            return {"ok": False, "error": "unknown_tool"}
        try:
            return t.handler(args)
        except Exception as e:
            return {"ok": False, "error": "tool_exception", "detail": str(e)}

    def chat(self, user_text: str) -> str:
        mode = _pick_mode(self.cfg.mode, user_text)
        self.memory.log_event(thread=self.cfg.thread, etype="user", text=user_text)

        packed = ""
        if mode != "no_memory":
            packed = self.memory.query(thread=self.cfg.thread, mode=mode, text=user_text).get("packed","")

        system = SYSTEM_CORE + "\n\nMEMORY CONTEXT:\n" + (packed if packed else "(none)")
        tools_spec = self.tools.openai_tool_specs()
        messages: list[dict[str, Any]] = [
            {"role":"system","content":system},
            {"role":"user","content":user_text},
        ]

        for _ in range(6):
            try:
                out = self.llm.chat(messages, tools=tools_spec)
            except LLMError as e:
                self.memory.log_event(thread=self.cfg.thread, etype="assistant", text=f"LLM_ERROR: {e}")
                raise
            msg = out["choices"][0]["message"]
            if msg.get("tool_calls"):
                messages.append({"role":"assistant","content":msg.get("content") or ""})
                for tc in msg["tool_calls"]:
                    fn = tc["function"]["name"]
                    args = json.loads(tc["function"].get("arguments","{}") or "{}")
                    res = self._tool_dispatch(fn, args)
                    messages.append({"role":"tool","tool_call_id":tc["id"],"content":json.dumps(res, ensure_ascii=False)})
                continue
            text = msg.get("content") or ""
            self.memory.log_event(thread=self.cfg.thread, etype="assistant", text=text)
            return text

        text = "Tool loop hit the step budget before completion."
        self.memory.log_event(thread=self.cfg.thread, etype="assistant", text=text)
        return text
