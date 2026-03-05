                        "strict_primary_chat": bool(not failover_enabled_for_chat and cfg.failover.enabled),
                    },
                }
            )
            try:
                autonomy_level = int(getattr(session, "autonomy_level", 3) or 3)
            except (TypeError, ValueError):
                autonomy_level = 3
            no_human_mode = "allow" if autonomy_level >= 4 else None
            require_command_approval = bool(getattr(advanced_tools, "require_command_approval", False)) and (
                autonomy_level < 4
            )
            journal = await stream_agent_events(
                agent=agent,
                prompt=prompt,
                send=send,
                send_timing=send_timing,
                cfg=cfg,
                session=session,
                sid=sid,
                raw_user_text=raw_user_text,
                ledger=ledger,
                deps=deps,
                run_id=run_id,
                model_cfg=model_cfg,
                requested_runtime=requested_runtime,
                failover_enabled_for_chat=failover_enabled_for_chat,
                mode=mode,
                advanced_tools=advanced_tools,
                requested_job_type=requested_job_type,
                applied_token_economy=applied_token_economy,
                token_economy_meta=token_economy_meta,
                run_max_iterations=run_max_iterations,
                run_done=run_done,
                no_human_mode=no_human_mode,
                require_command_approval=require_command_approval,
                llm=llm,
                memory=memory,
                start_t=start_t,
                apply_usage_budget=_apply_usage_budget,
                normalize_usage_payload=_normalize_usage_payload,
            )
        except Exception as e:
            run_done["ok"] = False
            run_done["error"] = f"{type(e).__name__}: {e}"
            deps.task_ledger_update(
                sid,
                status="blocked",
                missing_inputs=extract_missing_inputs(run_done["error"]),
                last_progress=run_done["error"],
                source="chat.exception",
                force_event=True,
            )
            try:
                await emit_vibe("response.done", "error", detail=run_done["error"], kind="result")
                await send({"type": "error", "error": run_done["error"]})
            except Exception as send_err:
                log.warning("Failed to stream chat error payload: %s", send_err)
        finally:
            # Safety-finalize journal if it wasn't already finalized
            if journal is not None:
                try:
                    journal.finalize(
                        ok=bool(run_done.get("ok")),
                        iterations=int(run_done.get("iterations") or 0),
                        tool_calls=int(run_done.get("tool_calls") or 0),
                        error=run_done.get("error"),
                    )
                except Exception:
                    pass
            try:
                await llm.close()
            except Exception as _llm_close_err:
                log.warning("LLM client close failed: %s", _llm_close_err)
            if run_store_enabled:
                try:
                    ok_val = bool(run_done["ok"]) if run_done["ok"] is not None else False
                    run_store_mod.finalize_run(
                        run_id,
                        ok=ok_val,
                        error=None if ok_val else str(run_done.get("error") or "run failed"),
                        iterations=run_done.get("iterations"),
                        tool_calls=run_done.get("tool_calls"),
                        usage=run_done.get("usage"),
                    )
                except Exception as e:
                    log.warning("Run store finalize failed: %s", e)
            if writer is not None:
                try:
                    writer.close()
                except Exception as e:
                    log.warning("Run writer close failed: %s", e)
            # Clean up per-session interrupt queue.
            _SESSION_MSG_QUEUES.pop(sid, None)
            try:
                await resp.write_eof()
            except Exception as eof_err:
                log.warning("Failed to close chat stream cleanly: %s", eof_err)
        return resp

    app.router.add_post("/api/chat", api_chat)
