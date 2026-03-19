class AgentLoop(_AgentLoopBase):
    """Extended agent loop with main execution."""

    def _select_tools(
        self,
        prompt: str,
        policy: str = "auto",
        route: RouteDecision | None = None,
    ) -> list[dict[str, Any]] | None:
        """Select tool exposure policy with Smart Lazy Loading."""
        return select_tools(self, prompt, policy=policy, route=route)

    def _parse_tool_args(self, raw_args: Any) -> tuple[dict[str, Any] | None, str | None]:
        """Parse tool arguments with repair heuristics for weak model outputs."""
        return parse_tool_args(self, raw_args)

    async def _execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
        iteration: int,
    ) -> AsyncIterator[AgentEvent]:
        """Execute tool calls, running independent calls in parallel."""
        try:
            tool_stream = await _coerce_async_iterator(
                execute_tools(self, tool_calls, iteration),
                source="execute_tools",
            )
        except TypeError as exc:
            raise TypeError(f"Tool stream is not async iterable: {exc}") from exc

        async for event in tool_stream:
            yield event

    def _retrieve_memory(
        self,
        prompt: str,
        mode: str = "auto",
        *,
        budget_override: int | None = None,
    ) -> str:
        """Retrieve memory context for the prompt."""
        return retrieve_memory(self, prompt, mode=mode, budget_override=budget_override)

    def _apply_memory_policy(self, route: RouteDecision) -> None:
        """Apply per-turn memory policy."""
        apply_memory_policy(self, route)

    def _retrieve_library(self, prompt: str, route: RouteDecision) -> str:
        """Retrieve context from research library."""
        return retrieve_library(self, prompt, route)

    def _auto_capture_research(
        self,
        *,
        route: RouteDecision,
        query: str,
        answer: str,
        job_type: str | None = None,
    ) -> None:
        """Persist research-heavy answers into the external library."""
        auto_capture_research(self, route=route, query=query, answer=answer, job_type=job_type)

    def _record_event(self, etype: str, text: str) -> None:
        """Record an event in memory."""
        record_event(self, etype, text)

    def _capture_profile_hints(self, text: str) -> None:
        """Promote stable user hints into global pins."""
        capture_profile_hints(self, text)

    def _build_token_report(
        self,
        *,
        prompt_text: str,
        usage_obj: dict[str, int],
        mode: str,
        iterations: int,
        peak_context_tokens: int,
        avg_context_tokens: int,
        memory_tokens: int,
        tool_chars_total: int,
        tool_chars_kept: int,
    ) -> dict[str, Any]:
        """Build a comprehensive token usage report."""
        return build_token_report(
            self,
            prompt_text=prompt_text,
            usage_obj=usage_obj,
            mode=mode,
            iterations=iterations,
            peak_context_tokens=peak_context_tokens,
            avg_context_tokens=avg_context_tokens,
            memory_tokens=memory_tokens,
            tool_chars_total=tool_chars_total,
            tool_chars_kept=tool_chars_kept,
        )

    @staticmethod
    def _normalize_usage(prompt_tokens: Any, completion_tokens: Any, total_tokens: Any) -> dict[str, int]:
        """Normalize and validate token counts."""
        return normalize_usage(prompt_tokens, completion_tokens, total_tokens)

    def _session_usage_snapshot(self) -> dict[str, int]:
        """Get current session usage from LLM client."""
        return session_usage_snapshot(self)

    def _usage_from_event_payload(self, payload: Any) -> dict[str, int]:
        """Extract usage from event payload."""
        return usage_from_event_payload(payload)

    def _usage_delta(self, before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        """Calculate the difference between two usage snapshots."""
        return usage_delta(before, after)

    def _routing_input_text(self, prompt_text: str) -> tuple[str, str]:
        """Optionally augment routing input with prior assistant context."""
        return routing_input_text(self, prompt_text)

    def _input_continuity_hint(self, prompt_text: str) -> str:
        """Infer whether the user just supplied data requested in the prior turn."""
        return input_continuity_hint(self, prompt_text)

    def _sanitize_assistant_text(
        self,
        text: str,
        *,
        prompt_text: str,
        route: RouteDecision,
        route_input_source: str,
        pending_tool_calls: int,
    ) -> tuple[str, bool]:
        """Apply response hygiene: remove thought leakage + premature follow-ups."""
        return sanitize_assistant_text(
            self,
            text,
            prompt_text=prompt_text,
            route=route,
            route_input_source=route_input_source,
            pending_tool_calls=pending_tool_calls,
        )

    @staticmethod
    def _looks_like_clarifying_question(text: str) -> bool:
        """Check if text looks like a clarifying question."""
        return looks_like_clarifying_question(text)

    @staticmethod
    def _claims_execution(text: str) -> bool:
        """Heuristic detector for fabricated execution claims in plain text."""
        low = str(text or "").strip().lower()
        if not low:
            return False
        if "?" in low:
            return False
        if re.search(
            r"\b(cannot|can't|unable|don't have access|do not have access|missing access|missing credentials)\b",
            low,
        ):
            return False

        patterns = (
            r"\bi(?:'ve| have)?\s+(created|written|saved|executed|ran|launched|completed|finished)\b",
            r"\bfile\s+(saved|written|created)\b",
            r"\breport\s+(saved|written|created)\b",
            r"\bhere(?:'s| is)\s+the\s+output\b",
            r"\b\d+\s+agents?\s+running\b",
            r"\bagents?\s+(running|launched|started)\b",
        )
        return any(re.search(pattern, low) for pattern in patterns)

    @staticmethod
    def _full_auto_nudge(prompt_text: str, retry_index: int) -> str:
        """Generate nudge for Autonomy level 4."""
        return full_auto_nudge(prompt_text, retry_index)

    @staticmethod
    def _assume_and_proceed_nudge(
        prompt_text: str,
        *,
        retry_index: int,
        question_cap: int,
        questions_seen: int,
        route_input_source: str,
    ) -> str:
        """Generate nudge to assume defaults and proceed."""
        return assume_and_proceed_nudge(
            prompt_text,
            retry_index=retry_index,
            question_cap=question_cap,
            questions_seen=questions_seen,
            route_input_source=route_input_source,
        )

    async def _audit_action(
        self,
        *,
        kind: str,
        tool_call_id: str = "",
        tool_name: str = "",
        decision: str = "",
        reason: str = "",
        payload: Any = None,
    ) -> None:
        """Best-effort action audit event for tool lifecycle tracing."""
        audit = self._action_audit
        if audit is None:
            return
        try:
            await audit.log_async(
                kind=kind,
                run_id=self._run_id,
                session_id=self._session_id,
                tool_call_id=str(tool_call_id or ""),
                tool_name=str(tool_name or ""),
                decision=str(decision or ""),
                reason=str(reason or ""),
                payload=payload if payload is not None else {},
            )
        except Exception as e:  # REVIEWED: log-and-continue — optional audit logging
            log.debug("action audit failed (%s/%s): %s", kind, tool_name, e)

    async def run(
        self,
        prompt: Any,
        *,
        mode: str = "auto",
        tools_policy: str = "auto",
        token_economy: str = "optimal",
        max_iterations: int | None = None,
        job_type: str | None = None,
        _quality_retry_count: int = 0,
        _quality_carry_forward_events: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent loop, yielding events as they occur.

        The loop:
        1. Build messages with context window management
        2. Stream LLM response, yielding tokens to caller in real-time
        3. If tool calls detected, execute them (parallel when independent)
        4. Append tool results, loop back to LLM
        5. Stop on: no tool calls, max iterations, context overflow, or error
        """
        # Extract plain text for heuristics/memory even if prompt is multimodal.
        prompt_text = prompt if isinstance(prompt, str) else ""
        if isinstance(prompt, list):
            for part in prompt:
                if isinstance(part, dict) and part.get("type") == "text":
                    prompt_text += str(part.get("text", "")) + "\n"
            prompt_text = prompt_text.strip()

        # Suspicious prompt gate: if the prompt matches jailbreak/extraction patterns,
        # require Windows PIN before continuing. Abort if denied.
        try:
            from thomas.tools.windows_auth import check_prompt_suspicious, gate_suspicious_prompt

            is_suspicious, matched_pattern = check_prompt_suspicious(prompt_text)
            if is_suspicious:
                log.warning("Suspicious prompt detected (matched: %r). Requiring PIN.", matched_pattern)
                yield AgentEvent(
                    type=EventType.SECURITY_FLAG,
                    data={
                        "flag": "suspicious_prompt",
                        "matched_pattern": matched_pattern[:100],
                        "message": "This request matched a suspicious pattern. Windows PIN required to proceed.",
                    },
                )
                # Pass precomputed result — avoids running the regex a second time
                authorized = gate_suspicious_prompt(
                    prompt_text,
                    action_description="Proceed with flagged request",
                    precomputed=(is_suspicious, matched_pattern),
                    no_human_mode=os.environ.get("THOMAS_NO_HUMAN_MODE")
                    or os.environ.get("THOMAS_GUARDRAILS_NO_HUMAN_MODE")
                    or "human",
                )
                if not authorized:
                    yield AgentEvent(
                        type=EventType.AGENT_END,
                        data={
                            "reason": "suspicious_prompt_denied",
                            "message": "Request blocked: Windows PIN not entered or incorrect.",
                        },
                    )
                    return
                log.info("Suspicious prompt authorized via Windows PIN.")
        except Exception as e:  # REVIEWED: log-and-continue — gate check is optional, non-fatal
            log.debug("Suspicious prompt gate check failed (non-fatal): %s", e)

        route_input, route_input_source = self._routing_input_text(prompt_text)

        # Check conversation intelligence for multi-turn context
        is_followup = self.check_if_followup(prompt_text)
        user_is_confused = self.detect_user_confusion(prompt_text)
        if is_followup:
            # For follow-ups, try to resolve pronouns and references
            resolved_prompt = self.resolve_message_references(prompt_text)
            # Only use resolved version if it added context
            if len(resolved_prompt) > len(prompt_text):
                prompt_text = resolved_prompt

        route = self._router.decide(
            route_input,
            requested_mode=mode,
            requested_tools_policy=tools_policy,
            is_followup=is_followup,
        )
        autonomy = autonomy_spec(self._autonomy_level)
        autonomy_name = str(autonomy.name)
        effective_mode = route.mode
        applied_token_economy = normalize_token_economy_level(token_economy)
        token_economy_meta = build_token_economy_meta(token_economy, applied_token_economy)
        _budget_economy = applied_token_economy
        strict_issue_ownership = bool(
            self._non_coder_profile
            or str(self._profile_type or "").strip().lower() == "non_coder"
            or str(self._profile_type or "").strip().lower() == "non-coder"
        )
        best_practice_gate_active = bool(self._non_coder_profile) or bool(best_practice_gate_hint(prompt_text))
        best_practice_gate_source = "profile_non_coder" if bool(self._non_coder_profile) else ""
        if not best_practice_gate_source and best_practice_gate_hint(prompt_text):
            best_practice_gate_source = "prompt"

        review_quality_hint = simplified_review_default_hint(
            self._review_depth,
            non_coder_profile=bool(self._non_coder_profile),
        )
        best_practice_hint = (
            best_practice_default_hint() if bool(self._non_coder_profile) else best_practice_gate_hint(prompt_text)
        )
        code_output_validation_enabled = bool(prompt_requests_code_output(prompt_text))
        runtime_skills_context = ""
        runtime_skills_payload: dict[str, Any] = {
            "enabled": False,
            "discovered_count": 0,
            "selected_count": 0,
            "explicit_mentions": [],
            "pinned_matches": [],
            "roots": [],
            "selected": [],
        }
        # Skip skills resolution for low-intent routes — casual chat doesn't
        # need runtime skill discovery and it saves latency.
        _low_intent_skip = {"casual_chat", "personal_context", "assistant_meta", "general"}
        prompt_lower = str(prompt_text or "").lower()
        explicit_skill_hint = ("$" in str(prompt_text or "")) or ("skill " in prompt_lower)
        if str(route.path or "") not in _low_intent_skip or explicit_skill_hint:
            try:
                runtime_skills = resolve_runtime_skills(
                    self.config,
                    prompt_text=prompt_text,
                    relevance_text=route_input,
                    route_path=str(route.path or ""),
                    cwd=Path.cwd(),
                )
                runtime_skills_context = format_runtime_skills_context(runtime_skills)
                runtime_skills_payload = runtime_skills.to_event_payload()
            except Exception as e:  # REVIEWED: log-and-continue — skill discovery optional, graceful fallback
                log.warning("Runtime skills resolution failed: %s", e)
                runtime_skills_payload["error"] = f"{type(e).__name__}: {e}"
        usage_before = self._session_usage_snapshot()
        stream_usage = self._normalize_usage(0, 0, 0)

        if self._is_tool_usage_question(prompt_text):
            preserve_first, preserve_last = self._history_preserve_counts(route)
            history_token_cap = self._history_token_cap(route)
            answer = self._tool_usage_response()

            yield AgentEvent(
                type=EventType.AGENT_START,
                data={
                    "prompt": prompt_text,
                    "route": route.to_dict(),
                    "route_input_source": route_input_source,
                    "mode": effective_mode,
                    "tools_policy": "never",
                    "autonomy_level": int(self._autonomy_level),
                    "autonomy_name": autonomy_name,
                    "token_economy": token_economy_meta,
                    "library_enabled": bool(self._library is not None),
                    "skills": dict(runtime_skills_payload),
                    "history_policy": {
                        "preserve_first": int(preserve_first),
                        "preserve_last": int(preserve_last),
                        "history_token_cap": int(history_token_cap),
                    },
                },
            )

            if prompt_text:
                self._record_event("user_message", prompt_text)
                self._capture_profile_hints(prompt_text)
            self._conversation.append({"role": "user", "content": prompt})
            self._sync_user_message_to_intelligence(prompt)
            self._conversation.append({"role": "assistant", "content": answer})
            self._sync_assistant_message_to_intelligence(answer)
            yield AgentEvent.text_delta(answer, iteration=0)

            usage_obj = {
                "prompt_tokens": estimate_tokens(prompt_text),
                "completion_tokens": estimate_tokens(answer),
                "total_tokens": estimate_tokens(prompt_text) + estimate_tokens(answer),
            }
            token_report = self._build_token_report(
                prompt_text=prompt_text,
                usage_obj=usage_obj,
                mode=effective_mode,
                iterations=1,
                peak_context_tokens=usage_obj["total_tokens"],
                avg_context_tokens=usage_obj["total_tokens"],
                memory_tokens=0,
                tool_chars_total=0,
                tool_chars_kept=0,
            )
            token_report["route"] = route.to_dict()
            token_report["effective_tools_policy"] = "never"
            token_report["autonomy_level"] = int(self._autonomy_level)
            token_report["autonomy_name"] = autonomy_name
            token_report["continuity"] = {
                "route_input_source": route_input_source,
                "followup_suppressed_count": 0,
                "thought_leak_suppressed_count": 0,
                "full_auto_reprompt_count": 0,
                "clarification_question_cap": 0,
                "clarification_questions_asked": 0,
                "clarification_reprompt_count": 0,
                "best_practice_gate_active": bool(best_practice_gate_active),
                "best_practice_gate_source": str(best_practice_gate_source),
                "profile_type": str(self._profile_type),
                "code_output_guard_reprompts": 0,
                "code_output_guard_last_issue": "",
                "strict_issue_ownership": bool(strict_issue_ownership),
                "high_prompt_spend_fail_iters": 0,
            }
            token_report["token_economy"] = dict(token_economy_meta)
            token_report["skills"] = dict(runtime_skills_payload)
            cfg_errors: list[str] = []
            cfg_unknown: list[str] = []
            try:
                cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
                loaded_cfg = load_config(cfg_path)
                cfg_errors = loaded_cfg.validate()
                cfg_unknown = list(loaded_cfg.unknown_core_keys)
            except Exception as e:  # REVIEWED: log-and-continue — audit optional, sets error list
                cfg_errors = [f"config_audit_failed: {type(e).__name__}: {e}"]

            quality_cfg = getattr(self.config, "quality", None)
            combined_quality_events = list(_quality_carry_forward_events or [])
            rules_report = evaluate_rules(
                route_path=str(route.path or ""),
                prompt_text=prompt_text,
                response_text=answer,
                tool_events=combined_quality_events,
                requested_job_type=job_type,
                config_errors=cfg_errors,
                unknown_core_keys=cfg_unknown,
                require_verification_for_coding=bool(getattr(quality_cfg, "require_verification_for_coding", True)),
                require_tests_for_code_edits=bool(getattr(quality_cfg, "require_tests_for_code_edits", False)),
                require_monolith_guard_for_coding=bool(getattr(quality_cfg, "require_monolith_guard_for_coding", True)),
                strict_issue_ownership=bool(strict_issue_ownership),
                attempt=int(_quality_retry_count),
            )
            token_report["rules_of_road"] = rules_report

            quality_enabled = bool(getattr(quality_cfg, "enabled", True))
            quality_enforce = bool(getattr(quality_cfg, "enforce", True))
            quality_max_retries = max(
                0,
                min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)),
            )
            if strict_issue_ownership:
                quality_max_retries = max(quality_max_retries, 2)
            issue_ownership_signals = rules_report.get("signals") if isinstance(rules_report, dict) else {}
            if not isinstance(issue_ownership_signals, dict):
                issue_ownership_signals = {}
            issue_ownership_blocked = bool(
                bool(issue_ownership_signals.get("strict_issue_ownership"))
                and bool(issue_ownership_signals.get("unresolved_issue_detected"))
            )
            quality_required = not bool(rules_report.get("passed", False))
            if (
                quality_required
                and _quality_retry_count < quality_max_retries
                and ((quality_enabled and quality_enforce) or strict_issue_ownership)
            ):
                remediation_prompt = build_remediation_prompt(rules_report)
                if remediation_prompt:
                    retry_job_type = str(job_type or rules_report.get("job_type") or "").strip().lower() or None
                    async for retry_event in self.run(
                        remediation_prompt,
                        mode=mode,
                        tools_policy=tools_policy,
                        token_economy=applied_token_economy,
                        max_iterations=max_iterations,
                        job_type=retry_job_type,
                        _quality_retry_count=_quality_retry_count + 1,
                        _quality_carry_forward_events=combined_quality_events,
                    ):
                        yield retry_event
                    return
                if strict_issue_ownership and issue_ownership_blocked:
                    block_error = (
                        "Issue-ownership quality gate blocked completion: "
                        "user-facing text still appears to describe unresolved issues or workaround-only work."
                    )
                    yield AgentEvent.agent_error(block_error, iteration=0)
                return
            if (
                quality_required
                and strict_issue_ownership
                and issue_ownership_blocked
                and _quality_retry_count >= quality_max_retries
            ):
                block_error = (
                    "Issue-ownership quality gate blocked completion: "
                    "user-facing text still appears to describe unresolved issues or workaround-only work."
                )
                yield AgentEvent.agent_error(block_error, iteration=0)
                return

            yield AgentEvent.agent_done(
                text=answer,
                iterations=1,
                tool_calls=0,
                usage=usage_obj,
                token_report=token_report,
            )
            return

        # Mode presets (the caller can still override with max_iterations).
        if max_iterations is not None:
            max_iter = max_iterations
        elif effective_mode == "fast":
            # Fast mode should not truncate task completion. Keep the same loop
            # budget as normal mode; "fast" is handled by lighter behavior/budgets.
            max_iter = self.config.max_agent_iterations
        elif effective_mode == "thinking":
            max_iter = min(self.config.max_agent_iterations * 2, 25)
        else:
            max_iter = self.config.max_agent_iterations
        if max_iterations is None and autonomy.prefers_extended_iterations:
            if effective_mode == "fast":
                # Fast mode still needs enough room for at least one tool turn + follow-up,
                # but should not inherit very long full-auto iteration budgets.
                max_iter = max(max_iter, min(max(self.config.max_agent_iterations, 2), 6))
            else:
                max_iter = max(max_iter, min(self.config.max_agent_iterations * 3, 32))

        project_related = self._is_project_related_prompt(prompt_text)
        explicit_action = self._has_explicit_action_intent(prompt_text)
        low_intent_route = self._is_low_intent_route(route.path)
        action_route = str(route.path or "") in ("coding_task", "debug_audit", "planning", "research")
        full_auto_action_turn = bool(
            int(self._autonomy_level) == 4 and (project_related or explicit_action or action_route)
        )
        clarification_budget_active = bool(project_related or explicit_action or action_route)
        continuation_turn = bool(route_input_source == "history_augmented")
        clarification_question_cap = 2
        if clarification_budget_active:
            clarification_question_cap = 1
        if clarification_budget_active and explicit_action and int(self._autonomy_level) >= 3:
            clarification_question_cap = 0
        if continuation_turn:
            clarification_question_cap = 0 if clarification_budget_active else 1
        if full_auto_action_turn:
            clarification_question_cap = 0
        clarification_question_cap = max(0, int(clarification_question_cap))
        full_auto_reprompt_count = 0
        clarification_questions_asked = 0
        clarification_reprompt_count = 0
        effective_tools_policy = route.tools_policy
        if tools_policy == "auto" and route.tools_policy == "auto":
            if effective_mode == "fast":
                effective_tools_policy = "never"
            elif effective_mode == "thinking":
                effective_tools_policy = "always"
        if tools_policy == "auto" and low_intent_route and not explicit_action and not project_related:
            effective_tools_policy = "never"

        # API/cloud providers should always have tools available unless the
        # user explicitly disabled them. The routing heuristic was originally
        # tuned for local models where hiding tools saves context.
        from thomas.models.protocol import profile_prefers_always_tools

        if (
            tools_policy == "auto"
            and effective_tools_policy == "never"
            and profile_prefers_always_tools(self.llm.config)
            and (project_related or explicit_action)
        ):
            effective_tools_policy = "auto"
        if tools_policy == "auto" and effective_tools_policy == "never" and project_related:
            effective_tools_policy = "auto"
        if self._autonomy_level == 2 and effective_tools_policy == "always":
            effective_tools_policy = "auto"
        if autonomy.force_tools_policy in ("never", "auto", "always"):
            forced = str(autonomy.force_tools_policy)
            if forced == "always" and low_intent_route and not explicit_action and not project_related:
                # Only downgrade "always" to "never" when truly conversational
                # (no action verbs AND no project signals).
                effective_tools_policy = "never"
            else:
                effective_tools_policy = forced

        tool_specs = self._select_tools(prompt_text, policy=effective_tools_policy, route=route)

        # EMERGENCY BRAKE: Tool definition bloat.
        if tool_specs:
            hard_tool_count_cap, max_tool_spec_tokens = loop_tool_spec_budgets(
                _budget_economy,
                effective_mode,
            )
            if len(tool_specs) > hard_tool_count_cap:
                tool_specs = tool_specs[:hard_tool_count_cap]

            while len(tool_specs) > 1 and estimate_tools_tokens(tool_specs) > max_tool_spec_tokens:
                tool_specs = tool_specs[:-1]

        preserve_first, preserve_last = self._history_preserve_counts(route)
        history_token_cap = self._history_token_cap(route)
        state = LoopState()
        iter_token_estimates: list[int] = []
        cumulative_context_tokens = 0
        peak_context_tokens = 0
        tool_chars_total = 0
        tool_chars_kept = 0
        iter_prompt_spends: list[int] = []
        high_prompt_spend_fail_iters = 0
        code_output_guard_reprompts = 0
        code_output_guard_last_issue = ""
        followup_suppressed_count = 0
        thought_leak_suppressed_count = 0
        quality_tool_events: list[dict[str, Any]] = []
        consecutive_failed_tool_iters = 0
        repeated_failure_signature = ""
        repeated_failure_count = 0
        runaway_guard_reason: str | None = None
        memory_text = ""
        continuity_hint = ""
        test_visibility_hint = ""
        library_text = ""
        memory_tokens = 0
        mode_context_budget, hard_context_budget, emergency_context_budget = loop_context_budgets(
            _budget_economy,
            effective_mode,
        )
        iter_prompt_warn_cap, iter_prompt_hard_cap = loop_iteration_prompt_caps(
            _budget_economy,
            effective_mode,
        )
        provider_tpm_limit = self._provider_tpm_limit()
        provider_tpm_budget = 0
        if provider_tpm_limit > 0:
            provider_tpm_budget = max(1, int(provider_tpm_limit * self._provider_tpm_headroom()))
        provider_prompt_window: list[tuple[float, int]] = []
        provider_tpm_wait_events = 0
        provider_tpm_wait_seconds = 0.0
        provider_prompt_tokens_last_minute = 0
        stream_prompt_prev = 0

        def _prune_prompt_window(now_ts: float) -> None:
            cutoff = now_ts - _TPM_WINDOW_SECONDS
            if not provider_prompt_window:
                return
            provider_prompt_window[:] = [(ts, tok) for (ts, tok) in provider_prompt_window if ts >= cutoff]

        def _projected_wait_seconds(next_prompt_tokens: int) -> tuple[float, int, int]:
            if provider_tpm_budget <= 0:
                return 0.0, 0, 0
            now_ts = time.monotonic()
            _prune_prompt_window(now_ts)
            current_prompt = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))
            projected_prompt = current_prompt + max(0, int(next_prompt_tokens))
            if projected_prompt <= provider_tpm_budget:
                return 0.0, projected_prompt, current_prompt

            running_prompt = current_prompt
            wait_s = _TPM_WINDOW_SECONDS
            for ts, tok in provider_prompt_window:
                running_prompt -= max(0, int(tok))
                if running_prompt + max(0, int(next_prompt_tokens)) <= provider_tpm_budget:
                    wait_s = max(0.25, _TPM_WINDOW_SECONDS - (now_ts - ts))
                    break
            return wait_s, projected_prompt, current_prompt

        yield AgentEvent(
            type=EventType.AGENT_START,
            data={
                "prompt": prompt_text,
                "route": route.to_dict(),
                "route_input_source": route_input_source,
                "mode": effective_mode,
                "tools_policy": effective_tools_policy,
                "autonomy_level": int(self._autonomy_level),
                "autonomy_name": autonomy_name,
                "token_economy": token_economy_meta,
                "library_enabled": bool(self._library is not None),
                "skills": dict(runtime_skills_payload),
                "conversation_intelligence": {
                    "is_followup": is_followup,
                    "user_is_confused": user_is_confused,
                    "turn_count": self._conv_intel.turn_count,
                    "current_topic": self._conv_intel.current_topic,
                },
                "history_policy": {
                    "preserve_first": int(preserve_first),
                    "preserve_last": int(preserve_last),
                    "history_token_cap": int(history_token_cap),
                },
            },
        )

        self._apply_memory_policy(route)

        # Record user message in memory
        if prompt_text:
            self._record_event("user_message", prompt_text)
            self._capture_profile_hints(prompt_text)

        # Always retrieve memory context for continuity.
        if prompt_text:
            memory_mode = self.config.memory.mode or "auto"
            if effective_mode == "fast":
                memory_mode = "fast"
            if effective_mode == "thinking":
                memory_mode = "thorough"
            memory_text = self._retrieve_memory(
                prompt_text,
                mode=memory_mode,
                budget_override=route.memory_budget_tokens,
            )
            continuity_hint = self._input_continuity_hint(prompt_text)
            test_visibility_hint = live_test_default_hint(prompt_text)
            library_text = ""
            # Keep coding turns lean by default; reserve library context for
            # deep-thinking coding sessions and non-coding routes.
            if str(route.path or "") != "coding_task" or str(effective_mode or "").strip().lower() == "thinking":
                library_text = self._retrieve_library(prompt_text, route)
            extra_context_parts: list[str] = []
            if memory_text:
                extra_context_parts.append(str(memory_text))
            if continuity_hint:
                extra_context_parts.append(str(continuity_hint))
            if best_practice_gate_active and best_practice_hint:
                extra_context_parts.append(str(best_practice_hint))
            if code_output_validation_enabled:
                extra_context_parts.append(
                    "Return ONLY the requested output format for this task, no prose or commentary."
                )
            if review_quality_hint:
                extra_context_parts.append(str(review_quality_hint))
            if test_visibility_hint:
                extra_context_parts.append(str(test_visibility_hint))
            if library_text:
                extra_context_parts.append(str(library_text))
            memory_text = "\n\n".join([p for p in extra_context_parts if p is not None and str(p).strip()])

            memory_tokens = estimate_tokens(memory_text)

        # Add user message to conversation for history
        self._conversation.append({"role": "user", "content": prompt})
        self._sync_user_message_to_intelligence(prompt)

        for iteration in range(max_iter):
            state.iteration = iteration

            # Auto-compact conversation if approaching token budget.
            # This runs before _build_messages to avoid hard truncation.
            if iteration >= 1:
                try:
                    compact_result = await self._auto_compact_if_needed(
                        hard_cap=self._context_window,
                        threshold=0.70,
                        preserve_recent=max(6, preserve_last + 2),
                    )
                    if compact_result:
                        log.info(
                            "Auto-compacted conversation: %d -> %d tokens (saved %d)",
                            compact_result["original_tokens"],
                            compact_result["compacted_tokens"],
                            compact_result["tokens_saved"],
                        )
                except Exception as _ac_err:
                    log.debug("Auto-compaction check failed (non-fatal): %s", _ac_err)

            # Build messages with context window management
            # Only inject memory on first iteration
            mem = ""
            if iteration == 0:
                mem = memory_text
                if continuity_hint:
                    mem = (mem + "\n\n" + continuity_hint).strip() if mem else continuity_hint
                if test_visibility_hint:
                    mem = (mem + "\n\n" + test_visibility_hint).strip() if mem else test_visibility_hint
                if library_text:
                    mem = (mem + "\n\n" + library_text).strip() if mem else library_text
            messages = self._build_messages(
                state,
                memory_text=mem,
                tool_specs=tool_specs,
                include_purpose=route.include_purpose,
                preserve_first=preserve_first,
                preserve_last=preserve_last,
                history_token_cap=history_token_cap,
                route_path=str(route.path or ""),
                skills_context=runtime_skills_context,
            )
            iter_token_estimates.append(int(state.token_estimate))
            cumulative_context_tokens += int(state.token_estimate)
            peak_context_tokens = max(peak_context_tokens, int(state.token_estimate))

            if provider_tpm_budget > 0:
                while True:
                    next_prompt_estimate = int(state.token_estimate)
                    if provider_prompt_window:
                        observed_avg = int(
                            sum(max(0, int(tok)) for _, tok in provider_prompt_window)
                            / max(1, len(provider_prompt_window))
                        )
                        next_prompt_estimate = max(next_prompt_estimate, observed_avg)
                    wait_s, projected_prompt, current_prompt = _projected_wait_seconds(next_prompt_estimate)
                    provider_prompt_tokens_last_minute = int(current_prompt)
                    if wait_s <= 0:
                        break
                    if wait_s <= _TPM_MAX_AUTO_WAIT_S:
                        provider_tpm_wait_events += 1
                        provider_tpm_wait_seconds += float(wait_s)
                        yield AgentEvent.status(
                            (
                                f"Throttling {wait_s:.1f}s to avoid provider rate limit "
                                f"({projected_prompt:,}/{provider_tpm_budget:,} estimated prompt tokens/min)."
                            ),
                            iteration=iteration,
                        )
                        await asyncio.sleep(wait_s)
                        continue

                    profile_name = str(getattr(self.llm.config, "name", "") or "active-model")
                    runaway_guard_reason = (
                        "Stopped automatically to prevent provider rate-limit failure: "
                        f"projected prompt load {projected_prompt:,}/{provider_tpm_budget:,} "
                        f"tokens/min for profile '{profile_name}'. Retry in about {int(wait_s)}s."
                    )
                    yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
                    state.error = runaway_guard_reason
                    state.finished = True
                    break
                if state.finished:
                    break

            yield AgentEvent(
                type=EventType.AGENT_ITERATION,
                data={
                "iteration": iteration,
                "message_count": len(messages),
                "token_estimate": state.token_estimate,
                "context_window": self._context_window,
                "context_window_profile": str(self.llm.config.name or "").strip().lower(),
            },
                iteration=iteration,
            )

            # Collect this iteration's response
            text_chunks: list[str] = []
            pending_tool_calls: list[dict[str, Any]] = []
            # Always buffer text tokens so the sanitization pass runs before
            # anything reaches the client.  This prevents internal-reasoning
            # leakage, tool-artifact noise, and robotic-opener pollution on
            # *every* route — not just the subset we previously enumerated.
            buffer_text_tokens = True
            iter_prompt_start_total = int(stream_usage.get("prompt_tokens", 0) or 0)

            try:
                llm_stream_error: str | None = None
                await _ensure_llm_hardened_client(self.llm)
                llm_stream = await _coerce_async_iterator(
                    self.llm.stream_chat(messages, tool_specs),
                    source="LLMClient.stream_chat",
                )

                async for event in llm_stream:
                    if event.type == "thinking":
                        # Forward thinking/reasoning tokens to the stream
                        yield AgentEvent(
                            type=EventType.THINKING,
                            data={"text": event.data.get("text", "")},
                            iteration=iteration,
                        )

                    elif event.type == "token":
                        text = event.data.get("text", "")
                        text_chunks.append(text)
                        if not buffer_text_tokens:
                            yield AgentEvent.text_delta(text, iteration=iteration)

                    elif event.type == "tool_call_start":
                        tc_id = event.data.get("id", "")
                        tc_name = event.data.get("name", "")
                        yield AgentEvent.tool_call_start(tc_id, tc_name, iteration=iteration)

                    elif event.type == "tool_call_delta":
                        tc_id = event.data.get("id", "")
                        delta = event.data.get("delta", "")
                        if tc_id and delta:
                            yield AgentEvent.tool_call_args_delta(tc_id, delta, iteration=iteration)

                    elif event.type == "tool_call_end":
                        # Codex app-server executes tools itself; treat tool_call_end as a tool result
                        # passthrough (do not execute via Thomas's tool registry).
                        if self.llm.config.provider == "codex" and "output" in event.data:
                            tc_id = str(event.data.get("id", ""))
                            tc_name = str(event.data.get("name", ""))
                            output = str(event.data.get("output", ""))
                            exit_code = event.data.get("exit_code")
                            tool_chars_total += len(output)
                            tool_chars_kept += len(output)

                            ok = True
                            if exit_code is not None:
                                try:
                                    ok = int(exit_code) == 0
                                except (ValueError, TypeError):
                                    ok = False

                            await self._audit_action(
                                kind="tool_action_result",
                                tool_call_id=tc_id,
                                tool_name=tc_name,
                                decision="EXECUTED" if ok else "FAILED",
                                payload={
                                    "provider": "codex",
                                    "ok": ok,
                                    "exit_code": exit_code,
                                    "output_preview": output[:1000],
                                },
                            )

                            yield AgentEvent.tool_call_end(tc_id, iteration=iteration)
                            yield AgentEvent(
                                type=EventType.TOOL_RESULT,
