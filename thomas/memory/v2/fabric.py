"""Memory fabric: unified episodic + semantic + profile storage.

This module re-exports the main public interfaces from sub-modules:
- fabric_utils: utility functions and MemorySettings dataclass
- fabric_core: MemoryFabricV2 main class
- fabric_compat: MemoryFabricCompat compatibility shim
"""

from .fabric_compat import MemoryFabricCompat
from .fabric_core import MemoryFabricV2
from .fabric_utils import MemorySettings

__all__ = [
    "MemoryFabricV2",
    "MemoryFabricCompat",
    "MemorySettings",
]
