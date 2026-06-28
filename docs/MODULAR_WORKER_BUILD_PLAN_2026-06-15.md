# Modular Provider-Agnostic Worker — Build Plan (2026-06-15)

> Turnkey plan from the modular-worker workflow. Engine already flipped to openai_codex (live). This is the worker rewire so the WORKER uses Thomas tools via ANY configured provider.

I now have everything I need. The findings are accurate against the live code. Here is the synthesized build plan.

---

# Build Plan: Provider-Agnostic Worker (one engine, config-selected provider)

## 0. The core insight (what the findings prove)

There are **two seams** and they are already 90% provider-agnostic. The remaining work is *deleting a fork*, not building parity:

- **LLM seam** â€” `LLMClient.stream_chat(messages, tools)` already dispatches on `config.provider` and re-emits ONE normalized `StreamEvent` set. `anthropic`, `openai`/`openai_compat`/`ollama`/`local`, and `openai_codex` all honor Thomas tool schemas. **Only the legacy `codex` (CodexBridge) provider forks** â€” it throws away Thomas's tool schemas and runs Codex's own native sandbox toolset.
- **Worker seam** â€” `thomas/server/chat_delegation.py` hardwires the background worker to that *one* forked provider: `_ensure_bridge` always builds `CodexBridge`, gates readiness on Codex OAuth, and `_run_provider_native_worker` iterates `bridge.chat(...)`.

The whole job: **make the worker drive the standard `AgentLoop` + configured `LLMClient` + full `ToolRegistry`** (the same engine the CLI and chat already use), so the worker inherits provider-agnosticism for free. The CodexBridge worker path becomes one of N providers â€” and `gpt-5.5`/`openai_codex` runs through the *exact same* loop as the local model.

This is reuse, not rebuild: `AgentLoop`, `_build_tools`, `_build_memory`, `LLMClient`, the `_DelegationEmitter`, `task_bot_runtime`, `derive_task_title`, the deliverable-serving routes, and the workspace creator are all kept verbatim. Only the ~90 lines that *are* the Codex fork (`_ensure_bridge`, `_start_provider_native_delegation`, `_run_provider_native_worker`) get swapped for ~150 lines that drive `AgentLoop` and map its events to the *identical* runtime updates.

---

## 1. Modular worker design

**One file: `thomas/server/worker_runtime.py`** (new). It exposes one coroutine the delegation layer calls:

```
async def run_agent_worker(
    app, *, execution_id, prompt, instructions, work_dir,
    session_id, bot, specialist_id, emitter, repo_root,
    profile=None, autonomy_level=4,
) -> None
```

Internally it does exactly what `_run_chat` (the canonical headless template, `thomas/cli/_commands_base.py:296`) does, plus eventâ†’runtime mapping. Step by step, reusing existing helpers:

