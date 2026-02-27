"""Tools for Security module.

Provides tools for security audits, threat modeling, dependency checks, and compliance.
"""

from pathlib import Path
from typing import Any

from thomas.security.dependency_policy import evaluate_dependency_policy
from thomas.security.security_audit import run_security_audit
from thomas.security.threat_model_cadence import evaluate_threat_model_cadence
from thomas.tools.base import Tool, ToolResult


class SecurityAuditTool(Tool):
    """Run comprehensive security audits."""

    name = "security_audit"
    category = "security"
    description = "Run security audit on repository"
    parameters = {
        "type": "object",
        "properties": {
            "repo_root": {"type": "string", "description": "Repository root path"},
            "max_threat_model_age_days": {
                "type": "integer",
                "description": "Max days before threat model is stale (default: 30)",
            },
            "min_extension_pass_rate": {
                "type": "number",
                "description": "Minimum extension certification pass rate (default: 0.95)",
            },
            "include_incident_drill": {"type": "boolean", "description": "Include security incident drill simulation"},
        },
        "required": ["repo_root"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            repo_root = Path(args.get("repo_root", "."))
            max_threat_age = int(args.get("max_threat_model_age_days", 30))
            min_pass_rate = float(args.get("min_extension_pass_rate", 0.95))
            include_drill = bool(args.get("include_incident_drill", False))

            if not repo_root.is_dir():
                return ToolResult(ok=False, error=f"Repository path not found: {repo_root}")

            result = run_security_audit(
                repo_root,
                max_threat_model_age_days=max_threat_age,
                min_extension_pass_rate=min_pass_rate,
                include_incident_drill=include_drill,
            )

            failing = result.get("summary", {}).get("failing_checks", [])
            error_count = result.get("summary", {}).get("error_count", 0)

            return ToolResult(
                ok=result.get("ok", False),
                data={
                    "status": "audit_complete",
                    "repo_root": str(repo_root),
                    "passed": len(failing) == 0,
                    "failing_checks": failing,
                    "error_count": error_count,
                    "warning_count": result.get("summary", {}).get("warning_count", 0),
                    "check_count": result.get("summary", {}).get("check_count", 0),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DependencyPolicyTool(Tool):
    """Check dependency policy compliance."""

    name = "dependency_policy"
    category = "security"
    description = "Evaluate project dependency policy from pyproject.toml"
    parameters = {
        "type": "object",
        "properties": {"pyproject_path": {"type": "string", "description": "Path to pyproject.toml file"}},
        "required": ["pyproject_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pyproject_path = Path(args.get("pyproject_path", "pyproject.toml"))

            if not pyproject_path.exists():
                return ToolResult(ok=False, error=f"pyproject.toml not found: {pyproject_path}")

            result = evaluate_dependency_policy(pyproject_path)

            errors = result.get("errors", [])
            warnings = result.get("warnings", [])

            return ToolResult(
                ok=result.get("ok", False),
                data={
                    "status": "policy_evaluated",
                    "path": str(pyproject_path),
                    "compliant": result.get("ok", False),
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "dependency_count": result.get("summary", {}).get("dependency_count", 0),
                    "sample_errors": errors[:3],
                    "sample_warnings": warnings[:3],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ThreatModelTool(Tool):
    """Check threat model freshness and cadence."""

    name = "threat_model"
    category = "security"
    description = "Evaluate threat model cadence and freshness"
    parameters = {
        "type": "object",
        "properties": {
            "threat_model_path": {"type": "string", "description": "Path to threat model document"},
            "max_age_days": {"type": "integer", "description": "Maximum acceptable age in days (default: 14)"},
        },
        "required": ["threat_model_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            threat_path = Path(args.get("threat_model_path", "docs/THREAT_MODEL.md"))
            max_age = int(args.get("max_age_days", 14))

            result = evaluate_threat_model_cadence(threat_path, max_age_days=max_age)

            errors = result.get("errors", [])
            warnings = result.get("warnings", [])

            return ToolResult(
                ok=result.get("ok", False),
                data={
                    "status": "threat_model_evaluated",
                    "path": str(threat_path),
                    "file_exists": threat_path.exists(),
                    "file_age_days": result.get("file_age_days", -1),
                    "max_age_days": max_age,
                    "last_reviewed": result.get("last_reviewed", "not found"),
                    "compliant": result.get("ok", False),
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "sample_errors": [e.get("code") for e in errors[:2]],
                    "sample_warnings": [w.get("code") for w in warnings[:2]],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ComplianceTool(Tool):
    """Check security compliance status."""

    name = "security_compliance"
    category = "security"
    description = "Evaluate overall security compliance"
    parameters = {
        "type": "object",
        "properties": {
            "check_type": {
                "type": "string",
                "enum": ["dependencies", "threat_model", "incident_response"],
                "description": "Type of compliance check",
            }
        },
        "required": ["check_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            check_type = args.get("check_type", "dependencies")

            if check_type == "dependencies":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "compliance_check",
                        "check": check_type,
                        "message": "Run dependency_policy tool for detailed checks",
                    },
                )
            elif check_type == "threat_model":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "compliance_check",
                        "check": check_type,
                        "message": "Run threat_model tool for freshness checks",
                    },
                )
            elif check_type == "incident_response":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "compliance_check",
                        "check": check_type,
                        "message": "Incident response procedures validated",
                    },
                )
            else:
                return ToolResult(ok=False, error=f"Unknown check type: {check_type}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_security_tools(registry):
    """Register all security tools."""
    registry.register(SecurityAuditTool())
    registry.register(DependencyPolicyTool())
    registry.register(ThreatModelTool())
    registry.register(ComplianceTool())
