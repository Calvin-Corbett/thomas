# Thomas Review Action Plan

Created: 2026-03-20
Author: Claude (Cowork review session)
Status: Draft — awaiting Calvin's approval before any agent executes

---

## Item 1: Domain Modules — Marketplace Boundary Signal

**What it is:** Thomas has ~73 domain modules (agriculture, blockchain, physics, etc.) that are marketplace inventory, not core runtime. Every new AI agent that opens the repo misreads them as bloat and either tries to delete them or judges the project negatively because of them.

**Root cause:** There is no clear signal separating marketplace content from core runtime. An agent scanning `thomas/` sees 160+ flat subdirectories with no organizational hierarchy telling it which ones matter for the task at hand.

**Proposed fix:**

1. Create `thomas/marketplace/MANIFEST.json` listing every domain module with metadata:
   ```json
   {
     "agriculture": {"status": "marketplace-inventory", "do_not_modify": true},
     "blockchain": {"status": "marketplace-inventory", "do_not_modify": true}
   }
   ```

2. Add to `AGENTS.md` and `CLAUDE.md` (top section, impossible to miss):
   ```
   Everything under thomas/ that is NOT listed in the Architecture section below
   is marketplace inventory. Do not refactor, delete, rename, or judge the project
   based on these modules. They are plugin content for the Thomas marketplace.
   ```

3. Add to `agent_safety.toml` a new `[marketplace]` section:
   ```toml
   [marketplace]
   manifest = "thomas/marketplace/MANIFEST.json"
   # Agents must not modify marketplace modules without explicit user request
   protected_dirs = [
       "thomas/agriculture/",
       "thomas/blockchain/",
       # ... all 73 modules
   ]
   ```

4. Optionally: move all marketplace modules under `thomas/marketplace/` as a parent directory so the flat listing in `thomas/` drops from ~160 to ~25 core directories. This is a bigger change and requires updating imports across every module. Could be a separate phase.

**Effort:** Phase 1 (manifest + docs + safety config) = small, one agent session. Phase 2 (directory move) = large, needs careful import rewriting.

**Verification:** After phase 1, any new agent session should be able to answer "what are the marketplace modules?" by reading the manifest, and should not suggest deleting them.

---

## Item 2: Monolith Loader — Fix Guard + Eliminate Pattern

**What it is:** 10 Python files use `monolith_source_loader.py` to `exec()` 27 part files (`_part01.py`, `_part02.py`, etc.) into a single namespace at runtime. This pattern was introduced in commit `5425444` by an unattributed agent. The filename guard (`forge/gates/monolith_filename_guard.py`) was supposed to prevent this but its regex only catches `.partNN.ext` (dot-separated), not `_partNN.py` (underscore-separated). Every existing violation passes the guard undetected.

**Root cause:** The guard regex `r"\.part\d+\.[^.]+$"` does not match the `_partNN` naming convention that the agent used.

**Proposed fix — Phase 1: Close the guard gap (immediate, 15 minutes)**

1. Edit `scripts/forge/gates/monolith_filename_guard.py` line 21:
   ```python
   # BEFORE (only catches .partNN.ext):
   FORBIDDEN_PART_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
       re.compile(r"\.part\d+\.[^.]+$", re.IGNORECASE),
   )

   # AFTER (catches both .partNN.ext AND _partNN.ext):
   FORBIDDEN_PART_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
       re.compile(r"\.part\d+\.[^.]+$", re.IGNORECASE),
       re.compile(r"_part\d+\.\w+$", re.IGNORECASE),
   )
   ```

2. Add the same pattern to `scripts/forge/gates/monolith_guard.py` line 33:
   ```python
   _FORBIDDEN_PART_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
       re.compile(r"\.part\d+\.[^.]+$", re.IGNORECASE),
       re.compile(r"_part\d+\.\w+$", re.IGNORECASE),
   )
   ```

3. Update `CLAUDE.md` (already done — includes "MUST NOT create files matching `*_part*.py`").

4. Add to `agent_safety.toml` under `[duplicates]`:
   ```toml
   # Monolith split patterns — these are ALWAYS forbidden for new files
   forbidden_part_patterns = ["_part\\d+", ".part\\d+"]
   ```

**Proposed fix — Phase 2: Merge existing part files back (one workboard task per file)**

Each of the 10 monolith stub files needs to be converted to a normal Python module. The approach for each:

1. Concatenate all part files for that module into a single file
2. Replace the `load_monolith_source()` call in the stub with the actual concatenated code
3. Delete the part files
4. Run `ruff check --fix` on the merged file
5. If the merged file exceeds 800 lines (the soft limit), refactor into separate modules with normal `import` statements — NOT part files
6. Run the test suite to verify nothing broke

**Files to merge (10 tasks):**

