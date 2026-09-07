"""Harbor agent adapter for Thomas.

Exposes :class:`ThomasAgent` so Harbor can drive Thomas as the agent under
test via ``-a "harbor_thomas.agent:ThomasAgent"``.
"""

from harbor_thomas.agent import ThomasAgent

__all__ = ["ThomasAgent"]
