"""Thomas Autonomy Engine.

Production-grade job queue + scheduler + approvals + audit trail for autonomous background work.

Design goals:
- Safe-by-default (feature-flagged, policy-controlled, human approvals for risky actions)
- Migration-safe persistence (SQLite with schema versioning)
- Works on Windows (stdlib + aiohttp only)
"""

from .plugin import install_autonomy

__all__ = ["install_autonomy"]
