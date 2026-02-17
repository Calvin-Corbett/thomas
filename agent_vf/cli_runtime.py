from __future__ import annotations
import os
from pathlib import Path

from agent_vf.config import AppConfig
from agent_vf.llm_client import OpenAICompatClient
from agent_vf.tools.base import ToolRegistry
from agent_vf.tools import fs_tools, web_tools, playwright_tool
from agent_vf.agent import Agent
from agent_vf.memory_engine import AgentMemoryApp

def build_agent(root: str="./runtime") -> Agent:
    cfg = AppConfig(root=Path(root))
    cfg.thread = os.getenv("AGENT_THREAD", cfg.thread)
    cfg.mode = os.getenv("AGENT_MODE", cfg.mode)
    cfg.safety["fs_root"] = os.getenv("AGENT_FS_ROOT", cfg.safety["fs_root"])
    cfg.safety["deny_network"] = os.getenv("AGENT_DENY_NETWORK","false").lower() in ("1","true","yes")
    cfg.llm.base_url = os.getenv("AGENT_LLM_BASE_URL", cfg.llm.base_url)
    cfg.llm.api_key = os.getenv("AGENT_LLM_API_KEY", cfg.llm.api_key)
    cfg.llm.model = os.getenv("AGENT_LLM_MODEL", cfg.llm.model)

    reg = ToolRegistry()
    fs_tools.register(reg, cfg.safety["fs_root"])
    web_tools.register(reg, deny_network=bool(cfg.safety["deny_network"]))
    playwright_tool.register(reg)

    mem = AgentMemoryApp(cfg.root)
    llm = OpenAICompatClient(cfg.llm)
    return Agent(cfg=cfg, tools=reg, llm=llm, memory=mem)
