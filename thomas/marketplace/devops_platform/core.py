"""DevOps platform with CI/CD pipelines, deployments, and rollbacks.

Implements a DevOps system for continuous integration and deployment.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class PipelineStage(str, Enum):
    """Stages in a CI/CD pipeline."""

    BUILD = "build"
    TEST = "test"
    DEPLOY = "deploy"
    VALIDATE = "validate"
    CLEANUP = "cleanup"


class BuildStatus(str, Enum):
    """Build status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class DeploymentStatus(str, Enum):
    """Deployment status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ROLLED_BACK = "rolled_back"


@dataclass
class StageRun:
    """Execution of a pipeline stage."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    stage: PipelineStage = PipelineStage.BUILD
    status: BuildStatus = BuildStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    logs: list[str] = field(default_factory=list)
    error: str | None = None

    def start(self) -> None:
        """Start the stage."""
        self.status = BuildStatus.IN_PROGRESS
        self.started_at = datetime.now()

    def complete(self, success: bool = True) -> None:
        """Complete the stage."""
        self.completed_at = datetime.now()
        if success:
            self.status = BuildStatus.SUCCESS
        else:
            self.status = BuildStatus.FAILURE

        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

    def add_log(self, log_line: str) -> None:
        """Add a log line."""
        self.logs.append(log_line)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "log_lines": len(self.logs),
        }


@dataclass
class Build:
    """A build in the CI/CD system."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    build_number: int = 0
    branch: str = ""
    commit_hash: str = ""
    status: BuildStatus = BuildStatus.PENDING
    stages: list[StageRun] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def add_stage(self, stage: StageRun) -> None:
        """Add a stage to the build."""
        self.stages.append(stage)

    def get_current_stage(self) -> StageRun | None:
        """Get the currently running stage."""
        for stage in self.stages:
            if stage.status == BuildStatus.IN_PROGRESS:
                return stage
        return None

    def is_complete(self) -> bool:
        """Check if build is complete."""
        return self.status in (BuildStatus.SUCCESS, BuildStatus.FAILURE, BuildStatus.CANCELLED)

    def get_total_duration(self) -> float:
        """Get total build duration."""
        if not self.completed_at or not self.started_at:
            return 0.0
        return (self.completed_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "build_id": self.id,
            "build_number": self.build_number,
            "branch": self.branch,
            "commit": self.commit_hash[:8],
            "status": self.status.value,
            "stages": [s.to_dict() for s in self.stages],
            "total_duration_seconds": self.get_total_duration(),
        }


@dataclass
class Deployment:
    """A deployment."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    environment: str = ""
    version: str = ""
    status: DeploymentStatus = DeploymentStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    deployed_at: datetime | None = None
    rolled_back_at: datetime | None = None
    previous_version: str | None = None

    def deploy(self) -> None:
        """Mark as deployed."""
        self.status = DeploymentStatus.SUCCESS
        self.deployed_at = datetime.now()

    def rollback(self) -> None:
        """Rollback the deployment."""
        self.status = DeploymentStatus.ROLLED_BACK
        self.rolled_back_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "deployment_id": self.id,
            "environment": self.environment,
            "version": self.version,
            "status": self.status.value,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
        }


class Pipeline:
    """A CI/CD pipeline."""

    def __init__(self, name: str, repository: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.repository = repository
        self.stages_config: list[PipelineStage] = [PipelineStage.BUILD, PipelineStage.TEST, PipelineStage.DEPLOY]
        self.builds: dict[str, Build] = {}
        self.build_counter = 0

    def create_build(self, branch: str, commit_hash: str) -> Build:
        """Create a new build."""
        self.build_counter += 1
        build = Build(build_number=self.build_counter, branch=branch, commit_hash=commit_hash)

        # Create stages
        for stage in self.stages_config:
            stage_run = StageRun(stage=stage)
            build.add_stage(stage_run)

        self.builds[build.id] = build
        return build

    def get_build(self, build_id: str) -> Build | None:
        """Get a build by ID."""
        return self.builds.get(build_id)

    def get_latest_build(self, branch: str | None = None) -> Build | None:
        """Get the latest build."""
        builds = list(self.builds.values())
        if branch:
            builds = [b for b in builds if b.branch == branch]

        if not builds:
            return None

        return max(builds, key=lambda b: b.build_number)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pipeline_id": self.id,
            "name": self.name,
            "repository": self.repository,
            "total_builds": len(self.builds),
            "stages": [s.value for s in self.stages_config],
        }


