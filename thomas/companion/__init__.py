"""Companion app platform scaffold for Thomas.

This package defines the stable kernel/update contract needed to support
highly customizable companion experiences while keeping the host runtime safe.
"""

from .contracts import ModuleContract, UpdateBundleManifest, allowed_permissions
from .devices import DeviceRecord, DeviceRegistry
from .kernel import CompanionKernel, CompanionKernelPaths, KERNEL_VERSION
from .releases import ReleaseRecord, ReleaseRegistry
from .registry import ModuleRegistry
from .runtime import ModuleRuntime
from .studio import BundleStudio
from .update import BundleVerifier, UpdateApplier
from .audit import CompanionAuditLog
from .policy import (
    ComplianceReport,
    ComplianceReportStore,
    ComplianceViolation,
    FALLBACK_POLICY_PROFILE_ID,
    PolicyComplianceService,
    PolicyProfile,
    get_policy_profile,
    list_policy_profiles,
    resolve_policy_profile,
)

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
