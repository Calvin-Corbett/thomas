I now have a comprehensive picture across the recent arcs. I have enough to build the prioritized seed backlog. Let me synthesize.

Below is the prioritized seed backlog — the FUEL for the loop. Ranked by Calvin-value (what he keeps raising / what's blocking him from actually using Thomas), each with WHY + source, effort, and a testable "done" signal.

---

# Thomas Improvement Backlog (loop seed) — ranked by Calvin-value

## TIER 1 — Calvin is actively blocked / keeps re-raising

**1. Canvas/visual speed — drive the ~50–146s floor toward ~20s**
WHY: Calvin's #1 repeated complaint on the canvas arc — "time doesn't matter" was said for QUALITY tuning, but speed is the standing open item flagged in EVERY canvas session. Floor is now the gpt-5.5 planner emitting detailed JSON. (src: `thomas_canvas_worker_dispatch_2026-06-26.md` — "51s floor is now the planner… push toward ~20s"; Win7 desktop still 146s)
EFFORT: M
DONE: a real chart renders end-to-end in ≤25s on 8906 (measured), conforming, no flash; complex spec (multi-panel) ≤60s.

**2. Proactive "it's done" notification reliability + the slow-task SSE drop**
WHY: Thomas only acks completion on the user's NEXT message; the announce endpoint was built (`7215abea`) but slow tasks still drop the live completion SSE with `Cannot call write() after write_eof()` so cards stick on "Executing" until reload. Calvin flagged the silent-completion gap directly. (src: canvas_worker_dispatch; openai_codex_engine_swap "KNOWN FOLLOW-UPS (b)")
EFFORT: M
DONE: dispatch a 90s+ task in browser → card flips to completed live (no reload) AND Thomas posts an unprompted done bubble, verified on Calvin's instance.

**3. The 21/136 tool-load drift on 8906 (his real server)**
WHY: Calvin's actual instance loads only 21 of 136 tool modules ("registry drift" in `_real_server_8906.log`) → the provider-native AGENT worker is broken there (over-builds, hangs in 'executing', cards stick forever). Non-visual tasks genuinely don't work on the server he runs. (src: canvas_worker_dispatch "⚠ 8906 loads only 21/136")
EFFORT: M
DONE: 8906 startup log shows full tool registry loaded; a non-visual dispatched task (e.g. "write me a haiku file") completes via the agent worker on 8906, not just the test server.

**4. Land the canvas-deterministic-render branch + commit the pile of UNCOMMITTED dev work**
WHY: Weeks of work (canvas, composer redesign, CSS cache-bust, chat.html, dispatch fixes, file-access ladder) sit UNCOMMITTED on `dev` / on `claude/canvas-deterministic-render-2026-06-27` un-pushed. Calvin's standing law: don't strand work dirty (feedback_commit_and_breakglass). Risk of loss is high. (src: nearly every recent file ends "UNCOMMITTED on dev")
EFFORT: S (mechanical, needs owner override tap)
DONE: branch pushed + owner-merged to dev, local main checkout synced, `git status` clean.

## TIER 2 — recurring frustrations with a known root cause

**5. Stale-frontend cache trap — guard so it can never silently regress**
WHY: THE multi-week "AI says UI fixed but Calvin still sees old" trap. Root-caused twice (`babe4323` JS fingerprint, then CSS `__THOMAS_WEB_BUILD__` + frozen `@import`). But the fix is a manual file-walk that a future edit can drift out of. (src: `thomas_stale_frontend_cachebust_2026-06-25.md`, `thomas_frontend_delivery_and_funnel_cli_2026-06-26.md`)
EFFORT: S
DONE: a test asserts the fingerprint hashes EVERY `js/**/*.js` + `css/**/*.css`; adding a new CSS file + not touching the walk makes the test fail (proves no drift).

**6. Organic dispatch finish — retire `should_dispatch` regex (D3/D4)**
WHY: Calvin HATES regex/keyword routing ("it always sucks", no_keyword_chat law) and explicitly said "everything ORGANIC, no regex/auto." The `surface:` param made the model declare canvas-vs-task organically, but `should_dispatch` (misclassifies 71.7%/86 of 120 tasks) + forced-dispatch regexes + brain D3/D4 + `_infer_specialist` are still in tree as DEFERRED. (src: canvas_worker_dispatch "DEFERRED (non-organic)"; chatbot_only_no_modes_law; chat_audit "Brittle routing")
EFFORT: L
DONE: give the model a constrained send_task-only dispatch path on every provider, delete `should_dispatch`; a 120-prompt matrix routes via model choice with ≥95% correct task-vs-chat, no regex in the path.

**7. Over-dispatch of short creative/inline answers**
WHY: Calvin watched "write me a haiku" dispatch to a worker when Thomas could answer inline — minor but it's the chatbot-identity boundary he cares about (assistant talks; only real work hands off). (src: canvas_worker_dispatch "OPEN: short creative text (haiku) dispatches")
EFFORT: S
DONE: trivial/short creative + factual asks answer inline (0 delegations); genuine build/research still dispatch — verified in browser.

**8. Cross-session memory persistence (memory is now Thomas's own, but session-scoped)**
WHY: Calvin: "his memory doesn't work." Fixed so the chat agent uses remember/recall inline instead of dispatching it as a task (`b581a74f`), but it currently stores in the SESSION thread — facts don't survive a new chat. He tests memory by asking across sessions. (src: canvas_worker_dispatch "LATE2 — MEMORY"; OPEN: cross-session persistence)
EFFORT: M
DONE: "remember my dog is Rex" in chat A → start chat B → "what's my dog?" → "Rex" recalled, verified in browser on his instance.

## TIER 3 — reliability / polish Calvin will hit

**9. gpt-5.5 transient reasoning stalls ("Sorry, I had trouble")**
WHY: Surfaced repeatedly in live tests — concurrent streams HANG (the very stall behind the canvas first-token timeout) and one-off "Sorry, I had trouble" reasoning errors break flows. Provider flakiness, but Calvin sees it as Thomas breaking. (src: canvas_worker_dispatch "TRANSIENT gpt-5.5 reasoning error"; "his gpt-5.5/OAuth HANGS on concurrent streams")
EFFORT: M
DONE: a transient provider error mid-stream is retried/recovered gracefully (user sees a brief retry, not a dead "Sorry"); a concurrency guard serializes streams on the OAuth path.

**10. Composer visual quality final eyeball + commit**
WHY: "Terminal, Refined" redesign + green-line fix shipped but composer's send size / mic grouping / overall look "still needs Calvin's eyes on a fresh load"; verify on his ACTUAL screen via computer-use (his explicit standing rule). (src: composer_terminal_redesign; frontend_delivery_and_funnel_cli; feedback_ui_verify_on_real_screen)
EFFORT: S
DONE: screenshot his real Chrome after hard-reload, confirm composer matches spec, get his sign-off, commit.

**11. Canvas tabs for multiple visuals**
WHY: Calvin "asked repeatedly" — deferred until single-canvas draw confirmed, which it now is. (src: canvas_worker_dispatch "OPEN/NEXT: TABS")
EFFORT: M
DONE: two visuals in one chat → two tabs in the canvas, switchable, both render; verified in browser.

**12. Settings redesign (#6 on Calvin's chat.html list)**
WHY: The last remaining item from Calvin's explicit new-chat redesign list (themes, model dropdown, canvas all done). (src: canvas_live_render "Remaining from Calvin's list: #6 Settings")
EFFORT: M
DONE: Settings surface redesigned to match the new chat aesthetic, wired to real prefs, verified in browser.

**13. Self-review loop automation for canvas quality**
WHY: Calvin asked to "SCREENSHOT the result, judge it, fix in real time" and the render→serve→Playwright→judge→fix loop worked manually; he flagged automating it as the natural next step. (src: canvas_worker_dispatch "could AUTOMATE the self-review as an agent loop")
EFFORT: M
DONE: an agent loop renders a visual, screenshots it, scores against the quality rubric, and re-dispatches fixes until it passes — no human in the loop.

## TIER 4 — infrastructure debt the loop itself will trip on

**14. The ~38 unfixed codex/evolve-loop residuals (next-tier holes)**
WHY: The self-evolving loop (the loop's own substrate) has open verification holes handed to codex: H3 (non-.py files get ZERO verification → poison pyproject/pytest-ini auto-promotes), H2 (semantic-delta strips top-level imports, sha256→md5 invisible), H4 (day-field timestamp forgery), defense-in-depth (lock `evolve_supervisor`+`evolve_corpus` in `_HARDCODED_PROTECTED_DIRS`). These are reward-hack surfaces the loop can exploit on ITSELF. (src: `thomas_evolve_loop_failclosed_learn_2026-06-22.md` — NEXT-TIER list; evolve.py:696 fail-open residual)
EFFORT: L
DONE: each hole has a known-bad corpus case that the supervisor now REJECTS (re-run the exploit → blocked); `evolve.py:696` fail-open closed (`len(verification)>0`).

**15. Headless funnel OAuth blocker — wire CLI backend so the loop can run unattended**
WHY: The funnel (Thomas's evolve engine) CANNOT run headless because openai_codex OAuth isn't persisted to disk → falls back to classic. The CLI backend (`evolve_funnel_cli_backend.py`) is built but UNWIRED. This directly blocks the loop running while Calvin is AFK. (src: `thomas_funnel_evolve_2026-06-23.md`; funnel_cli fixes in frontend_delivery file)
EFFORT: M
DONE: `thomas evolve dispatch --use-funnel --via cli` runs a full funnel session headless to completion (no OAuth fallback), produces a real verified edit.

**16. Size-debt blocking commits (monolith/growth guards)**
WHY: Real fixes have been stranded uncommitted because `chat_delegation.py` (1617>1500) + runtime JS (001=2639, 021=3391, 022=7546) exceed size ceilings → monolith_guard blocks, breakglass is a GUI tap that hangs AFK runs. The loop will hit this wall on any sizable change. (src: `thomas_health_consolidation_2026-06-21.md` "Did NOT commit — hard-blocked by size architecture")
EFFORT: L
DONE: the oversized hot files are split under the ceiling (or the ceiling consciously raised with Calvin's sign-off); a sizable change commits without a GUI breakglass hang.

---

### Cross-cutting "done" rule for EVERY item
Per Calvin's standing laws, an item is only DONE when: (a) verified on his ACTUAL running instance (system-py `-m thomas.server --port 8899` / `run_thomas_main_8906.py`), via real-browser/computer-use on his screen after a hard reload — NOT a harness or computed styles (feedback_organic_browser_testing, feedback_ui_verify_on_real_screen); and (b) committed + pushed, not left dirty (feedback_commit_and_breakglass). UI items especially: restart his server after the edit or the cache-bust fingerprint won't matter.

Source files mined: `MEMORY.md`, `thomas_canvas_worker_dispatch_2026-06-26.md`, `thomas_canvas_live_render_2026-06-26.md`, `thomas_chat_design_import_2026-06-26.md`, `thomas_stale_frontend_cachebust_2026-06-25.md`, `thomas_frontend_delivery_and_funnel_cli_2026-06-26.md`, `thomas_chatbot_only_no_modes_law.md`, `thomas_chat_audit_2026-06-17.md`, `thomas_evolve_loop_failclosed_learn_2026-06-22.md`, `thomas_funnel_evolve_2026-06-23.md`, `thomas_openai_codex_engine_swap_2026-06-15.md`, `thomas_composer_terminal_redesign_2026-06-25.md`, `thomas_health_consolidation_2026-06-21.md`, `feedback_organic_browser_testing.md`, `feedback_ui_verify_on_real_screen_2026-06-25.md`, `feedback_thomas_builds_not_claude.md`, `user_persona.md` (all under `C:\Users\corbe\.claude\projects\C--Users-corbe\memory\`).