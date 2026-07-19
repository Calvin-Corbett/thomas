from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class WorkflowExecutionError(ValueError):
    pass


_NO_HUMAN_MODES = {"human", "allow", "deny"}
_DEFAULT_NO_HUMAN_MODE = "human"


def _text(value: Any, *, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    return default


def _text_list(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            s = _text(item)
            if s:
                out.append(s)
    return out


def _normalize_no_human_mode(value: Any) -> str:
    mode = str(value or _DEFAULT_NO_HUMAN_MODE).strip().lower()
    if mode not in _NO_HUMAN_MODES:
        return _DEFAULT_NO_HUMAN_MODE
    return mode


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "pass", "passed", "ok"):
            return True
        if v in ("0", "false", "no", "fail", "failed"):
            return False
    return default


def _as_int(value: Any, *, default: int, minimum: int = 1, maximum: int = 12) -> int:
    try:
        iv = int(value)
    except (ValueError, TypeError):
        iv = int(default)
    return max(minimum, min(maximum, iv))


@dataclass(frozen=True)
class _StepSpec:
    name: str
    prompt: str
    capability: str
    profile: str
    approval_required: bool = False  # halt for human approval before executing


@dataclass(frozen=True)
class _RouteSpec:
    name: str
    when: str
    prompt: str
    capability: str
    profile: str


@dataclass(frozen=True)
class _AskJsonResult:
    payload: dict[str, Any]
    profile: str
    capability: str
    requested_profile: str
    requested_capability: str
    attempts: list[dict[str, Any]]

    @property
    def fallback_used(self) -> bool:
        return (
            self.profile != self.requested_profile
            or self.capability != self.requested_capability
            or len(self.attempts) > 1
        )


_CAPABILITY_FALLBACKS: dict[str, tuple[str, ...]] = {
    "video_gen": ("image_gen", "chat"),
    "image_gen": ("chat",),
    "audio": ("chat",),
    "stt": ("audio", "chat"),
    "tts": ("audio", "chat"),
    "tools": ("chat",),
}


class WorkflowRunner:
    """Workflow-first execution patterns using the chat adapter."""

    def __init__(
        self,
        *,
        chat_adapter,
        session_id: str | None = None,
        default_profile: str | None = None,
        capabilities_by_profile: Mapping[str, Mapping[str, bool]] | None = None,
        approval_broker: Any = None,
        no_human_mode: str = "human",
        execution_context: Mapping[str, Any] | None = None,
    ):
        self._chat = chat_adapter
        self._session_id = session_id
        self._default_profile = _text(default_profile)
        self._approval_broker = approval_broker  # optional ApprovalBroker for step gates
        self._execution_context = dict(execution_context or {})
        self._no_human_mode = _normalize_no_human_mode(
            os.environ.get("THOMAS_AUTONOMY_NO_HUMAN_MODE")
            or os.environ.get("THOMAS_NO_HUMAN_MODE")
            or os.environ.get("THOMAS_GUARDRAILS_NO_HUMAN_MODE")
            or no_human_mode
        )
        self._caps: dict[str, dict[str, bool]] = {}
        for profile, caps in (capabilities_by_profile or {}).items():
            p = _text(profile)
            if not p:
                continue
            if isinstance(caps, Mapping):
                self._caps[p] = {str(k): bool(v) for k, v in caps.items()}

    def _execution_prompt(self, system_prompt: str) -> str:
        if not self._execution_context:
            return system_prompt
        context = {
            key: self._execution_context.get(key)
            for key in (
                "model_id",
                "reasoning_effort",
                "autonomy_level",
                "file_access",
                "thomas_guardrails",
                "memory",
                "token_economy",
                "private_skills",
                "job_memory",
                "connector_bindings",
                "settings",
                "work_app_id",
                "work_job_id",
            )
            if key in self._execution_context
        }
        return (
            system_prompt.rstrip()
            + "\n\n[Verified Work execution context]\n"
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
        )

    def _adapter_execution_kwargs(self) -> dict[str, Any]:
        controls = {
            "model_id": self._execution_context.get("model_id"),
            "reasoning_effort": self._execution_context.get("reasoning_effort"),
            "autonomy_level": self._execution_context.get("autonomy_level"),
            "file_access": self._execution_context.get("file_access"),
            "thomas_guardrails": self._execution_context.get("thomas_guardrails"),
            "memory": self._execution_context.get("memory"),
            "token_economy": self._execution_context.get("token_economy"),
            "private_skills": self._execution_context.get("private_skills"),
            "job_memory": self._execution_context.get("job_memory"),
            "connector_bindings": self._execution_context.get("connector_bindings"),
            "work_app_id": self._execution_context.get("work_app_id"),
            "work_job_id": self._execution_context.get("work_job_id"),
        }
        controls = {key: value for key, value in controls.items() if value is not None}
        try:
            parameters = inspect.signature(self._chat.generate_json).parameters
        except (TypeError, ValueError):
            return {"model_id": controls["model_id"]} if controls.get("model_id") else {}
        if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            return controls
        return {key: value for key, value in controls.items() if key in parameters}

    def _profile_supports_capability(self, profile: str, capability: str) -> bool:
        p = _text(profile)
        c = _text(capability)
        if not p:
            return False
        if not c:
            return True
        if not self._caps:
            return True
        caps = self._caps.get(p) or {}
        return bool(caps.get(c, False))

    def _candidate_profiles(
        self,
        *,
        capability: str = "",
        preferred_profile: str = "",
        strict_capability: bool,
    ) -> list[str]:
        c = _text(capability)
        preferred = _text(preferred_profile)
        default = _text(self._default_profile)
        candidates: list[str] = []
        seen: set[str] = set()

        # Worker decomposition is model-authored. Without a trusted profile
        # registry, never treat a descriptive model suggestion (for example
        # "Independent QA reviewer") as a configured Thomas model profile.
        # An owner-selected default remains authoritative; otherwise the chat
        # route resolves its configured default.
        if not self._caps:
            preferred = default

        def _push(profile: str, *, requires_capability: bool) -> None:
            p = _text(profile)
            if not p or p in seen:
                return
            if self._caps and p not in self._caps:
                return
            if requires_capability and c and not self._profile_supports_capability(p, c):
                return
            seen.add(p)
            candidates.append(p)

        if c and self._caps:
            _push(preferred, requires_capability=True)
            _push(default, requires_capability=True)
            for profile in sorted(self._caps.keys()):
                _push(profile, requires_capability=True)
            if candidates:
                return candidates
            if strict_capability:
                return []

        _push(preferred, requires_capability=False)
        _push(default, requires_capability=False)
        if self._caps:
            for profile in sorted(self._caps.keys()):
                _push(profile, requires_capability=False)
        return candidates

    def _capability_chain(
        self,
        capability: str,
        *,
        fallback_capabilities: Sequence[str] | None = None,
    ) -> list[str]:
        requested = _text(capability, default="chat")
        chain: list[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            v = _text(value)
            if not v or v in seen:
                return
            seen.add(v)
            chain.append(v)

        _add(requested)
        for c in fallback_capabilities or []:
            _add(str(c))
        for c in _CAPABILITY_FALLBACKS.get(requested, ()):
            _add(c)
        if requested != "chat":
            _add("chat")
        return chain or ["chat"]

    def _select_profile(self, *, capability: str = "", preferred_profile: str = "") -> str:
        candidates = self._candidate_profiles(
            capability=capability,
            preferred_profile=preferred_profile,
            strict_capability=False,
        )
        if candidates:
            return candidates[0]
        return ""

    async def _ask_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
        profile: str = "",
        capability: str = "chat",
        fallback_capabilities: Sequence[str] | None = None,
    ) -> _AskJsonResult:
        requested_profile = _text(profile)
        requested_capability = _text(capability, default="chat")
        chain = self._capability_chain(
            requested_capability,
            fallback_capabilities=fallback_capabilities,
        )
        attempts: list[dict[str, Any]] = []
        tried: set[tuple[str, str]] = set()
        last_exc: Exception | None = None

        for cap in chain:
            candidates = self._candidate_profiles(
                capability=cap,
                preferred_profile=requested_profile,
                strict_capability=True,
            )
            if not candidates:
                # When profile capabilities are known, move to the next capability fallback
                # instead of forcing unsupported capability execution.
                if self._caps:
                    continue
                candidates = self._candidate_profiles(
                    capability=cap,
                    preferred_profile=requested_profile,
                    strict_capability=False,
                )
            if not candidates:
                candidates = [""]

            for candidate in candidates:
                key = (cap, candidate)
                if key in tried:
                    continue
                tried.add(key)
                try:
                    out = await self._chat.generate_json(
                        system_prompt=self._execution_prompt(system_prompt),
                        user_prompt=user_prompt,
                        session_id=self._session_id,
                        schema_hint=schema_hint,
                        profile=(candidate or None),
                        **self._adapter_execution_kwargs(),
                    )
                    if not isinstance(out, dict):
                        raise WorkflowExecutionError("workflow step returned non-object JSON")
                    attempts.append(
                        {
                            "capability": cap,
                            "profile": candidate,
                            "ok": True,
                        }
                    )
                    return _AskJsonResult(
                        payload=out,
                        profile=candidate,
                        capability=cap,
                        requested_profile=requested_profile,
                        requested_capability=requested_capability,
                        attempts=attempts,
                    )
                except Exception as e:
                    last_exc = e
                    attempts.append(
                        {
                            "capability": cap,
                            "profile": candidate,
                            "ok": False,
                            "error": f"{type(e).__name__}: {e}",
                        }
                    )

        if last_exc is not None:
            raise last_exc
        raise WorkflowExecutionError("workflow step had no viable fallback candidates")

    def _parse_steps(self, payload: dict[str, Any], *, default_capability: str = "chat") -> list[_StepSpec]:
        steps_out: list[_StepSpec] = []
        raw_steps = payload.get("steps")
        if isinstance(raw_steps, list):
            for idx, item in enumerate(raw_steps, start=1):
                if isinstance(item, dict):
                    prompt = _text(item.get("prompt") or item.get("task"))
                    if not prompt:
                        continue
                    steps_out.append(
                        _StepSpec(
                            name=_text(item.get("name")) or f"step-{idx}",
                            prompt=prompt,
                            capability=_text(item.get("capability"), default=default_capability),
                            profile=_text(item.get("profile")),
                            approval_required=_as_bool(item.get("approval") or item.get("approval_required")),
                        )
                    )
                elif isinstance(item, str) and item.strip():
                    steps_out.append(
                        _StepSpec(
                            name=f"step-{idx}",
                            prompt=item.strip(),
                            capability=default_capability,
                            profile="",
                        )
                    )
        if steps_out:
            return steps_out

        single = _text(payload.get("step") or payload.get("prompt"))
        if single:
            steps_out.append(
                _StepSpec(
                    name="step-1",
                    prompt=single,
                    capability=default_capability,
                    profile="",
                )
            )
        return steps_out

    def _parse_workers(self, payload: dict[str, Any], *, default_capability: str = "chat") -> list[_StepSpec]:
        workers: list[_StepSpec] = []
        raw_workers = payload.get("workers")
        if isinstance(raw_workers, list):
            for idx, item in enumerate(raw_workers, start=1):
                if not isinstance(item, dict):
                    continue
                prompt = _text(item.get("prompt") or item.get("task"))
                if not prompt:
                    continue
                workers.append(
                    _StepSpec(
                        name=_text(item.get("name")) or f"worker-{idx}",
                        prompt=prompt,
                        capability=_text(item.get("capability"), default=default_capability),
                        profile=_text(item.get("profile")),
                    )
                )
        if workers:
            return workers
        return self._parse_steps(payload, default_capability=default_capability)

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise WorkflowExecutionError("workflow payload must be an object")
        workflow = _text(payload.get("workflow") or payload.get("pattern") or "chain").lower()
        if workflow in ("chain", "prompt_chain", "sequential"):
            return await self.run_chain(payload)
        if workflow in ("parallel", "map_reduce"):
            return await self.run_parallel(payload)
        if workflow in ("orchestrator_worker", "orchestrator-workers", "orchestrate"):
            return await self.run_orchestrator_worker(payload)
        if workflow in ("coding_pipeline", "coding-pipeline", "phased_coding"):
            return await self.run_coding_pipeline(payload)
        if workflow in ("routing", "router"):
            return await self.run_routing(payload)
        if workflow in ("evaluator_optimizer", "eval_opt", "optimize"):
            return await self.run_evaluator_optimizer(payload)
        raise WorkflowExecutionError(f"unsupported workflow pattern: {workflow}")

    async def run_chain(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = _text(payload.get("goal") or payload.get("task") or payload.get("prompt"))
        if not goal:
            raise WorkflowExecutionError("chain workflow requires payload.goal")

        steps = self._parse_steps(payload, default_capability=_text(payload.get("capability"), default="chat"))
        if not steps:
            raise WorkflowExecutionError("chain workflow requires at least one step")

        previous_summary = ""
        outputs: list[dict[str, Any]] = []
        for idx, step in enumerate(steps, start=1):
            # Approval gate: halt for human approval before executing this step.
            if step.approval_required and self._approval_broker is not None and self._no_human_mode == "human":
                approved = await self._approval_broker.require(
                    run_id=goal[:60],
                    tool_call_id=f"workflow_step:{step.name}",
                    session_id="",
                    tool_name=f"workflow.{step.name}",
                    args_preview={"prompt": step.prompt[:200], "step": f"{idx}/{len(steps)}"},
                    reason=f"Workflow step '{step.name}' requires approval before execution.",
                    timeout_s=300,
                )
                if not approved:
                    return {
                        "pattern": "chain",
                        "ok": False,
                        "error": f"Step '{step.name}' not approved by user.",
                        "completed_steps": idx - 1,
                        "outputs": outputs,
                    }
            if step.approval_required and self._approval_broker is not None and self._no_human_mode == "deny":
                return {
                    "pattern": "chain",
                    "ok": False,
                    "error": f"Step '{step.name}' blocked by no-human deny mode.",
                    "completed_steps": idx - 1,
                    "outputs": outputs,
                }
            step_profile = self._select_profile(capability=step.capability, preferred_profile=step.profile)
            step_exec = await self._ask_json(
                system_prompt=(
                    "You are a workflow chain worker. Complete only the current step. "
                    "Return strict JSON with output and summary."
                ),
                user_prompt=(
                    f"Goal:\n{goal}\n\n"
                    f"Current step ({idx}/{len(steps)}) [{step.name}]:\n{step.prompt}\n\n"
                    f"Previous context summary:\n{previous_summary or '(none)'}\n"
                ),
                schema_hint={"output": "string", "summary": "string"},
                profile=step_profile,
                capability=step.capability,
            )
            response = step_exec.payload
            output_text = _text(response.get("output") or response.get("text"))
            summary_text = _text(response.get("summary")) or (output_text[:300] if output_text else "")
            outputs.append(
                {
                    "index": idx,
                    "name": step.name,
                    "step": step.prompt,
                    "capability": step.capability,
                    "resolved_capability": step_exec.capability,
                    "profile": step_exec.profile,
                    "fallback_used": bool(step_exec.fallback_used),
                    "attempt_count": len(step_exec.attempts),
                    "output": output_text,
                    "summary": summary_text,
                }
            )
            previous_summary = summary_text or previous_summary

        final_output = outputs[-1]["output"] if outputs else ""
        return {
            "pattern": "chain",
            "goal": goal,
            "steps": outputs,
            "final_output": final_output,
        }

    async def run_parallel(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = _text(payload.get("goal") or payload.get("task") or payload.get("prompt"))
        if not goal:
            raise WorkflowExecutionError("parallel workflow requires payload.goal")

        workers = self._parse_workers(payload, default_capability=_text(payload.get("capability"), default="chat"))
        if not workers:
            workers = [_StepSpec(name="worker-1", prompt=goal, capability="chat", profile="")]

        async def _run_worker(worker: _StepSpec) -> dict[str, Any]:
            worker_profile = self._select_profile(
                capability=worker.capability,
                preferred_profile=worker.profile,
            )
            try:
                worker_exec = await self._ask_json(
                    system_prompt=(
                        "You are a parallel workflow worker. Execute your assigned subtask only. "
                        "Return strict JSON with output and summary."
                    ),
                    user_prompt=f"Global goal:\n{goal}\n\nAssigned subtask:\n{worker.prompt}\n",
                    schema_hint={"output": "string", "summary": "string"},
                    profile=worker_profile,
                    capability=worker.capability,
                )
                response = worker_exec.payload
                output_text = _text(response.get("output") or response.get("text"))
                summary_text = _text(response.get("summary")) or output_text[:300]
                return {
                    "name": worker.name,
                    "prompt": worker.prompt,
                    "capability": worker.capability,
                    "resolved_capability": worker_exec.capability,
                    "profile": worker_exec.profile,
                    "fallback_used": bool(worker_exec.fallback_used),
                    "attempt_count": len(worker_exec.attempts),
                    "output": output_text,
                    "summary": summary_text,
                    "ok": True,
                }
            except Exception as exc:
                return {
                    "name": worker.name,
                    "prompt": worker.prompt,
                    "capability": worker.capability,
                    "resolved_capability": worker.capability,
                    "profile": worker_profile,
                    "fallback_used": False,
                    "attempt_count": 0,
                    "output": "",
                    "summary": "",
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        results = await asyncio.gather(*[_run_worker(w) for w in workers])
        worker_errors = [item for item in results if not bool(item.get("ok", True))]
        if worker_errors and not _as_bool(payload.get("allow_partial"), default=False):
            summaries = "; ".join(
                f"{_text(item.get('name'), default='worker')}: {_text(item.get('error'), default='failed')}"
                for item in worker_errors[:3]
            )
            raise WorkflowExecutionError(
                f"parallel workflow failed closed because {len(worker_errors)} of {len(results)} workers failed"
                + (f": {summaries}" if summaries else "")
            )

        synthesize = _as_bool(payload.get("synthesize"), default=True)
        synthesis = ""
        if synthesize:
            synthesis_cap = _text(payload.get("synthesis_capability"), default="chat")
            synthesis_profile = self._select_profile(
                capability=synthesis_cap,
                preferred_profile=_text(payload.get("synthesis_profile")),
            )
            synthesis_exec = await self._ask_json(
                system_prompt=(
                    "You are an orchestrator that merges worker outputs into a single answer. "
                    "Return strict JSON with final_output and rationale."
                ),
                user_prompt=(f"Global goal:\n{goal}\n\nWorker outputs:\n{results}\n"),
                schema_hint={"final_output": "string", "rationale": "string"},
                profile=synthesis_profile,
                capability=synthesis_cap,
            )
            synthesis_resp = synthesis_exec.payload
            synthesis = _text(synthesis_resp.get("final_output") or synthesis_resp.get("output"))

        return {
            "pattern": "parallel",
            "goal": goal,
            "workers": results,
            "worker_errors": worker_errors,
            "final_output": synthesis or "\n\n".join(_text(x.get("output")) for x in results if _text(x.get("output"))),
        }

    async def run_orchestrator_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = _text(payload.get("goal") or payload.get("task") or payload.get("prompt"))
        if not goal:
            raise WorkflowExecutionError("orchestrator_worker requires payload.goal")

        worker_count = _as_int(payload.get("worker_count"), default=3, minimum=1, maximum=8)
        orchestration_cap = _text(payload.get("orchestrator_capability"), default="chat")
        orchestration_profile = self._select_profile(
            capability=orchestration_cap,
            preferred_profile=_text(payload.get("orchestrator_profile")),
        )

        decompose_exec = await self._ask_json(
            system_prompt=(
                "You are an orchestrator. Decompose the goal into independent worker tasks. "
                "Return strict JSON with workers array where each worker has name, prompt, capability(optional), profile(optional)."
            ),
            user_prompt=(
                f"Goal:\n{goal}\n\n"
                f"Create up to {worker_count} workers. Prefer independent tasks that can run in parallel."
            ),
            schema_hint={
                "workers": [{"name": "string", "prompt": "string", "capability": "string", "profile": "string"}]
            },
            profile=orchestration_profile,
            capability=orchestration_cap,
        )
        decompose = decompose_exec.payload

        workers_payload = dict(payload)
        workers_payload["workers"] = decompose.get("workers")
        workers = self._parse_workers(
            workers_payload,
            default_capability=_text(payload.get("worker_capability"), default="chat"),
        )
        if not workers:
            workers = [_StepSpec(name="worker-1", prompt=goal, capability="chat", profile="")]

        parallel_out = await self.run_parallel(
            {
                "workflow": "parallel",
                "goal": goal,
                "workers": [
                    {
                        "name": w.name,
                        "prompt": w.prompt,
                        "capability": w.capability,
                        "profile": w.profile,
                    }
                    for w in workers
                ],
                "synthesize": True,
                "allow_partial": _as_bool(payload.get("allow_partial"), default=False),
                "synthesis_capability": _text(payload.get("synthesis_capability"), default="chat"),
                "synthesis_profile": _text(payload.get("synthesis_profile")),
            }
        )
        return {
            "pattern": "orchestrator_worker",
            "goal": goal,
            "decomposition": decompose,
            "workers": parallel_out.get("workers", []),
            "final_output": parallel_out.get("final_output", ""),
        }

    def _parse_routes(self, payload: dict[str, Any]) -> list[_RouteSpec]:
        routes: list[_RouteSpec] = []
        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, list):
            return routes
        for idx, item in enumerate(raw_routes, start=1):
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name")) or f"route-{idx}"
            prompt = _text(item.get("prompt") or item.get("task"))
            if not prompt:
                continue
            routes.append(
                _RouteSpec(
                    name=name,
                    when=_text(item.get("when")),
                    prompt=prompt,
                    capability=_text(item.get("capability"), default="chat"),
                    profile=_text(item.get("profile")),
                )
            )
        return routes

    async def run_routing(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = _text(payload.get("goal") or payload.get("task") or payload.get("prompt"))
        if not goal:
            raise WorkflowExecutionError("routing workflow requires payload.goal")

        routes = self._parse_routes(payload)
        if not routes:
            raise WorkflowExecutionError("routing workflow requires payload.routes[]")

        router_cap = _text(payload.get("router_capability"), default="chat")
        router_profile = self._select_profile(
            capability=router_cap,
            preferred_profile=_text(payload.get("router_profile")),
        )

        route_desc = [
            {
                "name": r.name,
                "when": r.when,
                "capability": r.capability,
            }
            for r in routes
        ]
        route_choice_exec = await self._ask_json(
            system_prompt=(
                "You are a routing controller. Pick the single best route for the goal. "
                "Return strict JSON with route_name and reason."
            ),
            user_prompt=f"Goal:\n{goal}\n\nAvailable routes:\n{route_desc}\n",
            schema_hint={"route_name": "string", "reason": "string"},
            profile=router_profile,
            capability=router_cap,
        )
        route_choice = route_choice_exec.payload

        chosen_name = _text(route_choice.get("route_name"))
        selected = next((r for r in routes if r.name == chosen_name), routes[0])
        route_order: list[_RouteSpec] = [selected] + [r for r in routes if r.name != selected.name]
        route_attempts: list[dict[str, Any]] = []
        worker_exec: _AskJsonResult | None = None
        executed_route: _RouteSpec | None = None
        last_exc: Exception | None = None
        for route in route_order:
            selected_profile = self._select_profile(
                capability=route.capability,
                preferred_profile=route.profile,
            )
            try:
                ask = await self._ask_json(
                    system_prompt=(
                        "You are a routed worker. Execute only your specialized route instructions. "
                        "Return strict JSON with output and summary."
                    ),
                    user_prompt=(
                        f"Goal:\n{goal}\n\n"
                        f"Selected route: {route.name}\n"
                        f"Route condition: {route.when or '(unspecified)'}\n"
                        f"Route instructions:\n{route.prompt}\n"
                    ),
                    schema_hint={"output": "string", "summary": "string"},
                    profile=selected_profile,
                    capability=route.capability,
                )
                worker_exec = ask
                executed_route = route
                route_attempts.append(
                    {
                        "route": route.name,
                        "ok": True,
                        "profile": ask.profile,
                        "capability": ask.capability,
                        "fallback_used": bool(ask.fallback_used),
                        "attempt_count": len(ask.attempts),
                    }
                )
                break
            except Exception as e:
                last_exc = e
                route_attempts.append(
                    {
                        "route": route.name,
                        "ok": False,
                        "error": f"{type(e).__name__}: {e}",
                    }
                )

        if worker_exec is None or executed_route is None:
            if last_exc is not None:
                raise last_exc
            raise WorkflowExecutionError("routing workflow failed to execute any route")

        worker_resp = worker_exec.payload
        output_text = _text(worker_resp.get("output") or worker_resp.get("text"))

        return {
            "pattern": "routing",
            "goal": goal,
            "routes": [r.__dict__ for r in routes],
            "initial_route": {
                "name": selected.name,
                "when": selected.when,
                "capability": selected.capability,
                "profile": selected.profile,
            },
            "selected_route": {
                "name": executed_route.name,
                "when": executed_route.when,
                "capability": executed_route.capability,
                "resolved_capability": worker_exec.capability,
                "profile": worker_exec.profile,
            },
            "route_reason": _text(route_choice.get("reason")),
            "route_fallback_used": bool(executed_route.name != selected.name),
            "route_attempts": route_attempts,
            "final_output": output_text,
            "worker_response": worker_resp,
        }

    async def run_coding_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = _text(payload.get("goal") or payload.get("task") or payload.get("prompt"))
        if not goal:
            raise WorkflowExecutionError("coding_pipeline workflow requires payload.goal")

        max_rounds = _as_int(payload.get("max_rounds"), default=2, minimum=1, maximum=4)

        coder_capability = _text(payload.get("coder_capability"), default="chat")
        reviewer_capability = _text(payload.get("reviewer_capability"), default="chat")
        fixer_capability = _text(payload.get("fixer_capability"), default="chat")
        coder_profile = self._select_profile(
            capability=coder_capability,
            preferred_profile=_text(payload.get("coder_profile")),
        )
        reviewer_profile = self._select_profile(
            capability=reviewer_capability,
            preferred_profile=_text(payload.get("reviewer_profile")),
        )
        fixer_profile = self._select_profile(
            capability=fixer_capability,
            preferred_profile=_text(payload.get("fixer_profile")),
        )

        coder_exec = await self._ask_json(
            system_prompt=(
                "You are the coding worker. Produce the best implementation for the task. "
                "Return strict JSON with code and rationale."
            ),
            user_prompt=f"Coding task:\n{goal}\n",
            schema_hint={"code": "string", "rationale": "string"},
            profile=coder_profile,
            capability=coder_capability,
        )
        coder_resp = coder_exec.payload
        current_code = _text(coder_resp.get("code") or coder_resp.get("output") or coder_resp.get("draft"))
        if not current_code:
            raise WorkflowExecutionError("coding worker returned empty code")

        steps: list[dict[str, Any]] = [
            {
                "name": "coder",
                "capability": coder_capability,
                "resolved_capability": coder_exec.capability,
                "profile": coder_exec.profile,
                "fallback_used": bool(coder_exec.fallback_used),
                "attempt_count": len(coder_exec.attempts),
                "output": current_code,
                "summary": _text(coder_resp.get("rationale")) or "initial draft",
                "ok": True,
            }
        ]

        review_rounds: list[dict[str, Any]] = []
        passed = False
        rounds_used = 0
        for round_idx in range(1, max_rounds + 1):
            review_exec = await self._ask_json(
                system_prompt=(
                    "You are a strict code reviewer. Evaluate correctness and edge cases. "
                    "Return strict JSON with pass (boolean), issues (array of strings), and summary."
                ),
                user_prompt=f"Task:\n{goal}\n\nCandidate code:\n{current_code}\n",
                schema_hint={"pass": "boolean", "issues": ["string"], "summary": "string"},
                profile=reviewer_profile,
                capability=reviewer_capability,
            )
            review_resp = review_exec.payload
            issues = _text_list(review_resp.get("issues"))
            passed = _as_bool(review_resp.get("pass"), default=(len(issues) == 0))
            summary = _text(review_resp.get("summary"))
            rounds_used = round_idx
            review_row = {
                "round": round_idx,
                "pass": bool(passed),
                "issues": issues,
                "summary": summary,
            }
            review_rounds.append(review_row)
            steps.append(
                {
                    "name": f"reviewer-{round_idx}",
                    "capability": reviewer_capability,
                    "resolved_capability": review_exec.capability,
                    "profile": review_exec.profile,
                    "fallback_used": bool(review_exec.fallback_used),
                    "attempt_count": len(review_exec.attempts),
                    "output": summary,
                    "summary": summary or ("pass" if passed else "needs_fix"),
                    "ok": bool(passed),
                    "issues": issues,
                }
            )
            if passed:
                break

            fix_exec = await self._ask_json(
                system_prompt=(
                    "You are a coding fixer. Revise the code to address reviewer issues. "
                    "Return strict JSON with revised_code and change_summary."
                ),
                user_prompt=(f"Task:\n{goal}\n\nCurrent code:\n{current_code}\n\nReviewer issues:\n{issues}\n"),
                schema_hint={"revised_code": "string", "change_summary": "string"},
                profile=fixer_profile,
                capability=fixer_capability,
            )
            fix_resp = fix_exec.payload
            revised = _text(fix_resp.get("revised_code") or fix_resp.get("code") or fix_resp.get("output"))
            if revised:
                current_code = revised
            steps.append(
                {
                    "name": f"fixer-{round_idx}",
                    "capability": fixer_capability,
                    "resolved_capability": fix_exec.capability,
                    "profile": fix_exec.profile,
                    "fallback_used": bool(fix_exec.fallback_used),
                    "attempt_count": len(fix_exec.attempts),
                    "output": current_code,
                    "summary": _text(fix_resp.get("change_summary")) or "applied fixes",
                    "ok": True,
                }
            )

        return {
            "pattern": "coding_pipeline",
            "goal": goal,
            "profiles": {
                "coder": coder_profile,
                "reviewer": reviewer_profile,
                "fixer": fixer_profile,
            },
            "steps": steps,
            "review_rounds": review_rounds,
            "passed": bool(passed),
            "rounds_used": int(rounds_used),
            "final_output": current_code,
        }

    async def run_evaluator_optimizer(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = _text(payload.get("goal") or payload.get("task") or payload.get("prompt"))
        if not goal:
            raise WorkflowExecutionError("evaluator_optimizer workflow requires payload.goal")

        rubric = _text(payload.get("rubric")) or (
            "Correctness, completeness, actionable detail, and concise structure."
        )
        max_rounds = _as_int(payload.get("max_rounds"), default=2, minimum=1, maximum=5)

        generator_profile = self._select_profile(
            capability=_text(payload.get("generator_capability"), default="chat"),
            preferred_profile=_text(payload.get("generator_profile")),
        )
        evaluator_profile = self._select_profile(
            capability=_text(payload.get("evaluator_capability"), default="chat"),
            preferred_profile=_text(payload.get("evaluator_profile")),
        )
        optimizer_profile = self._select_profile(
            capability=_text(payload.get("optimizer_capability"), default="chat"),
            preferred_profile=_text(payload.get("optimizer_profile")),
        )

        draft_prompt = _text(payload.get("draft_prompt")) or goal
        draft_exec = await self._ask_json(
            system_prompt=("You are a generator. Produce a high-quality first draft. Return strict JSON with draft."),
            user_prompt=f"Goal:\n{goal}\n\nDraft instructions:\n{draft_prompt}\n",
            schema_hint={"draft": "string"},
            profile=generator_profile,
            capability=_text(payload.get("generator_capability"), default="chat"),
        )
        draft_resp = draft_exec.payload
        draft = _text(draft_resp.get("draft") or draft_resp.get("output"))
        if not draft:
            raise WorkflowExecutionError("generator returned empty draft")

        evaluations: list[dict[str, Any]] = []
        for round_idx in range(1, max_rounds + 1):
            eval_exec = await self._ask_json(
                system_prompt=(
                    "You are an evaluator. Score the draft against rubric and decide pass/fail. "
                    "Return strict JSON with pass (boolean), feedback, and score_0_to_10."
                ),
                user_prompt=(f"Goal:\n{goal}\n\nRubric:\n{rubric}\n\nDraft:\n{draft}\n"),
                schema_hint={"pass": "boolean", "feedback": "string", "score_0_to_10": "number"},
                profile=evaluator_profile,
                capability=_text(payload.get("evaluator_capability"), default="chat"),
            )
            eval_resp = eval_exec.payload
            passed = _as_bool(eval_resp.get("pass"), default=False)
            feedback = _text(eval_resp.get("feedback"))
            score = eval_resp.get("score_0_to_10")
            evaluations.append(
                {
                    "round": round_idx,
                    "pass": passed,
                    "feedback": feedback,
                    "score_0_to_10": score,
                }
            )
            if passed:
                return {
                    "pattern": "evaluator_optimizer",
                    "goal": goal,
                    "passed": True,
                    "rounds_used": round_idx,
                    "evaluations": evaluations,
                    "profiles": {
                        "generator": generator_profile,
                        "evaluator": evaluator_profile,
                        "optimizer": optimizer_profile,
                    },
                    "final_output": draft,
                }

            improve_exec = await self._ask_json(
                system_prompt=(
                    "You are an optimizer. Improve the draft using evaluator feedback. "
                    "Return strict JSON with revised_draft and changes."
                ),
                user_prompt=(f"Goal:\n{goal}\n\nCurrent draft:\n{draft}\n\nFeedback:\n{feedback}\n"),
                schema_hint={"revised_draft": "string", "changes": "string"},
                profile=optimizer_profile,
                capability=_text(payload.get("optimizer_capability"), default="chat"),
            )
            improve_resp = improve_exec.payload
            revised = _text(improve_resp.get("revised_draft") or improve_resp.get("draft"))
            if revised:
                draft = revised

        return {
            "pattern": "evaluator_optimizer",
            "goal": goal,
            "passed": False,
            "rounds_used": max_rounds,
            "evaluations": evaluations,
            "profiles": {
                "generator": generator_profile,
                "evaluator": evaluator_profile,
                "optimizer": optimizer_profile,
            },
            "final_output": draft,
        }


def summarize_workflow_telemetry(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    pattern = _text(result.get("pattern"), default="workflow")
    steps = result.get("steps")
    workers = result.get("workers")
    route_attempts = result.get("route_attempts")
    evaluations = result.get("evaluations")

    fallback_count = 0
    attempt_count = 0
    if isinstance(steps, list):
        for item in steps:
            if not isinstance(item, dict):
                continue
            attempt_count += int(item.get("attempt_count") or 0)
            fallback_count += 1 if bool(item.get("fallback_used")) else 0
    if isinstance(workers, list):
        for item in workers:
            if not isinstance(item, dict):
                continue
            attempt_count += int(item.get("attempt_count") or 0)
            fallback_count += 1 if bool(item.get("fallback_used")) else 0
    if isinstance(route_attempts, list):
        attempt_count += len(route_attempts)
        fallback_count += 1 if bool(result.get("route_fallback_used")) else 0

    telemetry: dict[str, Any] = {
        "pattern": pattern or "workflow",
        "step_count": len(steps) if isinstance(steps, list) else 0,
        "worker_count": len(workers) if isinstance(workers, list) else 0,
        "route_attempts": len(route_attempts) if isinstance(route_attempts, list) else 0,
        "evaluation_rounds": len(evaluations) if isinstance(evaluations, list) else 0,
        "attempt_count": int(attempt_count),
        "fallback_count": int(fallback_count),
        "rounds_used": int(result.get("rounds_used") or 0),
        "passed": bool(result.get("passed")) if "passed" in result else None,
    }
    return telemetry