| Stub file | Part files | Combined lines | Needs refactor? |
|-----------|-----------|---------------|----------------|
| `thomas/agent/loop.py` | 3 parts | ~1,886 | Yes (>800) — already has loop_core, loop_tools, loop_streaming, loop_planning as proper modules; just merge parts into those |
| `thomas/server/app.py` | 4 parts | ~2,468 | Yes — split into app.py + app_routes.py + app_middleware.py + app_startup.py with normal imports |
| `thomas/cli/main.py` | 3 parts | ~2,023 | Yes — split by command groups using normal imports |
| `thomas/server/routes/chat_aiohttp.py` | 3 parts | ~1,514 | Yes — split into chat routing + chat handlers + chat streaming |
| `thomas/memory/v2/fabric.py` | 4 parts | ~1,431 | Yes — split by responsibility (store, retrieval, indexing, maintenance) |
| `thomas/preferences/store.py` | 2 parts | ~1,394 | Yes — split preferences storage from preferences API |
| `thomas/tools/dep_scanner.py` | 2 parts | ~1,331 | Yes — split scanning logic from reporting |
| `thomas/tools/sandbox.py` | 2 parts | ~1,238 | Yes — split sandbox setup from sandbox execution |
| `thomas/cli/parity_commands.py` | 2 parts | ~1,181 | Yes — split by command category |
| `thomas/demo/agentic_benchmark.py` | 2 parts | ~1,286 | Yes — split benchmark definition from benchmark runner |

**JS/CSS part files (separate, lower priority):**
- `thomas/server/web/static/virtual_office.script01_part01.js` + `_part02.js`
- `thomas/server/web/static/plugin_marketplace.style01_part01.css` + `_part02.css`
- `thomas/server/web/static/workflow_builder.style01_part01.css` + `_part02.css`
- `thomas/server/web/js/modules/063_module_studio_comfy_style_id_part01.js` (x3 + x3 in src/)

These should be merged when the web UI build system is addressed (Item 6).

**Phase 3: Delete `monolith_source_loader.py` itself**

Once all 10 Python stubs are merged and all JS/CSS parts are merged, delete:
- `scripts/monolith_source_loader.py`
- Any references to it in docs

**Effort:** Phase 1 = 15 minutes. Phase 2 = 10 separate agent tasks, ~30-60 min each. Phase 3 = 5 minutes after Phase 2 is complete.

**Verification:** `python scripts/forge/gates/monolith_filename_guard.py` passes with zero violations. `grep -r "monolith_source_loader" thomas/` returns nothing. All tests pass.

---

## Item 3: Circular Imports — Add Missing Forbidden Pairs

**What it is:** `thomas/core/` imports from `thomas/server/` and `thomas/tools/`. The `core` module is documented as the bottom of the dependency tree — it should never import upward. The `agent_safety.toml` circular imports config is missing these two pairs.

**Root cause:** When the forbidden pairs list was created, `core → server` and `core → tools` were already in the code, so they weren't flagged as violations. Nobody added them to the list because the gate only checks for NEW violations in staged files.

**Proposed fix:**

1. Add the missing pairs to `agent_safety.toml`:
   ```toml
   [circular_imports]
   forbidden_pairs = [
       ["thomas.server", "thomas.browser"],
       ["thomas.memory", "thomas.agent"],
       ["thomas.memory", "thomas.server"],
       ["thomas.memory", "thomas.tools"],
       ["thomas.agent", "thomas.cli"],
       ["thomas.agent", "thomas.server"],
       ["thomas.core", "thomas.agent"],
       ["thomas.core", "thomas.server"],   # NEW
       ["thomas.core", "thomas.tools"],    # NEW
   ]
   ```

2. Find and fix the existing violations. The specific files in `thomas/core/` that import from `server` or `tools` need to be refactored. Options for each violation:
   - Move the import into a function body (lazy import) — quick fix
   - Move the shared code into `core` so the import isn't needed — correct fix
   - Use dependency injection (pass the needed object as a parameter) — cleanest fix

3. Add a comment to `agent_safety.toml` explaining the dependency hierarchy:
   ```toml
   # Dependency hierarchy (top imports bottom, never reverse):
   # cli → server → agent → tools → core
   #                agent → memory → core
   # core MUST NOT import from any sibling. It is the foundation.
   ```

**Effort:** Adding the config = 5 minutes. Fixing existing violations = 1-2 hours of careful refactoring, needs test verification after each change.

**Verification:** `python scripts/forge/gates/circular_imports_gate.py` passes. `python -c "from thomas.core import config"` succeeds without importing server or tools at module level.

---

## Item 4: Linting — One-Time Cleanup + Enforcement

**What it is:** 1,558 ruff violations in the core modules (agent, core, server). Mostly `UP006` (old-style type annotations like `Dict` instead of `dict`), plus pycodestyle and flake8-bugbear issues. 798 are auto-fixable.

**Root cause:** The ruff pre-commit hook only runs on changed files. These violations predate the hook and have never been touched since it was added.

**Why it matters for an agent-first repo:** Agents copy the style they see in existing code. If existing code uses `Dict[str, Any]`, new agent-written code will too, perpetuating the violations. Clean code teaches agents clean patterns.

**Proposed fix:**

1. Run `ruff check --fix` on the entire `thomas/` directory — fixes 798 violations automatically
2. Run `ruff check` to see remaining manual-fix violations, assess which are worth fixing vs. ignoring
3. Commit the auto-fix as a single "chore: apply ruff auto-fixes across codebase" commit
4. The existing pre-commit hook prevents new violations going forward

