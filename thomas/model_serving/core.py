"""ML model serving with registry, inference, A/B testing, canary, and scaling."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ModelStatus(str, Enum):
    """Model deployment status."""

    REGISTERED = "registered"
    SERVING = "serving"
    ARCHIVED = "archived"
    FAILED = "failed"


@dataclass
class ModelVersion:
    """Model version with metrics."""

    model_id: str
    version: str
    timestamp: datetime
    metrics: dict[str, float] = field(default_factory=dict)
    status: ModelStatus = ModelStatus.REGISTERED
    framework: str = "unknown"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "version": self.version,
            "status": self.status.value,
            "metrics": self.metrics,
            "framework": self.framework,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class InferenceResult:
    """Result of model inference."""

    model_id: str
    version: str
    input_data: dict[str, Any]
    predictions: Any
    confidence: float = 1.0
    latency_ms: float = 0.0
    error: str | None = None


class ModelRegistry:
    """Registry for model management."""

    def __init__(self):
        self.models: dict[str, list[ModelVersion]] = {}
        self.serving_model: dict[str, str] = {}  # model_id -> version

    def register_model(self, model_id: str, version: str, framework: str = "unknown") -> str:
        """Register a new model version."""
        if model_id not in self.models:
            self.models[model_id] = []

        model_version = ModelVersion(model_id=model_id, version=version, timestamp=datetime.now(), framework=framework)
        self.models[model_id].append(model_version)

        # Set as serving version if first
        if model_id not in self.serving_model:
            self.serving_model[model_id] = version

        return f"{model_id}:{version}"

    def get_model(self, model_id: str, version: str | None = None) -> ModelVersion | None:
        """Get model version."""
        if model_id not in self.models:
            return None

        if version is None:
            version = self.serving_model.get(model_id)

        if version:
            for m in self.models[model_id]:
                if m.version == version:
                    return m

        return None

    def list_models(self, model_id: str | None = None) -> list[ModelVersion]:
        """List models."""
        if model_id:
            return self.models.get(model_id, [])

        all_models = []
        for versions in self.models.values():
            all_models.extend(versions)
        return all_models

    def promote_version(self, model_id: str, version: str) -> bool:
        """Promote version to serving."""
        model = self.get_model(model_id, version)
        if model:
            self.serving_model[model_id] = version
            model.status = ModelStatus.SERVING
            return True
        return False

    def get_serving_version(self, model_id: str) -> str | None:
        """Get serving version."""
        return self.serving_model.get(model_id)


class InferenceEngine:
    """Execute model inference."""

    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self.request_count = 0
        self.inference_history: list[InferenceResult] = []

    async def infer(self, model_id: str, input_data: dict[str, Any], version: str | None = None) -> InferenceResult:
        """Run inference on model."""
        self.request_count += 1

        model = self.registry.get_model(model_id, version)
        if not model:
            return InferenceResult(
                model_id=model_id,
                version=version or "unknown",
                input_data=input_data,
                predictions=None,
                error=f"Model {model_id}:{version} not found",
            )

        # Simulate inference
        import time

        start = time.monotonic()

        predictions = {"prediction": random.uniform(0, 1)}
        latency = (time.monotonic() - start) * 1000

        result = InferenceResult(
            model_id=model_id,
            version=model.version,
            input_data=input_data,
            predictions=predictions,
            confidence=0.95,
            latency_ms=latency,
        )

        self.inference_history.append(result)
        return result

    def get_stats(self) -> dict[str, Any]:
        """Get inference statistics."""
        if not self.inference_history:
            return {"requests": 0}

        latencies = [r.latency_ms for r in self.inference_history]
        return {
            "total_requests": self.request_count,
            "avg_latency_ms": sum(latencies) / len(latencies),
            "min_latency_ms": min(latencies),
            "max_latency_ms": max(latencies),
            "error_count": sum(1 for r in self.inference_history if r.error),
        }


class ABTestController:
    """A/B testing for models."""

    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self.tests: dict[str, dict[str, Any]] = {}
        self.split_assignments: dict[str, dict[str, str]] = {}  # request_id -> model_version

    def create_test(
        self, test_id: str, model_id: str, variant_a: str, variant_b: str, split_percentage: float = 50.0
    ) -> bool:
        """Create A/B test."""
        self.tests[test_id] = {
            "model_id": model_id,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "split": split_percentage,
            "created_at": datetime.now(),
            "metrics": {"a_count": 0, "b_count": 0},
        }
        return True

    def get_variant(self, test_id: str, request_id: str) -> str | None:
        """Get variant for request."""
        test = self.tests.get(test_id)
        if not test:
            return None

        if request_id in self.split_assignments:
            return self.split_assignments[request_id].get(test_id)

        # Assign variant
        if random.uniform(0, 100) < test["split"]:
            variant = test["variant_a"]
            test["metrics"]["a_count"] += 1
        else:
            variant = test["variant_b"]
            test["metrics"]["b_count"] += 1

        if request_id not in self.split_assignments:
            self.split_assignments[request_id] = {}

        self.split_assignments[request_id][test_id] = variant
        return variant

    def get_test_results(self, test_id: str) -> dict[str, Any] | None:
        """Get test results."""
        test = self.tests.get(test_id)
        return test.copy() if test else None


class AutoScaler:
    """Auto-scaling for model replicas."""

    def __init__(self):
        self.replicas: dict[str, int] = {}  # model:version -> replica_count
        self.load: dict[str, float] = {}  # model:version -> load_percentage
        self.scaling_history: list[dict[str, Any]] = []

    def set_replicas(self, model_key: str, count: int) -> None:
        """Set number of replicas."""
        self.replicas[model_key] = max(1, count)

    def update_load(self, model_key: str, load: float) -> None:
        """Update model load percentage."""
        self.load[model_key] = load

    def auto_scale(self) -> dict[str, int]:
        """Auto-scale based on load."""
        changes = {}

        for model_key, current_load in self.load.items():
            current_replicas = self.replicas.get(model_key, 1)

            # Scale up if load > 80%
            if current_load > 80:
                new_replicas = current_replicas * 2
            # Scale down if load < 20%
            elif current_load < 20 and current_replicas > 1:
                new_replicas = max(1, current_replicas // 2)
            else:
                new_replicas = current_replicas

            if new_replicas != current_replicas:
                self.replicas[model_key] = new_replicas
                changes[model_key] = new_replicas
                self.scaling_history.append(
                    {
                        "timestamp": datetime.now(),
                        "model": model_key,
                        "from_replicas": current_replicas,
                        "to_replicas": new_replicas,
                        "load": current_load,
                    }
                )

        return changes

    def get_scaling_status(self) -> dict[str, Any]:
        """Get scaling status."""
        return {"replicas": self.replicas, "load": self.load, "scaling_events": len(self.scaling_history)}


class CanaryDeployment:
    """Canary deployment strategy."""

    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self.deployments: dict[str, dict[str, Any]] = {}

    def start_canary(
        self, model_id: str, stable_version: str, canary_version: str, canary_percentage: float = 10.0
    ) -> str:
        """Start canary deployment."""
        deployment_id = f"canary_{model_id}_{int(datetime.now().timestamp())}"

        self.deployments[deployment_id] = {
            "model_id": model_id,
            "stable_version": stable_version,
            "canary_version": canary_version,
            "canary_percentage": canary_percentage,
            "created_at": datetime.now(),
            "metrics": {"stable_errors": 0, "canary_errors": 0},
        }

        return deployment_id

    def get_route_version(self, deployment_id: str) -> str | None:
        """Get version to route request to."""
        deployment = self.deployments.get(deployment_id)
        if not deployment:
            return None

        if random.uniform(0, 100) < deployment["canary_percentage"]:
            return deployment["canary_version"]
        else:
            return deployment["stable_version"]

    def complete_canary(self, deployment_id: str) -> bool:
        """Complete canary and promote."""
        deployment = self.deployments.get(deployment_id)
        if not deployment:
            return False

        # Promote canary to stable
        self.registry.promote_version(deployment["model_id"], deployment["canary_version"])
        return True

    def get_canary_status(self, deployment_id: str) -> dict[str, Any] | None:
        """Get canary status."""
        return self.deployments.get(deployment_id)
