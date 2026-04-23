"""Tools for ML model serving operations."""

from typing import Any

from thomas.marketplace.model_serving import core
from thomas.tools.base import Tool, ToolResult


class ModelRegistryTool(Tool):
    """Manage model registry."""

    name = "model_registry"
    category = "model_serving"
    description = "Register and manage model versions"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_model", "list_models", "promote_version", "get_model"],
                "description": "Registry action",
            },
            "model_id": {"type": "string", "description": "Model identifier"},
            "version": {"type": "string", "description": "Model version"},
            "framework": {"type": "string", "description": "ML framework"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.registry = core.ModelRegistry()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "register_model":
                model_id = args.get("model_id", "")
                version = args.get("version", "")
                framework = args.get("framework", "unknown")

                if not model_id or not version:
                    return ToolResult(ok=False, error="model_id and version required")

                model_ref = self.registry.register_model(model_id, version, framework)
                return ToolResult(ok=True, data={"model_ref": model_ref, "registered": True})

            elif action == "list_models":
                model_id = args.get("model_id")
                models = self.registry.list_models(model_id)
                return ToolResult(ok=True, data={"models": [m.to_dict() for m in models], "count": len(models)})

            elif action == "promote_version":
                model_id = args.get("model_id", "")
                version = args.get("version", "")

                if not model_id or not version:
                    return ToolResult(ok=False, error="model_id and version required")

                success = self.registry.promote_version(model_id, version)
                return ToolResult(ok=True, data={"promoted": success})

            elif action == "get_model":
                model_id = args.get("model_id", "")
                version = args.get("version")

                if not model_id:
                    return ToolResult(ok=False, error="model_id required")

                model = self.registry.get_model(model_id, version)
                if not model:
                    return ToolResult(ok=False, error="Model not found")

                return ToolResult(ok=True, data=model.to_dict())

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class InferenceTool(Tool):
    """Run model inference."""

    name = "model_inference"
    category = "model_serving"
    description = "Run inference on registered models"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["infer", "batch_infer", "inference_stats"],
                "description": "Inference action",
            },
            "model_id": {"type": "string", "description": "Model identifier"},
            "version": {"type": "string", "description": "Model version"},
            "input_data": {"type": "object", "description": "Input features"},
            "batch_data": {"type": "array", "description": "Batch of inputs"},
        },
        "required": ["action", "model_id"],
    }

    def __init__(self):
        self.registry = core.ModelRegistry()
        self.engine = core.InferenceEngine(self.registry)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            model_id = args.get("model_id", "")
            version = args.get("version")

            if action == "infer":
                input_data = args.get("input_data", {})
                result = await self.engine.infer(model_id, input_data, version)

                if result.error:
                    return ToolResult(ok=False, error=result.error)

                return ToolResult(
                    ok=True,
                    data={
                        "predictions": result.predictions,
                        "confidence": result.confidence,
                        "latency_ms": round(result.latency_ms, 2),
                    },
                )

            elif action == "batch_infer":
                batch_data = args.get("batch_data", [])
                results = []

                for input_item in batch_data:
                    result = await self.engine.infer(model_id, input_item, version)
                    results.append(result.predictions)

                return ToolResult(ok=True, data={"batch_results": results, "batch_size": len(results)})

            elif action == "inference_stats":
                stats = self.engine.get_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DeploymentTool(Tool):
    """Manage model deployments."""

    name = "model_deployment"
    category = "model_serving"
    description = "Manage A/B tests, canary deployments, and auto-scaling"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start_canary", "create_ab_test", "auto_scale", "deployment_status"],
                "description": "Deployment action",
            },
            "model_id": {"type": "string", "description": "Model identifier"},
            "stable_version": {"type": "string", "description": "Stable model version"},
            "canary_version": {"type": "string", "description": "Canary model version"},
            "canary_percentage": {"type": "number", "description": "Canary traffic percentage"},
            "replicas": {"type": "integer", "description": "Number of replicas"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.registry = core.ModelRegistry()
        self.canary = core.CanaryDeployment(self.registry)
        self.scaler = core.AutoScaler()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "start_canary":
                model_id = args.get("model_id", "")
                stable = args.get("stable_version", "")
                canary = args.get("canary_version", "")
                canary_pct = args.get("canary_percentage", 10.0)

                if not all([model_id, stable, canary]):
                    return ToolResult(ok=False, error="model_id, stable_version, canary_version required")

                deployment_id = self.canary.start_canary(model_id, stable, canary, canary_pct)
                return ToolResult(ok=True, data={"deployment_id": deployment_id})

            elif action == "auto_scale":
                model_id = args.get("model_id", "")
                version = args.get("version", "latest")
                replicas = args.get("replicas", 1)

                if not model_id:
                    return ToolResult(ok=False, error="model_id required")

                model_key = f"{model_id}:{version}"
                self.scaler.set_replicas(model_key, replicas)
                return ToolResult(ok=True, data={"replicas": replicas})

            elif action == "deployment_status":
                status = self.scaler.get_scaling_status()
                return ToolResult(ok=True, data=status)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_model_serving_tools(registry):
    """Register all model serving tools."""
    registry.register(ModelRegistryTool())
    registry.register(InferenceTool())
    registry.register(DeploymentTool())
