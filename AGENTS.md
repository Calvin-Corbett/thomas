# Thomas Agent Instructions

Thomas is an AI coding agent with intentionally broad scope.
The breadth is a feature — don't reduce scope without explicit user request.

## Start Here
1. **`PROJECT_INDEX.md`** — How the project boots, where things live, process model,
   config flow, logging, data files, verification checklist, gotchas. **Read this first**
   when you need to understand how anything connects or runs.
2. **`thomas/_architecture.py`** — Module map, dependency rules, constraints, known debt.
   The single source of truth for architecture fitness.
3. **`KNOWN_ISSUES.md`** — Common problems and their fixes. **Read at session start.**
   Update when you find a new recurring issue that cost debugging time.

**Keep both files updated.** When you change boot paths, add entry points, move key files,
or discover a gotcha that cost significant debugging time — update `PROJECT_INDEX.md`.
When you add/remove modules or change dependencies — update `_architecture.py`.

## Changelog & Versioning (Dev Agent Responsibility)

**You own the changelog.** This is your development log — update it as you work, not at the end.

1. **When to write entries:** After each logical unit of work (a bug fix, a new feature, a
   refactor). Don't batch them. Don't wait for "before commit." Write it while the context
   is fresh.
2. **Version bump:** Any behavioral change (bug fix, new feature, changed behavior) needs a
   version bump in **both** `pyproject.toml` and `thomas/__init__.py`. Bump once per session,
   not once per change.
3. **Format:** Follow Keep a Changelog categories: `### Added`, `### Changed`, `### Fixed`,
   `### Removed`. Be specific — name the files, endpoints, or behaviors affected.
4. **What counts:** Code changes, new files, config changes, architectural changes, bug fixes.
   Pure docs-only changes (README, comments) don't need a version bump but still get a
   changelog entry under `[Unreleased]` if notable.

**The changelog is the project's memory across sessions.** Future agents (including you in a
new context window) rely on it to understand what changed and why. Sloppy changelog = lost
context = repeated mistakes.

## Before You Commit
Run `python -m pytest tests/test_architecture.py -x --tb=short -q`.
It checks dependency direction, file sizes, forbidden patterns, extension
isolation, module coverage, test coverage, health annotations, and cycles.

## Before You Delete Code
Never bulk-delete. For EVERY file or function you want to remove:
1. `grep -r '<name>' thomas/ tests/ scripts/ --include='*.py'` — find ALL references
2. If anything imports it: don't delete. Refactor or replace instead.
3. If only lazy/conditional imports: stub with safe fallbacks first.
4. After deletion: verify server boots (`python -m thomas serve --port 0`) and tests pass.

## Deep Context (read only when your task touches these areas)
- UI/tabs: `docs/WORKBENCH_OPERATOR_PROTOCOL.md`
- Workbench framing: tabs are AI-first operator control surfaces.
- Risky changes: `definitions/change-classification.md`
- Agent loop internals: `SOUL.md`
- Current priorities: `plans/thomas/WORKBOARD.md`
- Website releases: deploy via CI (`site-release.yml`), not ad-hoc

## Website Dev Shortcut (Dev-Only)
If a task mentions website/site/homepage/domain/Spline or the user asks for web changes:
1. Start in `apps/site` immediately.
2. Read `apps/site/README_DEV.md` first for current URLs and workflow.
3. Run website commands from `apps/site` (`npm run dev`, `npm run typecheck`, deploy scripts).
4. Apply skill `ui-precision-guard` at `.codex/skills/ui-precision-guard/SKILL.md` for any UI edit.

## Runtime Skills (Model-Agnostic)
Thomas resolves runtime skills at the orchestrator layer before model calls.
This applies across providers (Codex, Anthropic, OpenAI-compatible), not just Codex.

Selection order is:
1. Explicit skill mention in prompt (`$skill-name`, inline mention, or `skill <name>`)
2. Pinned skills from `.thomas/cli/skills.json`
3. Relevance-ranked skills from discovered roots

Discovery roots:
- `$CODEX_HOME/skills`
- `~/.codex/skills`
- `<memory_root>/.codex/skills`
- `<cwd>/.codex/skills`
- `<cwd>/skills`
- Optional: `THOMAS_SKILLS_EXTRA_DIRS` (`os.pathsep`-separated)

## Hard Gate: Website Visual Proof (All Agents)
This rule applies to Thomas and any external/competing agent editing this repo.

When UI files change in:
- `apps/site/src/app/**`
- `apps/site/src/components/**`

you must update:
- `apps/site/verification/ui-proof.json`
- `apps/site/verification/runtime-report.json`
- `apps/site/verification/screenshots/full-page.png`
- `apps/site/verification/screenshots/footer-focus.png`
- `apps/site/verification/baselines/full-page.png`
- `apps/site/verification/baselines/footer-focus.png`
- `apps/site/verification/diffs/full-page-diff.png`
- `apps/site/verification/diffs/footer-focus-diff.png`

and run:
- `python scripts/refresh_site_visual_proof.py`
- `python scripts/check_site_visual_proof.py`

Enforcement is hard-coded via:
- pre-commit hook `thomas-site-visual-proof-gate`
- CI workflow `.github/workflows/site-release.yml`
- runtime browser verifier `scripts/verify_site_visual_runtime.mjs` (auto screenshots + DOM assertions)
- proof refresh script `scripts/refresh_site_visual_proof.py` (pixel-diff baseline comparisons)

## LOC Counting Protocol (Default)
When a user asks for LOC/SLOC counts, run the full sweep by default.

Required method:
1. Count git-tracked files only (`git ls-files -z`) so local build artifacts do not skew totals.
2. For each tracked file present on disk, run language-aware analysis with UTF-8 fallback.
3. Report commit hash + branch with the results.
4. Report file coverage stats:
   - tracked files
   - present files
   - missing files
   - analyzer state counts (analyzed/unknown/binary/generated/empty)
5. Report SLOC buckets:
   - `prod_app`
   - `tests`
   - `docs_config_data`
   - `total_buckets`
6. Report physical line totals:
   - all present files
   - text files only
   - binary/text file counts
7. Report top languages by SLOC:
   - total repo
   - `prod_app` subset
8. Call out when JSON/config/docs dominate totals, and offer a stricter "pure app code" rerun (exclude JSON/lock/docs/diff) when needed.
