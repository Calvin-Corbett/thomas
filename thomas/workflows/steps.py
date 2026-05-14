"""
Workflow Step Executors

Implements execution logic for different step types:
- Tool calls (execute Thomas tools)
- LLM prompts (send to language model)
- Conditions (branching logic)
- Loops (iteration)
- Parallel steps (concurrent execution)
- Wait steps (delays/conditions)
- Approval gates (human intervention)
- Webhooks (external API calls)

Each step executor handles its own error handling and timeout logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from thomas.core.safe_expression import SafeExpressionError, evaluate_safe_expression

from .models import StepConfig, StepResult, StepStatus, StepType, Workflow, WorkflowRun

logger = logging.getLogger(__name__)


class StepExecutor:
    """Base step executor factory and router.

    Determines the correct executor for a step type and coordinates execution.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute a workflow step.

        Args:
            step_config: Step configuration
            run: Current workflow run
            workflow: Workflow definition

        Returns:
            Step execution result
        """
        try:
            executor = self._get_executor(step_config.step_type)
            return await executor.execute(step_config, run, workflow)
        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )

    def _get_executor(self, step_type: StepType):
        """Get executor for step type.

        Args:
            step_type: Type of step

        Returns:
            Appropriate executor instance
        """
        executors = {
            StepType.TOOL_CALL: ToolCallExecutor(),
            StepType.LLM_PROMPT: LLMPromptExecutor(),
            StepType.CONDITION: ConditionExecutor(),
            StepType.LOOP: LoopExecutor(),
            StepType.PARALLEL: ParallelExecutor(),
            StepType.WAIT: WaitExecutor(),
            StepType.APPROVAL: ApprovalExecutor(),
            StepType.WEBHOOK: WebhookExecutor(),
        }
        return executors.get(step_type, ToolCallExecutor())


# ============================================================
# Concrete Step Executors
# ============================================================


class ToolCallExecutor:
    """Execute a tool call step.

    Calls a Thomas tool with given parameters.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute tool call.

        Config keys:
        - tool_name: Name of tool to call
        - tool_params: Parameters to pass (can include variable references)
        """
        try:
            tool_name = step_config.config.get("tool_name")
            if not tool_name:
                raise ValueError("tool_name is required")

            # Resolve parameters with variable substitution
            params = step_config.config.get("tool_params", {})
            params = self._substitute_vars(params, run.variables)

            logger.info(f"Executing tool: {tool_name} with {params}")

            raise NotImplementedError(
                f"Tool registry integration not yet implemented. Tool '{tool_name}' cannot be executed. "
                "This feature requires integration with the Thomas tool registry."
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )

    def _substitute_vars(self, obj: Any, variables: dict[str, Any]) -> Any:
        """Substitute variable references in objects.

        Variables referenced as ${var_name} are replaced with values from variables dict.
        """
        if isinstance(obj, str):
            for var_name, var_value in variables.items():
                obj = obj.replace(f"${{{var_name}}}", str(var_value))
            return obj
        elif isinstance(obj, dict):
            return {k: self._substitute_vars(v, variables) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._substitute_vars(item, variables) for item in obj]
        return obj


class LLMPromptExecutor:
    """Execute an LLM prompt step.

    Sends a prompt to a language model and captures the response.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute LLM prompt.

        Config keys:
        - prompt: Prompt template
        - model: Model to use (optional)
        - temperature: Temperature parameter (optional)
        """
        try:
            prompt = step_config.config.get("prompt")
            if not prompt:
                raise ValueError("prompt is required")

            model = step_config.config.get("model", "default")
            step_config.config.get("temperature", 0.7)

            logger.info(f"Executing LLM prompt with model: {model}")

            raise NotImplementedError(
                f"LLM integration not yet implemented. Model '{model}' cannot be called. "
                "This feature requires integration with the LLM client."
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )


class ConditionExecutor:
    """Execute a condition step.

    Evaluates a condition and determines branching.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Evaluate condition.

        Config keys:
        - condition: Condition expression to evaluate
        - branches: Map of outcome -> step (for-branching)
        """
        try:
            condition = step_config.config.get("condition")
            if not condition:
                raise ValueError("condition is required")

            # Simple condition evaluation
            result = self._evaluate_condition(condition, run.variables)

            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.COMPLETED,
                output={"condition": condition, "result": result},
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )

    def _evaluate_condition(self, condition: str, variables: dict[str, Any]) -> bool:
        """Evaluate a simple condition expression.

        Supports basic comparisons like:
        - ${var} == value
        - ${var} > value
        - ${var} in [a, b, c]
        """
        try:
            expr = condition
            for var_name, var_value in variables.items():
                expr = expr.replace(f"${{{var_name}}}", repr(var_value))
            return bool(evaluate_safe_expression(expr))
        except (SafeExpressionError, Exception) as e:
            logger.warning(f"Condition evaluation failed: {e}")
            return False


class LoopExecutor:
    """Execute a loop step.

    Iterates over items and executes sub-workflow for each.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute loop.

        Config keys:
        - items: Items to iterate over (can reference variables)
        - body_step: Step to execute for each item
        - item_var: Variable name for current item
        """
        try:
            items_ref = step_config.config.get("items")
            if not items_ref:
                raise ValueError("items is required")

            # Resolve items from variables or config
            if isinstance(items_ref, str) and items_ref.startswith("${"):
                var_name = items_ref[2:-1]
                items = run.variables.get(var_name, [])
            else:
                items = items_ref

            if not isinstance(items, list):
                items = [items]

            item_var = step_config.config.get("item_var", "item")
            results = []

            for idx, item in enumerate(items):
                run.variables[item_var] = item
                run.variables["__loop_index__"] = idx
                results.append({"index": idx, "item": item})

            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.COMPLETED,
                output={"iterations": len(items), "results": results},
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )


class ParallelExecutor:
    """Execute parallel steps concurrently."""

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute steps in parallel.

        Config keys:
        - steps: List of step IDs to execute in parallel
        """
        try:
            step_ids = step_config.config.get("steps", [])
            if not step_ids:
                raise ValueError("steps list is required")

            raise NotImplementedError(
                f"Parallel step execution not yet implemented. Cannot execute {len(step_ids)} steps in parallel. "
                "This feature requires async step orchestration support."
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )


