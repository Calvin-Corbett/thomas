# Known Issues & Common Problems

> **For AI agents.** Read this at the start of EVERY session. Update it when you
> discover a recurring issue that cost significant debugging time. This file is
> the project's cross-session memory for common pitfalls.
>
> Last updated: 2026-03-01 (v0.14.17).

---

## 1. "500 Server got itself in trouble" on `/api/chat`

**Symptom:** User sees `API Error 500: 500 Internal Server Error Server got itself in trouble` in the chat UI.

**Cause:** An unhandled Python exception propagated through the aiohttp middleware. The `exception_logger` middleware (app.py ~line 522) logs the full traceback to the server console.

**Diagnosis:**
1. Check the server console/terminal for `[thomas] Unhandled exception on POST /api/chat` — the traceback will be right there.
2. Common root causes:
   - **LLM backend down or misconfigured** — API key missing, model not available, provider unreachable
   - **Connection timeout** to the model provider
   - **Client disconnected** mid-stream (the `send()` function now handles this gracefully as of v0.11.60)
   - **Pydantic ValidationError** on webhook/API routes that don't validate input

**Fix:** The outer `api_chat` wrapper (line 1934) catches `Exception` and returns `HTTPInternalServerError(text="chat setup failed: ...")`. If you see the generic "Server got itself in trouble" instead, the exception is happening in a code path not covered by the wrapper. Add try/except.

**Prevention:** After ANY change to server code, always verify: `python -m thomas serve --port 0`

---

## 2. Corrupted Unicode Characters in Python Files

**Symptom:** Strings contain `â€"` or `â€™` or similar garbled text instead of em-dashes, smart quotes, etc.

**Cause:** Double-encoding of UTF-8. Happens when files are edited in tools that re-encode UTF-8 as CP1252 then back to UTF-8, or when AI generates text with smart quotes that gets mangled by the editor.

**Diagnosis:** `python -c "import re; data = open('FILE', 'rb').read(); [print(f'Line {data[:m.start()].count(b\"\\n\")+1}') for m in re.finditer(rb'\\xc3\\xa2', data)]"`

**Fix:** Replace the garbled bytes with ASCII equivalents (`-` for em-dash, `'` for smart quotes).

**Prevention:** Use ASCII dashes and quotes in Python source files. Reserve Unicode for user-facing strings only.

---

## 3. parity_compat.py Has Lazy Imports — Don't Delete Modules Without Checking

**Symptom:** CLI commands crash with `ModuleNotFoundError` after deleting a module.

**Cause:** `thomas/cli/parity_compat.py` (~2.2K lines) has lazy imports to many modules. If you delete one of those modules, CLI commands that trigger the lazy import will crash.

**Fix:** Before deleting ANY module:
```bash
grep -r "module_name" thomas/ tests/ scripts/ --include="*.py"
```
If parity_compat.py references it, stub the import or update parity_compat first.

---

## 4. Always Verify Server Boots After Structural Changes

