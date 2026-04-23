"""SKELETON: planned domain surface; import-safe placeholder module."""

from __future__ import annotations

from thomas.domain_skeletons import make_module_getattr

__getattr__ = make_module_getattr(__name__)
__all__: list[str] = []
