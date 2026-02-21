"""Configuration system for Thomas.

Loads from thomas.toml, with environment variable overrides.
Supports model profiles (local, cloud, embed) and per-section config.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import,no-redef]


@dataclass
class ModelConfig:
    """Configuration for a single LLM model profile."""

    name: str
    provider: str = "openai_compat"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    # OpenAI-compatible services vary slightly (Azure, proxies, etc). Keep these
    # configurable so Thomas can talk to many providers without hardcoding.
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    chat_path: str = "/chat/completions"
    models_path: str = "/models"
    extra_headers: Dict[str, str] = field(default_factory=dict)
    query: Dict[str, str] = field(default_factory=dict)
    model: str = "qwen2.5-coder:7b"
    max_tokens: int = 4096
    context_window: int = 8192
    temperature: float = 0.1
    top_p: float = 0.95
    timeout_s: float = 120.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.model:
            errors.append(f"models.{self.name}: model is required")
        if self.temperature < 0 or self.temperature > 2:
            errors.append(f"models.{self.name}: temperature must be 0-2")
        if self.max_tokens < 1:
            errors.append(f"models.{self.name}: max_tokens must be >= 1")
        if self.context_window < 1:
            errors.append(f"models.{self.name}: context_window must be >= 1")
        if self.timeout_s < 1:
            errors.append(f"models.{self.name}: timeout_s must be >= 1")
        if self.chat_path and not self.chat_path.startswith("/"):
            errors.append(f"models.{self.name}: chat_path should start with '/'")
        if self.models_path and not self.models_path.startswith("/"):
            errors.append(f"models.{self.name}: models_path should start with '/'")
        return errors


@dataclass
class EmbedConfig:
    """Configuration for the embedding model."""

    provider: str = "local"
    model: str = "all-MiniLM-L6-v2"
    # "auto" picks CUDA when available, otherwise CPU.
    device: str = "auto"
    load_on_demand: bool = True
    batch_size: int = 64


@dataclass
class MemoryConfig:
    """Configuration for the memory engine."""

    root: str = "./runtime"
    context_budget: int = 12000
    mode: str = "auto"

    @property
    def root_path(self) -> Path:
        return Path(self.root).resolve()


@dataclass
class ToolsConfig:
    """Configuration for the tool system."""

    sandbox_root: str = "."
    # Safe-by-default: shell execution enables arbitrary commands.
    allow_shell: bool = False
    shell_timeout: int = 30
    max_file_size: int = 5_000_000

    @property
    def sandbox_path(self) -> Path:
        return Path(self.sandbox_root).resolve()


@dataclass
class FailoverConfig:
    """Configuration for cross-profile model failover."""

    enabled: bool = True
    # If false, primary chat runs stay pinned to the requested profile/model and
    # do not silently fail over to other profiles.
    chat_auto_failover: bool = False
    profiles: list[str] = field(default_factory=list)
    cooldown_seconds: int = 300
    fallback_on_auth_error: bool = False


@dataclass
class JournalConfig:
    """Configuration for the task journal."""

    enabled: bool = True
    dir: str = "./tasks"

    @property
    def dir_path(self) -> Path:
        return Path(self.dir).resolve()


@dataclass
class ServerConfig:
    """Configuration for server access policy."""

    # local: localhost-only API access
    # remote: authenticated API access from non-local clients
    access_mode: str = "local"
    api_token: str = ""
    allow_unauthenticated_version: bool = True
    # Remote-mode API request limiting (best-effort in-memory limiter).
    rate_limit_enabled: bool = True
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60

    def validate(self) -> list[str]:
        errors: list[str] = []
        mode = str(self.access_mode or "").strip().lower()
        if mode not in ("local", "remote"):
            errors.append("server.access_mode must be 'local' or 'remote'")
        if mode == "remote" and not str(self.api_token or "").strip():
            errors.append("server.api_token is required when server.access_mode='remote'")
        if int(self.rate_limit_max_requests) < 1:
            errors.append("server.rate_limit_max_requests must be >= 1")
        if int(self.rate_limit_window_seconds) < 1:
            errors.append("server.rate_limit_window_seconds must be >= 1")
        return errors


@dataclass
class QualityConfig:
    """Configuration for rules-of-the-road quality gates."""

    enabled: bool = True
    enforce: bool = True
    max_auto_retries: int = 1
    require_verification_for_coding: bool = True
    require_tests_for_code_edits: bool = False
    require_monolith_guard_for_coding: bool = True

    def validate(self) -> list[str]:
        errors: list[str] = []
        if int(self.max_auto_retries) < 0:
            errors.append("quality.max_auto_retries must be >= 0")
        if int(self.max_auto_retries) > 3:
            errors.append("quality.max_auto_retries must be <= 3")
        return errors


@dataclass
class AppConfig:
    """Top-level application configuration."""

    models: Dict[str, ModelConfig] = field(default_factory=dict)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    failover: FailoverConfig = field(default_factory=FailoverConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    journal: JournalConfig = field(default_factory=JournalConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    unknown_core_keys: list[str] = field(default_factory=list)
    default_model: str = "local"
    max_agent_iterations: int = 10

    def get_model(self, name: Optional[str] = None) -> ModelConfig:
        """Get a model config by name, falling back to default."""
        key = name or self.default_model
        if key not in self.models:
            available = ", ".join(self.models.keys()) or "(none)"
            raise KeyError(f"Model '{key}' not found. Available: {available}")
        return self.models[key]

    def failover_chain(self, primary_profile: str) -> list[ModelConfig]:
        """Ordered fallback model configs for a primary profile."""
        if not self.failover.enabled:
            return []

        primary = str(primary_profile or "").strip()
        if not primary:
            return []

        ordered_names: list[str] = []
        explicit = [str(x).strip() for x in self.failover.profiles if str(x).strip()]
        if explicit:
            ordered_names.extend(explicit)
        else:
            ordered_names.extend([name for name in self.models.keys() if name != primary])

        seen: set[str] = set()
        out: list[ModelConfig] = []
        for name in ordered_names:
            if name == primary:
                continue
            if name in seen:
                continue
            seen.add(name)
            cfg = self.models.get(name)
            if cfg is not None:
                out.append(cfg)
        return out

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.models:
            errors.append("No model profiles defined. Add at least [models.local].")
        for m in self.models.values():
            errors.extend(m.validate())
        if self.default_model and self.default_model not in self.models:
            errors.append(
                f"default_model '{self.default_model}' not in models: "
                f"{list(self.models.keys())}"
            )
        if self.max_agent_iterations < 1:
            errors.append("max_agent_iterations must be >= 1")
        if self.failover.cooldown_seconds < 0:
            errors.append("failover.cooldown_seconds must be >= 0")
        for name in self.failover.profiles:
            if name not in self.models:
                errors.append(
                    f"failover.profiles contains unknown model profile '{name}'. "
                    f"Available: {list(self.models.keys())}"
                )
        errors.extend(self.server.validate())
        errors.extend(self.quality.validate())
        for key in self.unknown_core_keys:
            errors.append(f"Unknown core config key '{key}'.")
        return errors


def _env_override(data: Dict[str, Any], prefix: str = "THOMAS") -> None:
    """Apply environment variable overrides.

    Examples:
      THOMAS_DEFAULT_MODEL=cloud
      THOMAS_MAX_AGENT_ITERATIONS=20

      THOMAS_MODELS_LOCAL_BASE_URL=http://127.0.0.1:11434/v1
      THOMAS_MODELS_LOCAL_MODEL=qwen2.5-coder:7b-instruct-q4_K_M

      THOMAS_MEMORY_ROOT=./runtime
    """
    for key, value in os.environ.items():
        if not key.startswith(prefix + "_"):
            continue
        raw = key[len(prefix) + 1 :]
        flat = raw.lower()

        # Top-level keys.
        if flat in ("default_model", "max_agent_iterations"):
            data[flat] = value
            continue

        parts = flat.split("_")
        if not parts:
            continue

        # Special-case sections where leaf keys contain underscores.
        #
        # THOMAS_MODELS_<profile>_<field...> -> data["models"][profile][field]
        if parts[0] == "models" and len(parts) >= 3:
            _, profile, *rest = parts
            field = "_".join(rest)
            data.setdefault("models", {}).setdefault(profile, {})[field] = value
            continue

        # THOMAS_MEMORY_<field...> -> data["memory"][field]
        # THOMAS_TOOLS_<field...> -> data["tools"][field]
        # THOMAS_EMBED_<field...> -> data["embed"][field]
        # THOMAS_FAILOVER_<field...> -> data["failover"][field]
        # THOMAS_SERVER_<field...> -> data["server"][field]
        if parts[0] in ("memory", "tools", "embed", "failover", "server", "journal", "quality") and len(parts) >= 2:
            section, *rest = parts
            field = "_".join(rest)
            data.setdefault(section, {})[field] = value
            continue

        # Fallback: nested dict override (THOMAS_FOO_BAR -> data["foo"]["bar"]).
        d = data
        for part in parts[:-1]:
            if part not in d:
                d[part] = {}
            if not isinstance(d[part], dict):
                break
            d = d[part]
        else:
            d[parts[-1]] = value


def _coerce_types(data: Dict[str, Any]) -> None:
    """Coerce string values from env vars to appropriate types."""
    int_fields = {"max_tokens", "context_window", "context_budget", "shell_timeout",
                  "max_file_size", "max_agent_iterations", "batch_size", "cooldown_seconds",
                  "rate_limit_max_requests", "rate_limit_window_seconds", "max_auto_retries"}
    float_fields = {"temperature", "top_p", "timeout_s"}
    bool_fields = {
        "allow_shell",
        "load_on_demand",
        "enabled",
        "chat_auto_failover",
        "fallback_on_auth_error",
        "allow_unauthenticated_version",
        "rate_limit_enabled",
        "enforce",
        "require_verification_for_coding",
        "require_tests_for_code_edits",
        "require_monolith_guard_for_coding",
    }

    for key, val in list(data.items()):
        if isinstance(val, dict):
            _coerce_types(val)
        elif isinstance(val, str):
            if key in int_fields:
                data[key] = int(val)
            elif key in float_fields:
                data[key] = float(val)
            elif key in bool_fields:
                data[key] = val.lower() in ("true", "1", "yes")
            elif key == "profiles":
                data[key] = [x.strip() for x in val.split(",") if x.strip()]


def _build_model_config(name: str, d: Dict[str, Any]) -> ModelConfig:
    return ModelConfig(
        name=name,
        provider=d.get("provider", "openai_compat"),
        base_url=d.get("base_url", "http://localhost:11434/v1"),
        api_key=d.get("api_key", ""),
        api_key_header=d.get("api_key_header", "Authorization"),
        api_key_prefix=d.get("api_key_prefix", "Bearer "),
        chat_path=d.get("chat_path", "/chat/completions"),
        models_path=d.get("models_path", "/models"),
        extra_headers=d.get("extra_headers", {}) if isinstance(d.get("extra_headers"), dict) else {},
        query=d.get("query", {}) if isinstance(d.get("query"), dict) else {},
        model=d.get("model", ""),
        max_tokens=d.get("max_tokens", 4096),
        context_window=d.get("context_window", 8192),
        temperature=d.get("temperature", 0.1),
        top_p=d.get("top_p", 0.95),
        timeout_s=d.get("timeout_s", 120.0),
    )


def _collect_unknown_core_keys(data: Dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    top_allowed = {
        "models",
        "embed",
        "memory",
        "tools",
        "failover",
        "server",
        "journal",
        "quality",
        "default_model",
        "max_agent_iterations",
    }
    top_extension_allowed = {
        "watcher",
        "dep_scanner",
        "autonomy",
        "library",
        "realtime",
        "policy",
        "notifications",
        "workspace",
        "workspaces",
        "costs",
        "spend",
        "batching",
    }

    for key, val in data.items():
        if key in top_allowed:
            continue
        if isinstance(val, dict):
            if key in top_extension_allowed:
                continue
            unknown.append(str(key))
            continue
        unknown.append(str(key))

    def _field_names(dc_type: Any, *, exclude: set[str] | None = None) -> set[str]:
        names = set(getattr(dc_type, "__dataclass_fields__", {}).keys())
        if exclude:
            names -= set(exclude)
        return names

    def _scan_section(section: str, allowed: set[str], *, allow_nested: bool = False) -> None:
        sec = data.get(section)
        if not isinstance(sec, dict):
            return
        for key, value in sec.items():
            if key in allowed:
                continue
            if allow_nested and isinstance(value, dict):
                # Allow tool-specific nested sections like [tools.web_search].
                continue
            unknown.append(f"{section}.{key}")

    _scan_section("embed", _field_names(EmbedConfig))
    _scan_section("memory", _field_names(MemoryConfig))
    _scan_section("tools", _field_names(ToolsConfig), allow_nested=True)
    _scan_section("failover", _field_names(FailoverConfig))
    _scan_section("server", _field_names(ServerConfig))
    _scan_section("journal", _field_names(JournalConfig))
    _scan_section("quality", _field_names(QualityConfig))

    model_allowed = _field_names(ModelConfig, exclude={"name"})
    models = data.get("models")
    if isinstance(models, dict):
        for profile, model_data in models.items():
            if not isinstance(model_data, dict):
                continue
            for key in model_data.keys():
                if key not in model_allowed:
                    unknown.append(f"models.{profile}.{key}")

    return sorted(set(unknown))


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load configuration from TOML file with env var overrides.

    Search order:
    1. Explicit path argument
    2. THOMAS_CONFIG env var
    3. ./thomas.toml
    4. Fallback to defaults
    """
    if path is None:
        env_path = os.environ.get("THOMAS_CONFIG")
        if env_path:
            path = Path(env_path)
        else:
            path = Path("thomas.toml")

    data: Dict[str, Any] = {}
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)

    _env_override(data)
    _coerce_types(data)
    unknown_core_keys = _collect_unknown_core_keys(data)

    # Build model profiles
    models: Dict[str, ModelConfig] = {}
    for name, mdata in data.get("models", {}).items():
        if isinstance(mdata, dict):
            models[name] = _build_model_config(name, mdata)

    # If no models defined, create a default local profile
    if not models:
        models["local"] = ModelConfig(name="local")

    # Build embed config
    embed_data = data.get("embed", {})
    embed = EmbedConfig(
        provider=embed_data.get("provider", "local"),
        model=embed_data.get("model", "all-MiniLM-L6-v2"),
        device=embed_data.get("device", "auto"),
        load_on_demand=embed_data.get("load_on_demand", True),
        batch_size=embed_data.get("batch_size", 64),
    )

    # Build memory config
    mem_data = data.get("memory", {})
    memory = MemoryConfig(
        root=mem_data.get("root", "./runtime"),
        context_budget=mem_data.get("context_budget", 12000),
        mode=mem_data.get("mode", "auto"),
    )

    # Build tools config
    tools_data = data.get("tools", {})
    tools = ToolsConfig(
        sandbox_root=tools_data.get("sandbox_root", "."),
        allow_shell=tools_data.get("allow_shell", False),
        shell_timeout=tools_data.get("shell_timeout", 30),
        max_file_size=tools_data.get("max_file_size", 5_000_000),
    )

    # Build failover config
    fail_data = data.get("failover", {})
    fail_profiles = fail_data.get("profiles", [])
    if isinstance(fail_profiles, str):
        fail_profiles = [x.strip() for x in fail_profiles.split(",") if x.strip()]
    if not isinstance(fail_profiles, list):
        fail_profiles = []
    failover = FailoverConfig(
        enabled=bool(fail_data.get("enabled", True)),
        chat_auto_failover=bool(fail_data.get("chat_auto_failover", False)),
        profiles=[str(x).strip() for x in fail_profiles if str(x).strip()],
        cooldown_seconds=int(fail_data.get("cooldown_seconds", 300) or 300),
        fallback_on_auth_error=bool(fail_data.get("fallback_on_auth_error", False)),
    )

    # Build server config
    srv_data = data.get("server", {})
    server = ServerConfig(
        access_mode=str(srv_data.get("access_mode", "local") or "local").strip().lower(),
        api_token=str(srv_data.get("api_token", "") or ""),
        allow_unauthenticated_version=bool(srv_data.get("allow_unauthenticated_version", True)),
        rate_limit_enabled=bool(srv_data.get("rate_limit_enabled", True)),
        rate_limit_max_requests=int(srv_data.get("rate_limit_max_requests", 120)),
        rate_limit_window_seconds=int(srv_data.get("rate_limit_window_seconds", 60)),
    )

    # Build journal config
    journal_data = data.get("journal", {})
    journal = JournalConfig(
        enabled=bool(journal_data.get("enabled", True)),
        dir=str(journal_data.get("dir", "./tasks") or "./tasks"),
    )

    # Build quality config
    quality_data = data.get("quality", {})
    quality = QualityConfig(
        enabled=bool(quality_data.get("enabled", True)),
        enforce=bool(quality_data.get("enforce", True)),
        max_auto_retries=int(quality_data.get("max_auto_retries", 1) or 0),
        require_verification_for_coding=bool(
            quality_data.get("require_verification_for_coding", True)
        ),
        require_tests_for_code_edits=bool(
            quality_data.get("require_tests_for_code_edits", False)
        ),
        require_monolith_guard_for_coding=bool(
            quality_data.get("require_monolith_guard_for_coding", True)
        ),
    )

    return AppConfig(
        models=models,
        embed=embed,
        memory=memory,
        tools=tools,
        failover=failover,
        server=server,
        journal=journal,
        quality=quality,
        unknown_core_keys=unknown_core_keys,
        default_model=data.get("default_model", "local"),
        max_agent_iterations=data.get("max_agent_iterations", 10),
    )
