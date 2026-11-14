from __future__ import annotations

import subprocess
import sys

from thomas.server import chat_app_keys
from thomas.server.routes import chat_v2_keys


def test_server_core_imports_without_optional_routes() -> None:
    code = """
import builtins

original_import = builtins.__import__

def refuse_routes(name, globals=None, locals=None, fromlist=(), level=0):
    if name.startswith('thomas.server.routes.'):
        raise ModuleNotFoundError(name)
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = refuse_routes
import thomas.server.worker_runtime
import thomas.server.app_chat_store
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_chat_v2_compatibility_exports_are_the_same_keys() -> None:
    assert len(chat_app_keys.__all__) == 6
    assert chat_v2_keys.__all__ == chat_app_keys.__all__
    for name in chat_app_keys.__all__:
        assert getattr(chat_v2_keys, name) is getattr(chat_app_keys, name)