**Effort:** The auto-fix is a 10-second command. Reviewing the diff takes 5-10 minutes. Manual fixes (if any) are optional and can be done incrementally.

**Verification:** `ruff check thomas/` returns zero fixable errors. Pre-commit hook continues to catch new violations on changed files.

---

## Item 5: Documentation — Agent-Optimized Routing

**What it is:** 1,497 markdown files in the repo. The agent startup router exists and works, but `AGENTS.md` is 266 lines and mixes critical rules with deep-context protocol details. Agents either read too much (wasting tokens and getting confused) or skip sections and miss critical rules.

**Root cause:** `AGENTS.md` grew organically as new protocols were added. Nobody pruned it. Critical rules (don't make monoliths, use the router, tag commits) are buried among multi-agent handshake protocols that most single-agent sessions don't need.

**Proposed fix:**

1. Restructure `AGENTS.md` into two clear sections:

   **Section 1: "STOP — Read Before Anything" (first 20 lines max)**
   - Run the startup router
   - Read GUARDRAILS.md
   - Read the module GUARDRAILS.md for whatever you're modifying
   - Check agent_safety.toml
   - Don't create part files
   - Don't skip pre-commit hooks
   - Tag commits with your model name
   - Don't touch marketplace modules

   **Section 2: "Deep Context — Read Only When Needed" (everything else)**
   - Multi-agent handshake protocol
   - Workboard task ecosystem
   - LOC counting protocol
   - Website dev shortcut
   - Visual proof gate
   - etc.

2. The startup router should explicitly tell agents NOT to read Section 2 unless their task requires it. The lane card should say: "You do NOT need multi-agent protocol for this task" when appropriate.

3. `CLAUDE.md` already points to `AGENTS.md` with Claude-specific rules (created in this session).

4. Consider adding a `CODEX.md` that mirrors `CLAUDE.md`'s structure — short, directive, points to `AGENTS.md`. This ensures Codex also gets the critical rules front-loaded even if it skims `AGENTS.md`.

**Effort:** Restructuring AGENTS.md = 1 hour. Creating CODEX.md = 15 minutes (mirror CLAUDE.md structure).

**Verification:** Have a fresh Claude session open the repo and check if it runs the router and follows the rules without being prompted. Same test with Codex.

---

## Item 6: Web UI — Build System + Framework

**What it is:** The Thomas web UI at `thomas/server/web/` (the localhost:8899 app interface) has 158 JS files, 48 CSS files, and 16 HTML files served raw with no build system, no bundler, no framework. The public website (`apps/site/`) has a proper Next.js build system, but the actual product UI does not. Calvin was told this was fixed; it was not.

**Root cause:** An agent either fixed the wrong thing (the site instead of the app UI) or claimed the task was done without verification.

**This is the most complex item and needs the most design discussion.** Options:

**Option A: Vite + vanilla JS (minimal change)**
- Add `package.json` and `vite.config.js` to `thomas/server/web/`
- Vite bundles the existing JS/CSS into optimized outputs
- No framework migration needed
- Existing code stays mostly as-is, just gets bundled
- Pros: fast, low risk, preserves existing code
- Cons: still no component model, still hand-written DOM manipulation

**Option B: Vite + Preact/React (modern stack)**
- Same Vite setup but migrate to a component framework
- Massive rewrite, high risk, but results in a maintainable UI
- Pros: proper component model, state management, easier for agents to work with
- Cons: huge effort, breaks everything, needs extensive testing

**Option C: Keep raw but add a simple bundler**
- Use esbuild (fast, minimal config) to just concatenate and minify
- No framework, no module system changes
- Pros: smallest possible change, gets minification and bundling
- Cons: doesn't solve the structural problem

**Recommended: Option A (Vite + vanilla JS)** as Phase 1. It gives you bundling, minification, dev server with hot reload, and a path to gradual framework migration later. It doesn't require rewriting the existing 158 JS files.

**Verification gate for the future:** Add a check to `agent_safety.toml`:
```toml
[web_ui]
requires_build_system = true
build_command = "npm run build"
build_dir = "thomas/server/web/"
# Agent claiming "web UI build system is done" must prove:
# 1. package.json exists
# 2. npm run build succeeds
# 3. Built output is served by the server
```

**Effort:** Option A = 1-2 agent sessions. Option B = weeks. Option C = 1 session.

---

## Execution Order (Recommended)

1. **Item 2 Phase 1** — Fix the monolith guard regex (15 min, immediate impact)
2. **Item 3** — Add missing circular import pairs (5 min config change)
3. **Item 4** — Run ruff auto-fix (10 seconds + review)
4. **Item 1 Phase 1** — Create marketplace manifest + update docs (1 session)
5. **Item 5** — Restructure AGENTS.md (1 session)
6. **Item 2 Phase 2** — Merge monolith part files (10 separate tasks)
7. **Item 6** — Web UI build system (1-2 sessions)
8. **Item 1 Phase 2** — Move marketplace modules to subdirectory (optional, large)
