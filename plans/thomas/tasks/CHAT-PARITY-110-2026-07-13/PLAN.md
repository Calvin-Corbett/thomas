# PLAN for CHAT-PARITY-110-2026-07-13

- Owner: codex-root-parity-110
- Status: complete
- Updated At: 2026-07-13T22:15:36+00:00
- Scope: CHANGELOG.md,plans/thomas/chatgpt_parity/BONUS_SCORECARD.md,plans/thomas/chatgpt_parity/CAPABILITY_RUBRIC.json,plans/thomas/chatgpt_parity/GAP_LEDGER.md,plans/thomas/chatgpt_parity/latest_evidence.jsonl,plans/thomas/chatgpt_parity/latest_scorecard.json,plans/thomas/chatgpt_parity/RUBRIC.md,tests/prompt_pack/test_p097_plugin_package_bootstrap.py,tests/prompt_pack/test_p098_plugin_manifest_schema.py,tests/prompt_pack/test_p102_plugin_install_from_local_path.py,tests/prompt_pack/test_p103_plugin_uninstall_cleanup.py,tests/stress/chatgpt_parity_artifact_probes.py,tests/stress/chatgpt_parity_data_probes.py,tests/stress/chatgpt_parity_document_probes.py,tests/stress/chatgpt_parity_image_probes.py,tests/stress/chatgpt_parity_loop.py,tests/stress/chatgpt_parity_memory_probes.py,tests/stress/chatgpt_parity_probes.py,tests/stress/chatgpt_parity_runtime_probes.py,tests/test_action_receipt.py,tests/test_agent_loop_memory_and_tokens.py,tests/test_chat_canvas_live_preview.py,tests/test_chat_delegation_artifact_verification.py,tests/test_chatgpt_parity_loop.py,tests/test_deliverable_ranking.py,tests/test_email_calendar_idempotency.py,tests/test_llm_codex_tool_result_pairing.py,tests/test_memory_fabric_v2.py,tests/test_memory_layers.py,tests/test_openai_codex_oauth.py,tests/test_orchestrator_brain_coverage.py,tests/test_plugin_runtime_loader.py,tests/test_realtime_ws.py,tests/test_reasoning_specialist_streaming.py,tests/test_scheduler.py,tests/test_server_chat_v2_helpers.py,tests/test_server_chat_v2_max_mode.py,tests/test_server_local_projects_routes.py,tests/test_server_memory_contradictions_api.py,tests/test_server_settings_page.py,thomas/agent/loop_streaming.py,thomas/chat/memory_layers.py,thomas/cli/commands/plugins/p097_plugin_package_bootstrap.py,thomas/core/action_receipt.py,thomas/core/llm_streaming_codex.py,thomas/core/scheduler.py,thomas/marketplace/orchestrator/brain.py,thomas/marketplace/specialists/reasoning.py,thomas/memory/autonomy.py,thomas/memory/v2/db.py,thomas/memory/v2/fabric_core.py,thomas/memory/v2/fabric_retrieval.py,thomas/plugins/p097_plugin_package_bootstrap.py,thomas/plugins/p098_plugin_manifest_schema.py,thomas/plugins/p102_plugin_install_from_local_path.py,thomas/plugins/p103_plugin_uninstall_cleanup.py,thomas/server/app_routes_init.py,thomas/server/chat_delegation_artifact_verification.py,thomas/server/chat_delegation_runner.py,thomas/server/chat_delegation_worker_config.py,thomas/server/routes/chat_v2.py,thomas/server/routes/core_aiohttp.py,thomas/server/routes/deliverable_aiohttp.py,thomas/server/routes/local_projects_aiohttp.py,thomas/server/routes/local_projects_helpers_aiohttp.py,thomas/server/routes/memory_aiohttp.py,thomas/server/routes/openai_codex_aiohttp_helpers.py,thomas/server/web/chat.html,thomas/server/web/js/model_settings_dropdown.js,thomas/server/web/settings.html,thomas/server/web/settings.script01.js,thomas/tools/email_calendar.py,thomas/tools/email_operations.py,thomas/tools/voice.py

## Summary

Bring the local Thomas experience to verified current-ChatGPT capability parity without weakening the fail-closed rubric, then add a separate ten-point live-browser evidence layer.

## Approach

- Close every failing capability family across chat, models, reasoning, file access, projects, privacy, memory, plugins, voice, and interactive artifacts.
- Run the full parity loop against the signed-in ChatGPT/Codex provider and require all 14 families to reach tier 4.
- Exercise the real local UI in a headed browser, including persistence, unavailable-model honesty, My Stuff, voice, Canvas, network failures, and console errors.
- Run the focused and closeout regression suites, lint, whitespace checks, and repository commit gates.

## Outcome

- Base parity: 100/100, 14/14 families at tier 4, 74/74 checks, and zero critical failures.
- Independent browser evidence: +10/10, for a reported total of 110/100 without rubric inflation.
- Release: Thomas 0.18.0 committed locally as `c1c22785328b90655cfe85e482e72c048e138555`.
