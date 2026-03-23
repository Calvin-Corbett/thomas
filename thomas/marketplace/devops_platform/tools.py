"""Tools for DevOps Platform module.

Provides tools for CI/CD pipelines, deployments, and releases.
"""

from typing import Any

from thomas.marketplace.devops_platform import core
from thomas.tools.base import Tool, ToolResult


class PipelineManagementTool(Tool):
    """Manage CI/CD pipelines."""

    name = "devops_pipelines"
    category = "devops_platform"
    description = "Create and manage CI/CD pipelines"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_pipeline", "list_pipelines", "get_pipeline"],
                "description": "Pipeline action",
            },
            "pipeline_name": {"type": "string", "description": "Name of the pipeline"},
            "repository": {"type": "string", "description": "Repository URL"},
            "pipeline_id": {"type": "string", "description": "Pipeline identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.platform = core.DevOpsPlatform()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_pipeline":
                pipeline_name = args.get("pipeline_name", "pipeline")
                repository = args.get("repository", "")

                pipeline = self.platform.create_pipeline(pipeline_name, repository)
                return ToolResult(
                    ok=True, data={"pipeline_id": pipeline.id, "pipeline_name": pipeline_name, "repository": repository}
                )

            elif action == "list_pipelines":
                pipelines = [p.to_dict() for p in self.platform.pipelines.values()]
                return ToolResult(ok=True, data={"pipelines": pipelines})

            elif action == "get_pipeline":
                pipeline_id = args.get("pipeline_id", "")
                pipeline = self.platform.get_pipeline(pipeline_id)
                if pipeline:
                    return ToolResult(ok=True, data=pipeline.to_dict())
                else:
                    return ToolResult(ok=False, error=f"Pipeline not found: {pipeline_id}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class BuildManagementTool(Tool):
    """Manage builds in pipelines."""

    name = "devops_builds"
    category = "devops_platform"
    description = "Create and manage builds"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_build", "get_build", "list_builds"],
                "description": "Build action",
            },
            "pipeline_id": {"type": "string", "description": "Pipeline identifier"},
            "branch": {"type": "string", "description": "Git branch"},
            "commit": {"type": "string", "description": "Commit hash"},
        },
        "required": ["action", "pipeline_id"],
    }

    def __init__(self):
        self.platform = core.DevOpsPlatform()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            pipeline_id = args.get("pipeline_id", "")

            pipeline = self.platform.get_pipeline(pipeline_id)
            if not pipeline:
                return ToolResult(ok=False, error=f"Pipeline not found: {pipeline_id}")

            if action == "create_build":
                branch = args.get("branch", "main")
                commit = args.get("commit", "")

                build = pipeline.create_build(branch, commit)
                return ToolResult(
                    ok=True, data={"build_id": build.id, "build_number": build.build_number, "branch": branch}
                )

            elif action == "get_build":
                build_id = args.get("build_id", "")
                build = pipeline.get_build(build_id)
                if build:
                    return ToolResult(ok=True, data=build.to_dict())
                else:
                    return ToolResult(ok=False, error=f"Build not found: {build_id}")

            elif action == "list_builds":
                builds = [b.to_dict() for b in pipeline.builds.values()]
                return ToolResult(ok=True, data={"builds": builds})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DeploymentTool(Tool):
    """Manage deployments."""

    name = "devops_deployments"
    category = "devops_platform"
    description = "Manage deployments and rollbacks"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["deploy", "rollback", "get_status"],
                "description": "Deployment action",
            },
            "environment": {"type": "string", "description": "Target environment"},
            "version": {"type": "string", "description": "Version to deploy"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.platform = core.DevOpsPlatform()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "deploy":
                environment = args.get("environment", "")
                version = args.get("version", "")

                if not environment or not version:
                    return ToolResult(ok=False, error="environment and version required")

                deployment = self.platform.deployment_manager.deploy(environment, version)
                return ToolResult(ok=True, data=deployment.to_dict())

            elif action == "rollback":
                environment = args.get("environment", "")

                if not environment:
                    return ToolResult(ok=False, error="environment required")

                if self.platform.deployment_manager.rollback(environment):
                    return ToolResult(ok=True, data={"rolled_back": environment})
                else:
                    return ToolResult(ok=False, error=f"Cannot rollback {environment}")

            elif action == "get_status":
                stats = self.platform.deployment_manager.get_deployment_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PlatformMonitoringTool(Tool):
    """Monitor DevOps platform."""

    name = "devops_monitor"
    category = "devops_platform"
    description = "Monitor platform statistics and health"
    parameters = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["get_stats"], "description": "Monitoring action"}},
        "required": ["action"],
    }

    def __init__(self):
        self.platform = core.DevOpsPlatform()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_stats":
                stats = self.platform.get_platform_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_devops_platform_tools(registry):
    """Register all DevOps platform tools."""
    registry.register(PipelineManagementTool())
    registry.register(BuildManagementTool())
    registry.register(DeploymentTool())
    registry.register(PlatformMonitoringTool())