class DeploymentManager:
    """Manages deployments across environments."""

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.deployments: dict[str, Deployment] = {}
        self.environments: dict[str, dict[str, Any]] = {}  # env_name -> config
        self.deployment_history: list[dict[str, Any]] = []

    def register_environment(self, name: str, config: dict[str, Any]) -> None:
        """Register a deployment environment."""
        self.environments[name] = config

    def get_current_version(self, environment: str) -> str | None:
        """Get current version deployed in an environment."""
        env_deployments = [
            d
            for d in self.deployments.values()
            if d.environment == environment and d.status == DeploymentStatus.SUCCESS
        ]

        if not env_deployments:
            return None

        latest = max(env_deployments, key=lambda d: d.deployed_at or datetime.now())
        return latest.version

    def deploy(self, environment: str, version: str) -> Deployment:
        """Deploy a version to an environment."""
        previous_version = self.get_current_version(environment)

        deployment = Deployment(environment=environment, version=version, previous_version=previous_version)

        deployment.deploy()
        self.deployments[deployment.id] = deployment

        self.deployment_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "environment": environment,
                "version": version,
                "action": "deployed",
            }
        )

        return deployment

    def rollback(self, environment: str) -> bool:
        """Rollback to previous version in an environment."""
        current_deployment = None
        for d in self.deployments.values():
            if d.environment == environment and d.status == DeploymentStatus.SUCCESS:
                if not current_deployment or d.deployed_at > current_deployment.deployed_at:
                    current_deployment = d

        if not current_deployment or not current_deployment.previous_version:
            return False

        current_deployment.rollback()

        self.deployment_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "environment": environment,
                "version": current_deployment.previous_version,
                "action": "rolled_back",
            }
        )

        return True

    def get_deployment_stats(self) -> dict[str, Any]:
        """Get deployment statistics."""
        total_deployments = len(self.deployments)
        successful = sum(1 for d in self.deployments.values() if d.status == DeploymentStatus.SUCCESS)
        failed = sum(1 for d in self.deployments.values() if d.status == DeploymentStatus.FAILURE)
        rolled_back = sum(1 for d in self.deployments.values() if d.status == DeploymentStatus.ROLLED_BACK)

        return {
            "total_deployments": total_deployments,
            "successful": successful,
            "failed": failed,
            "rolled_back": rolled_back,
            "environments": len(self.environments),
        }


class DevOpsPlatform:
    """Main DevOps platform."""

    def __init__(self, name: str = "devops"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.pipelines: dict[str, Pipeline] = {}
        self.deployment_manager = DeploymentManager()
        self.created_at = datetime.now()

    def create_pipeline(self, name: str, repository: str) -> Pipeline:
        """Create a new pipeline."""
        pipeline = Pipeline(name, repository)
        self.pipelines[pipeline.id] = pipeline
        return pipeline

    def get_pipeline(self, pipeline_id: str) -> Pipeline | None:
        """Get a pipeline by ID."""
        return self.pipelines.get(pipeline_id)

    def get_platform_stats(self) -> dict[str, Any]:
        """Get platform statistics."""
        total_builds = sum(len(p.builds) for p in self.pipelines.values())

        return {
            "platform_id": self.id,
            "platform_name": self.name,
            "pipelines": len(self.pipelines),
            "total_builds": total_builds,
            "deployments": self.deployment_manager.get_deployment_stats(),
        }
