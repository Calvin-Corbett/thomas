"""Thomas Desktop Operator Magic.

Session-oriented desktop control with isolated execution, quiet guardrails,
allowlisted workflow profiles, VM bootstrap support, direct window capture,
verification, recovery, and host-service onboarding for isolated desktop mode.
"""

from .contracts import DESKTOP_OPERATOR_SERVICE_ID, DESKTOP_OPERATOR_VERSION
from .host_service import (
    DEFAULT_PIPE_NAME,
    DEFAULT_SERVICE_NAME,
    DesktopHostCapabilityService,
    DesktopHostPosture,
    get_global_desktop_host_service,
)
from .manager import get_global_desktop_operator_manager
from .tools import register_desktop_operator_tools

__all__ = [
    "DEFAULT_PIPE_NAME",
    "DEFAULT_SERVICE_NAME",
    "DESKTOP_OPERATOR_SERVICE_ID",
    "DESKTOP_OPERATOR_VERSION",
    "DesktopHostCapabilityService",
    "DesktopHostPosture",
    "get_global_desktop_host_service",
    "get_global_desktop_operator_manager",
    "register_desktop_operator_tools",
]
