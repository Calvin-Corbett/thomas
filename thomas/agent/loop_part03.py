                                data={
                                    "tool_id": tc_id,
                                    "tool_name": tc_name,
                                    "result": output[:4000],  # summary for event consumers
                                    "result_text": output,  # full text (not fed back to LLM)
                                    "ok": ok,
                                    "duration_ms": 0,
                                },
                                iteration=iteration,
                            )
                            quality_tool_events.append(
                                {
                                    "name": tc_name,
                                    "ok": ok,
                                    "command": "",
                                    "path": "",
                                }
                            )
                            continue

                        tc_data = {
                            "id": event.data.get("id", ""),
                            "name": event.data.get("name", ""),
                            "arguments": event.data.get("arguments", ""),
                        }
                        pending_tool_calls.append(tc_data)
                        yield AgentEvent.tool_call_end(tc_data["id"], iteration=iteration)

                    elif event.type == "error":
                        # Some providers (e.g. Codex bridge) surface errors as events.
                        err = str(event.data.get("error", "")).strip() or "LLM error"
                        llm_stream_error = err
                        yield AgentEvent.agent_error(err, iteration=iteration)

                    elif event.type == "done":
                        # Don't `break` here: exiting an `async for` early triggers an
                        # `aclose()` on the underlying async generator while it's still
                        # unwinding network I/O, which can produce noisy asyncio/httpx
                        # shutdown errors. Let it terminate naturally on StopAsyncIteration.
                        continue

                    elif event.type == "usage":
                        usage_part = self._usage_from_event_payload(event.data.get("usage"))
                        stream_usage = self._normalize_usage(
                            stream_usage["prompt_tokens"] + usage_part["prompt_tokens"],
                            stream_usage["completion_tokens"] + usage_part["completion_tokens"],
                            stream_usage["total_tokens"] + usage_part["total_tokens"],
                        )

                if llm_stream_error:
                    state.error = llm_stream_error
                    state.finished = True
                    break

            except LLMError as e:
                error_msg = str(e)
                # Detect connection errors and give a helpful message
                if "connect" in error_msg.lower() or "refused" in error_msg.lower():
                    base_url = self.llm.config.base_url
                    error_msg = f"Cannot connect to LLM at {base_url}. " f"Is Ollama running? Try: ollama serve"
                yield AgentEvent.agent_error(error_msg, iteration=iteration)
                state.error = error_msg
                state.finished = True
                break

            except (httpx_ConnectError, ConnectionError, OSError):
                base_url = self.llm.config.base_url
                error_msg = f"Cannot connect to LLM at {base_url}. " f"Is Ollama running? Try: ollama serve"
                yield AgentEvent.agent_error(error_msg, iteration=iteration)
                state.error = error_msg
                state.finished = True
                break

            # Accumulate text response
            iter_text = "".join(text_chunks)
            iter_text, suppressed = self._sanitize_assistant_text(
                iter_text,
                prompt_text=prompt_text,
                route=route,
                route_input_source=route_input_source,
                pending_tool_calls=len(pending_tool_calls),
            )
            if suppressed:
                followup_suppressed_count += 1
            if self._last_sanitize_flags.get("thought_leak"):
                thought_leak_suppressed_count += 1
            if iter_text.strip() == "Understood. How can I assist you further?":
                iter_text = "I didn't answer that. Please ask a specific question."

            # Clarification budget guardrail for action turns: avoid repeated
            # ask-back loops when the model can proceed with sensible defaults.
            is_clarifying_question = bool(not pending_tool_calls and self._looks_like_clarifying_question(iter_text))
            if is_clarifying_question:
                clarification_questions_asked += 1
            reached_clarification_cap = (
                clarification_questions_asked >= clarification_question_cap
                if full_auto_action_turn
                else clarification_questions_asked > clarification_question_cap
            )
            if (
                clarification_budget_active
                and is_clarifying_question
                and reached_clarification_cap
                and clarification_reprompt_count < 2
                and (iteration + 1) < max_iter
            ):
                clarification_reprompt_count += 1
                if full_auto_action_turn:
                    full_auto_reprompt_count += 1
                    nudge = self._full_auto_nudge(prompt_text, full_auto_reprompt_count)
                else:
                    nudge = self._assume_and_proceed_nudge(
                        prompt_text,
                        retry_index=clarification_reprompt_count,
                        question_cap=clarification_question_cap,
                        questions_seen=clarification_questions_asked,
                        route_input_source=route_input_source,
                    )
                self._conversation.append({"role": "user", "content": nudge})
                self._sync_user_message_to_intelligence(nudge)
                continue

            if buffer_text_tokens and iter_text:
                # Flush buffered text after full-auto guardrails accept it.
                yield AgentEvent.text_delta(iter_text, iteration=iteration)

            if provider_tpm_budget > 0:
                stream_prompt_now = int(stream_usage.get("prompt_tokens", 0) or 0)
                stream_prompt_delta = max(0, stream_prompt_now - stream_prompt_prev)
                if stream_prompt_delta > 0:
                    provider_prompt_window.append((time.monotonic(), int(stream_prompt_delta)))
                    stream_prompt_prev = stream_prompt_now
                    _prune_prompt_window(time.monotonic())
                    provider_prompt_tokens_last_minute = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))
                elif stream_prompt_now > stream_prompt_prev:
                    stream_prompt_prev = stream_prompt_now

            iter_prompt_now = int(stream_usage.get("prompt_tokens", 0) or 0)
            iter_prompt_spend = max(0, iter_prompt_now - int(iter_prompt_start_total))
            iter_prompt_spends.append(int(iter_prompt_spend))

            if iter_prompt_hard_cap is not None and iter_prompt_spend > int(iter_prompt_hard_cap):
                high_prompt_spend_fail_iters += 1
                runaway_guard_reason = (
                    "High prompt-token spend per iteration exceeded hard cap. "
                    "Stopping to prevent token waste and runaway budget usage."
                )
                yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
                state.error = runaway_guard_reason
                state.finished = True
                break

            benchmark_validation_ok = True
            benchmark_issue = ""
            if str(job_type or "").strip().lower() == "benchmark" and code_output_validation_enabled:
                benchmark_validation_ok, benchmark_issue, _ = _validate_benchmark_code_output(
                    prompt_text=prompt_text,
                    continuation=iter_text,
                )
            if not benchmark_validation_ok:
                code_output_guard_reprompts += 1
                code_output_guard_last_issue = str(benchmark_issue or "")
                if (iteration + 1) < max_iter:
                    guard_context = str(prompt_text or "").strip().replace("\n", " ")
                    if guard_context:
                        user_prompt = (
                            f"Original request: {guard_context}\n"
                            "Previous continuation failed code-output validation: "
                            f"{code_output_guard_last_issue}. "
                            "Return only valid Python continuation code meeting code-output requirements."
                        )
                    else:
                        user_prompt = (
                            "Previous continuation failed code-output validation: "
                            f"{code_output_guard_last_issue}. "
                            "Return only valid Python continuation code meeting code-output requirements."
                        )
                    self._conversation.append({"role": "user", "content": user_prompt})
                    self._sync_user_message_to_intelligence(user_prompt)
                    continue
                issue_error = "Code-output guard blocked completion: " f"{code_output_guard_last_issue}".strip()
                state.error = issue_error
                yield AgentEvent.agent_error(issue_error, iteration=iteration)
                state.finished = True
                break

            state.text_response += iter_text

            # If no tool calls, we're done
            if not pending_tool_calls:
                if iter_text:
                    self._conversation.append({"role": "assistant", "content": iter_text})
                    self._sync_assistant_message_to_intelligence(iter_text)
                    self._record_event("assistant_response", iter_text)
                state.finished = True
                break

            # Build assistant message with tool calls for the message history
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if iter_text:
                assistant_msg["content"] = iter_text
            else:
                assistant_msg["content"] = ""
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in pending_tool_calls
            ]
            self._conversation.append(assistant_msg)
            self._sync_assistant_message_to_intelligence(iter_text)

            # Execute tool calls (parallel when multiple), streaming each completion.
            tool_results: list[AgentEvent] = []
            tool_results_by_id: dict[str, AgentEvent] = {}
            async for result_event in self._execute_tools(pending_tool_calls, iteration):
                tc_id = str(result_event.data.get("tool_id", ""))
                tc: dict[str, Any] = {}
                for maybe_tc in pending_tool_calls:
                    if str(maybe_tc.get("id", "")) == tc_id:
                        tc = maybe_tc
                        break
                if not tc:
                    tc = {"id": tc_id, "name": result_event.data.get("tool_name", "tool"), "arguments": "{}"}

                parsed_args, _parse_err = self._parse_tool_args(tc.get("arguments"))

                yield result_event
                tool_results.append(result_event)
                tool_results_by_id[tc_id] = result_event

                args_meta = parsed_args if isinstance(parsed_args, dict) else {}
                quality_tool_events.append(
                    {
                        "name": str(tc.get("name") or ""),
                        "ok": bool(result_event.data.get("ok", False)),
                        "command": str(
                            args_meta.get("command") or args_meta.get("cmd") or args_meta.get("shell") or ""
                        )[:500],
                        "path": str(args_meta.get("path") or args_meta.get("file") or args_meta.get("filename") or "")[
                            :500
                        ],
                    }
                )

                # Truncate tool results that would dominate context
                result_text = result_event.data.get("result_text", "")
                original_len = len(result_text)
                if len(result_text) > _MAX_TOOL_RESULT_CHARS:
                    footer = f"\n\n... (truncated, {len(result_text):,} chars total. Use start_line/end_line for large files.)"
                    result_text = result_text[: _MAX_TOOL_RESULT_CHARS - len(footer)] + footer
                tool_chars_total += original_len
                tool_chars_kept += len(result_text)

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                }
                self._conversation.append(tool_msg)

                # ── message interruption check ──
                # Between tool completions, check if the user sent a new message.
                # This allows graceful cancellation mid-loop for responsive interaction.
                if self._message_queue is not None:
                    try:
                        user_interrupt = self._message_queue.get_nowait()
                        if user_interrupt is None or str(user_interrupt).strip().lower() == "stop":
                            state.user_interrupted = True
                            state.finished = True
                            yield AgentEvent(
                                type=EventType.AGENT_END,
                                data={"reason": "user_interrupted", "message": "Run cancelled by user."},
                                iteration=iteration,
                            )
                            break
                        interrupt_text = str(user_interrupt).strip()
                        if interrupt_text:
                            # Inject live follow-up user input into the active run.
                            # The next iteration will route against this updated request.
                            self._conversation.append({"role": "user", "content": interrupt_text})
                            self._sync_user_message_to_intelligence(interrupt_text)
                            yield AgentEvent(
                                type=EventType.THINKING,
                                data={"text": "Received additional user instructions. Adapting plan.\n"},
                                iteration=iteration,
                            )
                    except Exception:
                        # Handles both asyncio.QueueEmpty and queue.Empty
                        pass

                state.total_tool_calls += 1

                # Detect repeated failures
                if not result_event.data.get("ok"):
                    consecutive_failed_tool_iters += 1
                else:
                    consecutive_failed_tool_iters = 0

                if consecutive_failed_tool_iters >= 2:
                    current_signature = f"{tc.get('name', '')}:fail"
                    if current_signature == repeated_failure_signature:
                        repeated_failure_count += 1
                    else:
                        repeated_failure_signature = current_signature
                        repeated_failure_count = 1

                if repeated_failure_count >= 2:
                    yield AgentEvent.agent_error(
                        "Tool loop stability issue: "
                        f"{tc.get('name')} has failed repeatedly. Prevent token waste by stopping this loop.",
                        iteration=iteration,
                    )
                    runaway_guard_reason = (
                        "Tool loop stability issue. Stopping to prevent repeated tool-loop failure waste."
                    )
                    state.error = "Tool loop repeated failures"
                    state.finished = True
                    break

            if state.finished or state.user_interrupted:
                break

            # Context compaction: if approaching budget, compact older messages
            # instead of immediately stopping. This mirrors Claude Code behavior.
            if (
                _HAS_COMPACTION
                and iteration >= 2
                and cumulative_context_tokens >= int(hard_context_budget * 0.80)
                and cumulative_context_tokens < hard_context_budget
            ):
                try:
                    compacted = compact_conversation(
                        self._conversation,
                        target_tokens=int(hard_context_budget * 0.60),
                        preserve_recent=8,
                    )
                    old_len = len(self._conversation)
                    self._conversation = compacted
                    log.info(
                        "Context compacted: %d -> %d messages at iteration %d",
                        old_len,
                        len(compacted),
                        iteration + 1,
                    )
                except Exception as _ce:
                    log.debug("Context compaction failed: %s", _ce)

            # Runaway guard: if context is getting too big and we're doing tool loops,
            # proactively stop before we hit hard limits.
            if iteration >= 2 and cumulative_context_tokens >= hard_context_budget:
                runaway_guard_reason = (
                    f"Stopped after iteration {iteration + 1}: context approaching hard limit "
                    f"({cumulative_context_tokens:,} / {hard_context_budget:,} tokens). "
                    f"Consider smaller steps or narrower scope."
                )
                yield AgentEvent.agent_error(runaway_guard_reason, iteration=iteration)
                state.error = runaway_guard_reason
                state.finished = True
                break

        # Cleanup: Auto-capture research into library if enabled
        if prompt_text and state.text_response:
            try:
                self._auto_capture_research(
                    route=route,
                    query=prompt_text,
                    answer=state.text_response,
                    job_type=job_type,
                )
            except Exception as e:  # REVIEWED: log-and-continue — optional research auto-capture
                log.debug("Research auto-capture failed: %s", e)

        usage_after = self._session_usage_snapshot()
        usage_obj = self._usage_delta(usage_before, usage_after)
        if usage_obj["total_tokens"] <= 0 and stream_usage["total_tokens"] > 0:
            usage_obj = dict(stream_usage)
        avg_context = int(sum(iter_token_estimates) / len(iter_token_estimates)) if iter_token_estimates else 0
        token_report = self._build_token_report(
            prompt_text=prompt_text,
            usage_obj=usage_obj,
            mode=effective_mode,
            iterations=state.iteration + 1,
            peak_context_tokens=peak_context_tokens,
            avg_context_tokens=avg_context,
            memory_tokens=memory_tokens,
            tool_chars_total=tool_chars_total,
            tool_chars_kept=tool_chars_kept,
        )
        token_report["route"] = route.to_dict()
        token_report["effective_tools_policy"] = effective_tools_policy
        token_report["autonomy_level"] = int(self._autonomy_level)
        token_report["autonomy_name"] = autonomy_name
        token_report["continuity"] = {
            "route_input_source": route_input_source,
            "followup_suppressed_count": int(followup_suppressed_count),
            "thought_leak_suppressed_count": int(thought_leak_suppressed_count),
            "full_auto_reprompt_count": int(full_auto_reprompt_count),
            "clarification_question_cap": int(clarification_question_cap),
            "clarification_questions_asked": int(clarification_questions_asked),
            "clarification_reprompt_count": int(clarification_reprompt_count),
            "best_practice_gate_active": bool(best_practice_gate_active),
            "best_practice_gate_source": str(best_practice_gate_source),
            "profile_type": str(self._profile_type),
            "code_output_guard_reprompts": int(code_output_guard_reprompts),
            "code_output_guard_last_issue": str(code_output_guard_last_issue),
            "strict_issue_ownership": bool(strict_issue_ownership),
            "high_prompt_spend_fail_iters": int(high_prompt_spend_fail_iters),
        }
        token_report["token_economy"] = dict(token_economy_meta)
        token_report["skills"] = dict(runtime_skills_payload)
        if provider_tpm_budget > 0:
            _prune_prompt_window(time.monotonic())
            provider_prompt_tokens_last_minute = int(sum(max(0, int(tok)) for _, tok in provider_prompt_window))
        token_report["run_budget"] = {
            "token_economy": str(applied_token_economy),
            "mode_context_budget": int(mode_context_budget),
            "hard_context_budget": int(hard_context_budget) if hard_context_budget is not None else None,
            "emergency_context_budget": int(emergency_context_budget),
            "iteration_prompt_warn_cap": int(iter_prompt_warn_cap),
            "iteration_prompt_hard_cap": int(iter_prompt_hard_cap) if iter_prompt_hard_cap is not None else None,
            "max_iteration_prompt_spend": int(max(iter_prompt_spends) if iter_prompt_spends else 0),
            "high_prompt_spend_fail_iters": int(high_prompt_spend_fail_iters),
            "cumulative_context_tokens": int(cumulative_context_tokens),
            "runaway_guard_triggered": bool(runaway_guard_reason),
            "runaway_guard_reason": str(runaway_guard_reason or ""),
            "provider_tpm_limit": int(provider_tpm_limit) if provider_tpm_limit > 0 else None,
            "provider_tpm_budget": int(provider_tpm_budget) if provider_tpm_budget > 0 else None,
            "provider_prompt_tokens_last_minute": int(provider_prompt_tokens_last_minute),
            "provider_tpm_wait_events": int(provider_tpm_wait_events),
            "provider_tpm_wait_seconds": round(float(provider_tpm_wait_seconds), 3),
        }
        if runaway_guard_reason:
            token_report.setdefault("flags", []).append(
                {
                    "kind": "runaway_guard",
                    "severity": "high",
                    "detail": "Run was stopped by automatic token waste protection.",
                }
            )
            token_report.setdefault("suggestions", []).append(
                "Retry in a fresh chat or with tighter scope to reduce context growth."
            )
        if iter_prompt_spends and max(iter_prompt_spends) >= int(iter_prompt_warn_cap):
            token_report.setdefault("flags", []).append(
                {
                    "kind": "iteration_prompt_spend",
                    "severity": "medium",
                    "detail": (
                        "One or more iterations used unusually high prompt tokens; "
                        "review tool loops, memory scope, and mode/economy settings."
                    ),
                }
            )
            token_report.setdefault("suggestions", []).append(
                "If this repeats, narrow scope or lower memory/tool breadth to avoid oversized prompt rebuilds."
            )
        # Low-intent routes skip expensive quality-gate work (config reload,
        # retries).  Define the set once for both the config-skip and retry-skip.
        _low_intent_skip_quality = {"casual_chat", "personal_context", "assistant_meta", "general"}

        # Config validation on every message is expensive I/O.  Skip for
        # low-intent routes where quality-gate retries are disabled anyway.
        cfg_errors: list[str] = []
        cfg_unknown: list[str] = []
        if str(route.path or "") not in _low_intent_skip_quality:
            try:
                cfg_path = Path(os.environ.get("THOMAS_CONFIG") or "thomas.toml")
                loaded_cfg = load_config(cfg_path)
                cfg_errors = loaded_cfg.validate()
                cfg_unknown = list(loaded_cfg.unknown_core_keys)
            except Exception as e:  # REVIEWED: log-and-continue — config audit optional
                cfg_errors = [f"config_audit_failed: {type(e).__name__}: {e}"]

        quality_cfg = getattr(self.config, "quality", None)
        quality_enabled = bool(getattr(quality_cfg, "enabled", True))
        quality_enforce = bool(getattr(quality_cfg, "enforce", True))
        quality_max_retries = max(0, min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)))
        require_verify = bool(getattr(quality_cfg, "require_verification_for_coding", True))
        require_tests = bool(getattr(quality_cfg, "require_tests_for_code_edits", False))

        combined_quality_events = list(_quality_carry_forward_events or []) + quality_tool_events
        rules_report = evaluate_rules(
            route_path=str(route.path or ""),
            prompt_text=prompt_text,
            response_text=state.text_response,
            tool_events=combined_quality_events,
            requested_job_type=job_type,
            config_errors=cfg_errors,
            unknown_core_keys=cfg_unknown,
            require_verification_for_coding=require_verify,
            require_tests_for_code_edits=require_tests,
            require_monolith_guard_for_coding=bool(getattr(quality_cfg, "require_monolith_guard_for_coding", True)),
            strict_issue_ownership=bool(strict_issue_ownership),
            attempt=int(_quality_retry_count),
        )
        token_report["rules_of_road"] = rules_report

        issue_ownership_signals = rules_report.get("signals") or {}
        issue_ownership_blocked = bool(
            bool(issue_ownership_signals.get("strict_issue_ownership"))
            and bool(issue_ownership_signals.get("unresolved_issue_detected"))
        )

        # Quality-gate retries are for action routes only (coding, debug, etc.).
        # Low-intent routes (casual chat, greetings) should NEVER trigger a
        # quality retry — it wastes time and confuses the user.
        quality_required = not bool(rules_report.get("passed", False))
        if strict_issue_ownership:
            quality_max_retries = max(quality_max_retries, 2)
        quality_retry_enabled = strict_issue_ownership or str(route.path or "") not in _low_intent_skip_quality
        if (
            quality_required
            and _quality_retry_count < quality_max_retries
            and ((quality_enabled and quality_enforce) or strict_issue_ownership)
            and not bool(state.error)
            and quality_retry_enabled
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

        if (
            quality_required
            and strict_issue_ownership
            and issue_ownership_blocked
            and _quality_retry_count >= quality_max_retries
            and not bool(state.error)
        ):
            block_error = (
                "Issue-ownership quality gate blocked completion: "
                "user-facing text still appears to describe unresolved issues or workaround-only work."
            )
            yield AgentEvent.agent_error(block_error, iteration=state.iteration)
            state.error = block_error
            return

        # Done
        yield AgentEvent.agent_done(
            text=state.text_response,
            iterations=state.iteration + 1,
            tool_calls=state.total_tool_calls,
            usage=usage_obj,
            token_report=token_report,
        )

        # Auto-generate reusable tool from completed task
        if state.text_response and state.total_tool_calls > 0:
            try:
                from thomas.core.tool_factory import get_tool_factory

                factory = get_tool_factory()
                tool_schema = factory.create_tool_from_task(
                    task_description=prompt_text,
                    steps_taken=self._conversation[-10:],  # recent context
                    code_written=None,  # could extract from tool results
                    outcome="success" if not state.error else "error",
                )
                if tool_schema:
                    factory.register(tool_schema)
                    log.debug("ToolFactory: registered tool '%s' from task", tool_schema.name)
            except Exception as e:  # REVIEWED: log-and-continue — optional ToolFactory task capture
                log.debug("ToolFactory: failed to create tool from task: %s", e)