**Rule:** After ANY change to Python files, run:
```bash
python -m thomas serve --port 0
```
This boots the server on a random port and verifies all imports, route registration, and middleware work. If it stays running (doesn't crash), it's good. Kill it after ~5 seconds.

Also run:
```bash
python -m pytest tests/test_architecture.py -x
```
This checks dependency direction, file sizes, and architectural constraints.

---

## 5. Webhook Routes Return 500 on Bad Input (Fixed v0.11.60)

**Symptom:** `POST /api/webhooks/register` returns 500 instead of 400 on invalid payload.

**Cause:** Pydantic `ValidationError` was unhandled in `webhooks_aiohttp.py`. Fixed by wrapping model construction in try/except.

**Status:** Fixed in v0.11.60. If you see similar patterns in OTHER route files, apply the same fix.

---

## 6. Frontend Caching — User Sees Old JS/CSS

**Symptom:** User reports UI behavior that doesn't match the code.

**Cause:** Browser cached old JS/CSS. The `no_cache_ui_assets` middleware helps but isn't always sufficient.

**Fix:** Tell user to press Ctrl+Shift+R (hard reload). If that doesn't work, check that the middleware is still in place (app.py `no_cache_ui_assets`).

---

## 7. NEVER Bulk-Delete Code by Pattern

**Rule:** "Gut it all" means fix what's wrong, NOT blindly delete everything matching a pattern. Always:
1. Grep for ALL references first
2. Verify nothing imports the code you're deleting
3. Test boot after deletion

This has caused production-breaking issues multiple times. See AGENTS.md.

---

## 8. `_read_json` / `_read_json_object` Can Fail on Malformed Requests

**Symptom:** 500 error on API endpoints when client sends malformed JSON.

**Diagnosis:** Check if the route wraps `_read_json()` in try/except. If not, a `json.JSONDecodeError` propagates as a 500.

**Fix:** The main `_read_json` helper in app.py should catch `JSONDecodeError` and raise `HTTPBadRequest`. Verify this is the case for any new routes you add.

---

## 9. "unknown profile" Error on Chat After Server Restart (Fixed v0.11.62)

**Symptom:** User presses Restart Server, types a message, gets `API Error 400: unknown profile: default` or similar error.

**Cause:** Two compounding bugs:
1. **Server-side:** `_api_chat_inner` raised `HTTPBadRequest` when the profile name from the UI didn't match any configured model profile, instead of falling back gracefully.
2. **Frontend init order:** `fetchModels()` ran BEFORE `refreshIdentityState()` loaded preferences, so `currentPreferences` was `null` and the saved `active_profile` was never read. The selector fell back to whatever `data.default` was, which might not match.
3. **Settings save gap:** `saveSettings()` didn't include `active_profile` in its PATCH payload, so saving settings could erase the stored profile.

**Fix (v0.11.62):**
- Server: graceful fallback chain (session profile -> config default -> first available) instead of 400 error
- Frontend: load preferences BEFORE model fetch in `loadInitialState()`
- Frontend: `saveSettings()` now includes `active_profile` and `model_id`
- Frontend: localStorage backup (`thomas_active_profile`) as triple-redundant persistence

**Prevention:** Any endpoint that resolves a profile should fallback gracefully, never hard-fail on an unknown name.

---

## 10. Saved L4 Autonomy Reverts to L3 on First Chat After Reload (Fixed v0.11.70)

**Symptom:** User sets autonomy to L4 in preferences, reloads the UI, then first chat behaves like L3 (less autonomous) even though settings still show L4 later.

**Cause:** Frontend startup loaded preferences into `currentPreferences` but did not hydrate `activeAutonomyLevel` immediately. Chat payloads always include `autonomy_level`, so the stale default `activeAutonomyLevel = 3` overrode server-side preference fallback.

**Diagnosis:**
1. Inspect outgoing `POST /api/chat` payload in browser devtools.
2. If `autonomy_level` is `3` right after reload while `/api/preferences` has `autonomy.default_level = "L4"`, this bug is present.

**Fix (v0.11.70):**
- `refreshIdentityState()` in `thomas/server/web/js/app.js` now parses `currentPreferences.autonomy.default_level` and sets:
  - `activeAutonomyLevel`
  - segmented autonomy control selection
  - `settingAutonomy` value (when available)

**Prevention:** If a client sends per-request overrides, hydrate those runtime values from saved preferences before the first request.

---

## 11. Busy Port Retry Crashes Server with "Site ... already registered" (Fixed v0.11.71)

**Symptom:** Server startup logs one or more `Port <n> busy ... retrying` messages, then crashes with:
`RuntimeError: Site <aiohttp.web_runner.TCPSite ...> is already registered in runner ...`

**Cause:** `serve_async()` created one `TCPSite` before the retry loop and reused it. In aiohttp, `site.start()` can register the site in the runner before bind completes, so a second `start()` on the same site object raises `RuntimeError`.

**Diagnosis:**
1. Occupy a local TCP port with a temporary listener.
2. Start `python -m thomas serve --port <that-port>`.
3. If the second attempt raises duplicate site registration, this bug is present.

**Fix (v0.11.71):**
- In `thomas/server/app.py:serve_async()`, create a fresh `web.TCPSite(...)` on each bind attempt.
- After a failed bind, call `await site.stop()` (best-effort) before retrying.

**Prevention:** For aiohttp bind retries, never reuse a previously failed `TCPSite` instance.

---

## 12. Memory Engine Appears "Off" Despite Being Enabled in Configurator (Fixed v0.14.17)

**Symptom:** User enables Memory Engine in Model Setup/Settings, but chats still behave like memory is not persistent. In some cases, applying Model Setup appears to do nothing.

**Cause:** Two gaps:
1. `/api/chat` did not consistently apply effective thread/global memory preferences at runtime.
2. Advanced memory flags (global/profile include toggles) were not enforced in per-run memory policy.
3. Model Setup apply silently swallowed `/api/preferences` PATCH failures and closed the modal, making failures look like dead controls.

**Diagnosis:**
1. Inspect `/api/preferences` response and confirm `memory.enabled_global` + advanced memory flags are set as expected.
2. Send a chat turn and verify server chat path resolves effective memory state for the current `session_id`.
3. In browser devtools, check Model Setup apply network response; if non-200 and no UI error, this bug is present.

**Fix (v0.14.17):**
- `thomas/server/routes/chat_aiohttp.py` now reads preferences with `thread_id=session_id` and applies effective memory enablement for each turn.
- `thomas/agent/loop_streaming.py` now honors advanced memory include toggles when setting thread memory policy.
- `thomas/server/web/js/app_runtime_primary.mjs` now surfaces Model Setup save errors and keeps modal open on failure.

**Prevention:** Any new preference control must be validated end-to-end: UI PATCH payload, server persistence, and runtime consumption in the chat loop.

---


## 13. Placeholder-Backed Source Must Carry a Completion Note

**Symptom:** A module exists on disk but only contains a placeholder banner, so later agents assume the feature is implemented when runtime is actually relying on cached bytecode or a fallback path.

**Cause:** Source placeholders were checked in without recording why they exist, what behavior still needs to land, who owns completion, or what runtime should do until the implementation is restored.

**Diagnosis:** Run `python scripts/forge/gates/placeholder_completion_policy.py`. Any placeholder-backed file missing one of `placeholder-why`, `placeholder-scope_to_finish`, `placeholder-owner`, `placeholder-exit_rule`, or `placeholder-acceptance` is still incomplete.

**Fix:** Add the required placeholder note directly in the file and make runtime fail fast or use an explicit fallback until the real source is restored.

**Prevention:** Do not leave placeholder-backed source in place without the full completion note. Thomas agent quality gates now treat missing placeholder annotations as an incomplete coding outcome.

---

## Adding New Issues

When you discover a problem that:
- Took more than 5 minutes to diagnose, OR
- Has happened before in a previous session, OR
- Could easily trip up a future agent

Add it here with:
1. **Symptom** — what the user/agent sees
2. **Cause** — why it happens
3. **Diagnosis** — how to identify it
4. **Fix** — how to resolve it
5. **Prevention** — how to avoid it in the future