1. **Resolve the model (config-driven, provider-blind).**
   `profile = profile or _resolve_default_model_pair(cfg, app)` (canonical helper `chat_request_setup.py:61`, which respects Calvin's persisted local-model pref via `resolve_effective_model`). Then `model_cfg = _model_cfg_with_secrets(cfg, profile, cfg.models[profile])` (`app_middleware_handlers.py:456`) â€” this is the single function that embeds API keys AND handles `openai_codex` OAuth token resolution. **No provider branching here** â€” that's the point.

2. **Build the LLMClient (provider-agnostic by construction).**
   `llm = LLMClient(model_cfg, fallback_configs=_failover_cfgs_with_secrets(cfg, profile), failover_enabled=cfg.failover_enabled, ...)` (`llm_client.py:94`). Provider dispatch lives entirely inside this object.

3. **Build a FRESH, workspace-rooted ToolRegistry â€” the full surface.**
   Do **not** reuse `app[APP_TOOLS]` (it's sandboxed to the repo â€” the exact guardrail the Codex worker dodged by running in `~/.thomas/workspaces/<id>`). Instead:
   ```
   run_cfg = dataclasses.replace(cfg, tools=dataclasses.replace(cfg.tools,
       sandbox_root=str(work_dir), allow_shell=True))
   tools = _build_tools(run_cfg)          # full registry: fs/shell/git/diff/code-search/ssh/domain/notebook/plugins
   ```
   `_build_tools` (`_commands_base.py:218`) binds every filesystem/shell tool to `sandbox_root` **at registration** (`filesystem.py:756`, `shell.py:203`), so the whole toolset is confined to the workspace. This reproduces the bridge's `cwd=work_dir` confinement with Thomas's *own* tools instead of Codex's native ones.

4. **Run the standard AgentLoop with the FULL registry (the opposite of chatbot-only).**
   ```
   agent = AgentLoop(run_cfg, llm, tools,
       system_prompt=instructions,        # the existing work_dir instructions string
       memory=app.get(APP_MEMORY),
       thread_id=execution_id, run_id=execution_id, session_id=session_id,
       autonomy_level=autonomy_level)     # 4 = full-auto, no_human_mode, extended budget
   ```
   The chat path passes `chat_tools=[]` on purpose (chatbot-only law). The worker passes the **populated registry** â†’ `select_tools` returns real tool specs â†’ the loop does real ReAct tool work. **The loop executes tools itself**; the worker only consumes events.

5. **Map AgentEvents â†’ the SAME `task_bot_runtime` + emitter calls** the Codex worker used (drop-in event translation, see Â§1b). Template to copy: `chat_plan_mode.py:_run_agent_capture` (server-context AgentLoop consuming the full event stream).

6. **`finally: await llm.close()`** (and don't close shared `app[APP_MEMORY]`). The Codex path never had an httpx client to leak; the new path does â€” `chat_helpers.py:482` is the reference for closing it.

### 1b. Event map (provider-blind â€” the whole reason this works)

| AgentEvent (`thomas/core/events.py`) | Existing runtime/emitter action (unchanged) |
|---|---|
| `TEXT_DELTA` | append `data['text']` to `result_text_parts` |
| `TOOL_CALL_START` / `TOOL_START` | `tools_used.append(name)`; `update_execution(progress_summary=f"Using {name}â€¦", force=True)` + `emitter.progress(...)` |
| `TOOL_RESULT` | `update_execution(progress_summary=f"Finished {name}; continuing.")` + `emitter.progress(...)` |
| `AGENT_DONE` | prefer `data['text']` â†’ `_build_result_summary(...)` â†’ `complete_execution(...)` + `emitter.completed(...)` |
| `AGENT_ERROR` | `raise RuntimeError(data['error'])` into the existing `except` â†’ `fail_execution(...)` + `emitter.failed(...)` |

Lifecycle transitions (`classified â†’ queued â†’ claimed â†’ executing`, lines 468â€“495) and `result_text_parts`/`tools_used` accumulation stay **byte-for-byte identical**. Only the producer of the events changes (AgentLoop instead of `bridge.chat`). Every provider â€” local, `openai_codex`, `anthropic` â€” emits this same event set, so the worker is provider-blind.

---

## 2. Exact files to create/change (ordered, minimal)

1. **CREATE `thomas/server/worker_runtime.py`** â€” `run_agent_worker(...)` per Â§1. ~150 lines. Imports `AgentLoop`, `LLMClient`, `_build_tools`, `_resolve_default_model_pair`, `_model_cfg_with_secrets`, `_failover_cfgs_with_secrets`. This is the entire new engine.

2. **CREATE `thomas/models/worker_overrides.py`** â€” the per-model override table + applier (Â§3). ~80 lines, pure data + two small functions. Lives in `thomas/models/` beside `protocol.py` and `chat_capabilities.py` (their established home for provider-aware policy).

3. **EDIT `thomas/server/chat_delegation.py`** â€” the swap (the only edit to existing logic):
   - **Delete** `_coerce_bridge` (130), `_ensure_bridge` (140â€“181), `_start_provider_native_delegation` (443â€“530), `_run_provider_native_worker` (533â€“628). Remove the `APP_CODEX_BRIDGE` import.
   - **Rename** `_start_provider_native_delegation` â†’ `_start_agent_worker_delegation`; keep its body **verbatim** through line 504 (lifecycle transitions + `_ensure_task_workspace` + the `instructions` string), then replace the `bridge`/`asyncio.create_task(_run_provider_native_worker(...))` tail with `asyncio.create_task(run_agent_worker(app, ...))`. Pass `app` through (it has APP_CONFIG/APP_SECRETS/APP_MEMORY).
   - **In `start_background_delegation`** (317): delete `bridge = await _ensure_bridge(app)` and the `if bridge is not None:` branch (374â€“387). Readiness is now "is a model configured" (always true) â€” call `_start_agent_worker_delegation(app, ...)` directly; keep `_start_task_manager_delegation` as the existing fallback. Change `actor="codex-bridge"` â†’ `actor="thomas-worker"` in the create/update calls (cosmetic; preserves audit semantics).

4. **EDIT `thomas/server/chat_v2.py`** (call site, ~583/598)** â€” thread the session's chosen `profile`/`model_id` into `start_background_delegation` so the worker uses the *same* model the chat is on (today only app/session/prompt/mode are passed â†’ worker silently used the global default). Add `profile=...` param to `start_background_delegation` and forward it.

5. **EDIT tests** â€” `tests/test_codex_bridge_usage.py` and any Codex-worker tests assert `bridge.chat` is called; update to assert `run_agent_worker` drives an AgentLoop. Add the new verification test (Â§4).

6. **DO NOT TOUCH** (reused as-is, confirms reuse-over-rebuild): `deliverable_aiohttp.py` (workspace HTML serving is impl-independent), `_DelegationEmitter`, `_normalize_record`/`deliverable_url`, `_build_result_summary`, `task_bot_runtime.*`, `_ensure_task_workspace`, `derive_task_title`, `AgentLoop` and all of `thomas/agent/`, `LLMClient` and `thomas/core/llm_*`. **Do NOT delete `CodexBridge` / `thomas/marketplace/codex/` yet** â€” see Â§5 retirement.

---

## 3. Per-model override mechanism (thin overrides, no core fork)

A single declarative table keyed by `(provider, model)`, applied at the **three existing injection edges** the loop already has â€” never by forking the core. `worker_overrides.py`:

```python
WORKER_OVERRIDES = {
    # gpt-5.5 / openai_codex â€” Calvin's first tuning target
    ("openai_codex", "gpt-5.5"): ModelOverride(
        reasoning_effort="high",            # -> request_overrides / ModelConfig
        prompt_suffix=None,
        tool_deny=set(),                    # full toolset
        max_iterations=40,
        request_overrides={},
    ),
    ("openai_codex", None): ModelOverride(reasoning_effort="medium", max_iterations=30),
    # local sandbox model â€” smaller context, prune heavy tools, firmer nudge
    ("ollama", None): ModelOverride(
        prompt_suffix="\nUse one tool at a time. Verify each file write before continuing.",
        tool_deny={"ssh", "notebook"},
        max_iterations=20,
    ),
}

def resolve_override(model_cfg) -> ModelOverride:
    p = norm(model_cfg.provider); m = model_cfg.model
    return WORKER_OVERRIDES.get((p, m)) or WORKER_OVERRIDES.get((p, None)) or ModelOverride()
```

Applied at the loop's **already-existing seams** (zero changes to `stream_chat`, the `StreamEvent` contract, or dispatch):

- **Prompt tweaks** â†’ append `prompt_suffix` to the `instructions` system prompt before constructing `AgentLoop`.
- **Tool tweaks** â†’ after `_build_tools`, drop `tool_deny` names from the registry (or pass through `select_tools`, `loop_tools.py:32`, the canonical tool-subset point).
- **Limit/sampling tweaks** â†’ `max_iterations` to `agent.run(prompt, max_iterations=...)`; `reasoning_effort` onto the `replace`'d `model_cfg`; `request_overrides` to the `LLMClient(request_overrides=...)` channel (`llm_client.py:104`) which already feeds `_build_openai_request`/`_build_anthropic_request`.

Tune per model during testing by editing one dict entry. A model with no entry runs the unmodified loop (`ModelOverride()` is all-defaults) â€” so adding a provider needs **zero** override work; overrides are purely opt-in polish. This consolidates the scattered `profile_prefers_always_tools` / inline `provider==...` checks into one table without changing them yet (they keep working; the table is additive).

---

## 4. Verification â€” prove provider-agnosticism with the SAME worker

The proof is: **run `run_agent_worker` unchanged against two providers and confirm a Thomas registry tool executed in each.** A Thomas tool executing (not a Codex-native shell) is the signal that we're on the shared path, not a fork.

**4a. Local model (sandbox-verifiable now, no token):**
```
$env:THOMAS_DEFAULT_MODEL = "<local ollama profile>"
python -m pytest tests/test_agent_worker_parity.py::test_worker_local -q
```
The test: builds a temp `work_dir`, calls `run_agent_worker(app, prompt="Create hello.txt containing 'hi' in your workspace.", ...)`, asserts (1) a `TOOL_RESULT`/`TOOL_START` for a Thomas filesystem tool (`fs_write`/`write_file`) was observed, (2) `work_dir/hello.txt` exists with the content, (3) `complete_execution` ran with a real summary. Capture events via a list-collecting emitter stub. This runs fully offline.

**4b. openai_codex / gpt-5.5 (Calvin's live token):**
```
$env:THOMAS_DEFAULT_MODEL = "chatgpt"   # the openai_codex profile
python -m pytest tests/test_agent_worker_parity.py::test_worker_openai_codex -q
```
Same assertions, same worker code, different profile â†’ token resolved via `_model_cfg_with_secrets` OAuth path. **Windows note:** if the profile routes to a `codex`/`openai_codex` provider you need the Proactor event loop (`_repl_needs_codex_event_loop`, `_commands_base.py:57`) â€” the test must set it or run under the server's loop policy.

**4c. The equality assertion (the actual parity proof):** parametrize ONE test over `["local", "openai_codex"]` so the identical `run_agent_worker` call body is exercised for both; both must reach `AGENT_DONE` with â‰¥1 Thomas-registry `TOOL_RESULT`. Green on both = provider-agnostic, no per-provider code path. Also run the local case live through chat (`mode=max`, prompt "make me a snake game") and confirm a deliverable HTML appears via `deliverable_url` â€” end-to-end, real browser-openable artifact, same as the Codex worker produced.

---

## 5. Composition with the chatbot-only law + codex-bridge retirement

**Chatbot-only law is *strengthened*, not threatened.** The law (`reasoning.py:22` `THOMAS_CHATBOT_SYSTEM_PROMPT`, guarded by tests; chat passes `chat_tools=[]` at `chat_request_execution.py:268`) says: **chat talks, reads, reports â€” never builds.** This plan keeps that boundary exactly. The split becomes crisp and symmetric:

- **Chat surface** = `AgentLoop` with `tools=[]` â†’ conversational only. Unchanged.
- **Worker** = the *same* `AgentLoop` with the **full** registry â†’ does the tool work, in an isolated workspace.

Same engine, opposite tool list â€” that's the cleanest possible expression of "chat talks; worker does the work." It also removes the chat-path codex special-case (`reasoning.py:152` forces `tools=None` for codex because handing the bridge any tool turns the chatbot into a repo-cwd coding agent). Once the worker no longer uses the bridge, that defensive fork is no longer load-bearing (track removing it as cleanup, not a blocker).

**Codex-bridge retirement (staged, reversible):**
1. **Now:** worker stops calling `CodexBridge`. `openai_codex` (the project's already-default provider, `config.py:786`) carries gpt-5.5 through the shared tool loop. Bridge code stays in-tree but unreferenced by the worker.
2. **After 4a+4b green:** delete the `codex` provider's special-casing in `loop_execution.py:836` (the `provider=='codex'` tool_call_end passthrough) and `reasoning.py:152`, since nothing reaches them.
3. **Final (separate PR, Calvin's call):** delete `thomas/marketplace/codex/bridge.py` + `provider.py` and the `'codex'` branch in `_stream_current_provider`. Keep `openai_codex` â€” it's the real, tool-honoring ChatGPT path. Retiring the *bridge* is not retiring ChatGPT.

---

## 6. Honest risks

1. **`os.chdir` / cwd is process-global.** The loop reads `os.getcwd()` for the system prompt and the guarded runner (`loop_core.py:357`, `loop_tool_exec.py:425`). If you `os.chdir(work_dir)`, **concurrent workers in the same process race.** Mitigation: rely on `sandbox_root` binding at tool registration (which is per-registry, NOT global) for confinement, and make the `instructions` string name `work_dir` explicitly so the prompt is correct without chdir. If a guarded-runner path still needs real cwd isolation, run each worker in its own subprocess. **Decide this before shipping** â€” the multi-agent reality in MEMORY means concurrent workers are likely.
2. **Guarded-tool-runner / autonomy.** Codex auto-approved everything (`danger-full-access`). The new path must run unattended: set `autonomy_level=4` (â†’ `no_human_mode='allow'`, `loop_tool_exec.py:430`) and omit `guarded_tool_runner` (or pass a permissive one) so the worker can actually write files. The background guarded path isn't fully audited â€” verify a write tool isn't silently blocked under autonomy 4 before declaring done.
3. **LLMClient leak.** `repl_background.py` does NOT close the client; you MUST `await llm.close()` in `finally`. Background workers are long-lived and many â€” a leaked httpx client per task is a real resource bug.
4. **Local-model tool reliability.** Provider-agnostic â‰  equal quality. A small local model may loop, mis-call tools, or never terminate. The `max_iterations` override and per-model `prompt_suffix` are the mitigation, but **"no quality loss" is aspirational for weak local models** â€” set honest expectations: parity means *same path and same tools*, not *same competence*. gpt-5.5 is the quality bar; local is the always-available floor.
4. **Model/profile threading gap.** Today `chat_v2.py` doesn't pass the session's chosen model into delegation (Â§2.4). Until that edit lands, the worker uses the global default and "the worker matches my chat model" won't hold. Small but required for the UX to be honest.
5. **`tool_factory.GeneratedTool.to_openai_spec` is a second serializer** (`tool_factory.py:76`) parallel to `ToolSpec.to_openai`. If dynamically generated tools enter the worker registry, schema drift between the two is a latent bug. Low likelihood, worth a note.
6. **Startup cost.** `_build_tools` runs `register_all_optional_tools` + plugin-bridge registration, which may have heavy import-time side effects. Fine for the CLI; a high-throughput worker may want a pruned registry (overlaps with the per-model `tool_deny` mechanism â€” use it).

---

### Key files
- Create: `C:\Users\corbe\Thomas\thomas\server\worker_runtime.py`, `C:\Users\corbe\Thomas\thomas\models\worker_overrides.py`, `C:\Users\corbe\Thomas\tests\test_agent_worker_parity.py`
- Edit: `C:\Users\corbe\Thomas\thomas\server\chat_delegation.py` (delete bridge funcs 130â€“181/443â€“628, swap worker tail), `C:\Users\corbe\Thomas\thomas\server\chat_v2.py` (thread profile, ~583/598), `C:\Users\corbe\Thomas\tests\test_codex_bridge_usage.py`
- Reuse verbatim: `thomas\agent\loop.py` + `loop_core.py`, `thomas\cli\_commands_base.py` (`_build_tools` 218, `_build_memory` 265, `_run_chat` 296 template), `thomas\core\llm_client.py` (94), `thomas\server\app_middleware_handlers.py` (`_model_cfg_with_secrets` 456), `thomas\server\routes\chat_request_setup.py` (`_resolve_default_model_pair` 61), `thomas\server\routes\chat_plan_mode.py` (`_run_agent_capture` template), `thomas\server\routes\deliverable_aiohttp.py`, `thomas\core\events.py`
- Retire last (separate PR): `thomas\marketplace\codex\bridge.py` + `provider.py`, `loop_execution.py:836` codex passthrough, `reasoning.py:152` codex tool-block