from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_NAME = "thomas._compat.marketplace.channels.p084_channel_resolve_command"
_IMPL_PATH = Path(__file__).resolve().parents[1] / "marketplace" / "channels" / "p084_channel_resolve_command.py"
_SPEC = importlib.util.spec_from_file_location(_IMPL_NAME, _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load channel resolver implementation from {_IMPL_PATH}")
_IMPL = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault(_IMPL_NAME, _IMPL)
_SPEC.loader.exec_module(_IMPL)

ChannelResolveError = _IMPL.ChannelResolveError
InvalidChannelReference = _IMPL.InvalidChannelReference
MissingChannelConfig = _IMPL.MissingChannelConfig
ExternalChannelResolutionFailed = _IMPL.ExternalChannelResolutionFailed
ChannelResolveRequest = _IMPL.ChannelResolveRequest
ChannelResolveResult = _IMPL.ChannelResolveResult
TelegramResolver = _IMPL.TelegramResolver
resolve_channel = _IMPL.resolve_channel
result_json_schema = _IMPL.result_json_schema

__all__ = [
    "ChannelResolveError",
    "InvalidChannelReference",
    "MissingChannelConfig",
    "ExternalChannelResolutionFailed",
    "ChannelResolveRequest",
    "ChannelResolveResult",
    "TelegramResolver",
    "resolve_channel",
    "result_json_schema",
]
