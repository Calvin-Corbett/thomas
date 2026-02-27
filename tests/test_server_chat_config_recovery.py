from aiohttp import web

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app_keys import APP_CONFIG, APP_SESSIONS
from thomas.server.routes.chat_aiohttp import _resolve_app_value, _resolve_runtime_config


def _config() -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root="."),
        server=ServerConfig(access_mode="local"),
    )


def test_resolve_runtime_config_uses_existing_app_key() -> None:
    app = web.Application()
    cfg = _config()
    app[APP_CONFIG] = cfg
    resolved = _resolve_runtime_config(app)
    assert resolved is cfg


def test_resolve_runtime_config_recovers_from_unkeyed_config_value() -> None:
    app = web.Application()
    cfg = _config()
    app["legacy_config"] = cfg
    resolved = _resolve_runtime_config(app)
    assert resolved is cfg
    assert app.get(APP_CONFIG) is cfg


def test_resolve_app_value_recovers_same_named_foreign_appkey() -> None:
    app = web.Application()
    foreign_sessions_key = web.AppKey("thomas.server.app_keys.sessions", dict)
    sessions = {"s1": "ok"}
    app[foreign_sessions_key] = sessions
    resolved = _resolve_app_value(app, APP_SESSIONS, expected_type=dict, required=True)
    assert resolved is sessions
    assert app.get(APP_SESSIONS) is sessions
