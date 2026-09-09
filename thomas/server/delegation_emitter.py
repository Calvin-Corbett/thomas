from __future__ import annotations

# Backward-compat shim — canonical home is chat_delegation_emitter.
from thomas.server.chat_delegation_emitter import _DelegationEmitter, _ThreadsafeDelegationEmitter

__all__ = ["_DelegationEmitter", "_ThreadsafeDelegationEmitter"]