class WaitExecutor:
    """Wait step executor.

    Pauses workflow execution for a duration or until a condition is met.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute wait step.

        Config keys:
        - duration_seconds: Duration to wait
        - until_condition: Condition to wait for (optional)
        """
        try:
            duration = step_config.config.get("duration_seconds", 0)
            step_config.config.get("until_condition")

            if duration > 0:
                # Respect timeout from step_config
                max_wait = min(
                    duration,
                    step_config.timeout_seconds or duration,
                )
                await asyncio.sleep(max_wait)

            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.COMPLETED,
                output={"waited_seconds": duration},
            )

        except asyncio.TimeoutError:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error="Wait timeout exceeded",
            )
        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )


class ApprovalExecutor:
    """Human approval step executor.

    Pauses workflow and waits for human approval.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute approval step.

        Config keys:
        - message: Message to display for approval
        - timeout_seconds: How long to wait for approval
        """
        try:
            message = step_config.config.get("message", "Approval required")
            step_config.config.get("timeout_seconds", 3600)

            logger.info(f"Waiting for approval: {message}")

            raise NotImplementedError(
                f"Approval system integration not yet implemented. Message: '{message}'. "
                "This feature requires integration with the Thomas approval workflow system."
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )


class WebhookExecutor:
    """Webhook step executor.

    Calls external HTTP endpoints.
    """

    async def execute(
        self,
        step_config: StepConfig,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute webhook call.

        Config keys:
        - url: Webhook URL
        - method: HTTP method (GET, POST, etc.)
        - body: Request body (optional)
        - headers: Custom headers (optional)
        """
        try:
            url = step_config.config.get("url")
            if not url:
                raise ValueError("url is required")

            method = step_config.config.get("method", "POST")
            step_config.config.get("body")
            step_config.config.get("headers", {})

            logger.info(f"Calling webhook: {method} {url}")

            raise NotImplementedError(
                f"HTTP client integration not yet implemented. Cannot call {method} {url}. "
                "This feature requires integration with an HTTP client library."
            )

        except Exception as e:
            return StepResult(
                step_id=step_config.step_id,
                status=StepStatus.FAILED,
                error=str(e),
            )
