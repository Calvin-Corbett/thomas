"""The user overlay: a directory the base never writes, read at request time.

See docs/OVERLAY.md for the contract and docs/superpowers/plans/
2026-09-02-fork-by-overlay.md for the design. The public surface is small on
purpose: where the overlay lives (paths), what is in it (manifest.load /
resolve), and the one way anything gets in (manifest.append).
"""

from __future__ import annotations

from thomas.server.overlay.manifest import append, load, resolve
from thomas.server.overlay.paths import manifest_path, overlay_dir

__all__ = ["append", "load", "manifest_path", "overlay_dir", "resolve"]
