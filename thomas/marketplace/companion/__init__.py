"""Companion app platform scaffold for Thomas.

This package defines the stable kernel/update contract needed to support
highly customizable companion experiences while keeping the host runtime safe.
"""

from .audit import CompanionAuditLog
from .contracts import ModuleContract, UpdateBundleManifest, allowed_permissions
from .devices import DeviceRecord, DeviceRegistry
from .kernel import KERNEL_VERSION, CompanionKernel, CompanionKernelPaths
from .policy import (
    FALLBACK_POLICY_PROFILE_ID,
    ComplianceReport,
    ComplianceReportStore,
    ComplianceViolation,
    PolicyComplianceService,
    PolicyProfile,
    get_policy_profile,
    list_policy_profiles,
    resolve_policy_profile,
)
from .registry import ModuleRegistry
from .releases import ReleaseRecord, ReleaseRegistry
from .runtime import ModuleRuntime
from .studio import BundleStudio
from .update import BundleVerifier, UpdateApplier

__all__ = [
    "CompanionAuditLog",
    "BundleVerifier",
    "CompanionKernel",
    "CompanionKernelPaths",
    "ComplianceReport",
    "ComplianceReportStore",
    "ComplianceViolation",
    "DeviceRecord",
    "DeviceRegistry",
    "FALLBACK_POLICY_PROFILE_ID",
    "KERNEL_VERSION",
    "ModuleContract",
    "ModuleRuntime",
    "ModuleRegistry",
    "PolicyComplianceService",
    "PolicyProfile",
    "ReleaseRecord",
    "ReleaseRegistry",
    "BundleStudio",
    "allowed_permissions",
    "get_policy_profile",
    "list_policy_profiles",
    "resolve_policy_profile",
    "UpdateApplier",
    "UpdateBundleManifest",
]
