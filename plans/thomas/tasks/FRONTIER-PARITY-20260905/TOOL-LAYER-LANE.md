# FRONTIER-TOOL-LAYER-20260905 - the tool layer stops failing the model before it starts

Owner: claude. Goal (Calvin, 2026-09-05): "make thomas better in meaningful ways. thomas must meet or exceed frontier agents in every lane possible."

## Evidence (Terminal-Bench 4.0 run `thomas-tb4-finish`, 2026-09-04, commit 07cc5295)
- 26 tool calls refused with "absolute paths are not allowed" across 3 tasks, always the model's FIRST calls
  (fs.read_file, fs.list_dir, code.project_structure, eng.lint, eng.security_scan). The error calls a read tool a
  "write tool". The tool itself documents "Relative or absolute path" and its own sandbox check would have accepted it.
- git.status in a non-git folder returned the same fatal three times; the stability guard then killed a 128-iteration
  run (bun-sourcemap-leak, 30/36 tests). eng.lint crashed on a missing `python` binary (FileNotFoundError, absolute
  path refused) and killed data-anonymization the same way after 139 iterations.
- Frontier harnesses (LangChain LoopDetection, Claude Code, Codex CLI) break a doom loop by refusing the repeated call
  and telling the model why; none of them abort the run.

## Changes
1. loop_tool_paths / loop_tool_exec: a non-write tool may use an absolute path when it resolves inside the sandbox
   root (or the benchmark root); outside stays refused. Error text names the tool correctly.
2. git tools: outside a repository, one clear refusal that names the folder and the alternative, cached per cwd so the
   model is told "already refused" instead of a fresh fatal.
3. Repeated identical failure: a synthetic tool result that names the count and disables that exact call for the run,
   instead of `state.error` + abort. (guard block lives in loop_execution.py - codex claim; carve-out requested.)
4. eng.lint / eng.format: sys.executable, then `ruff` on PATH, run in the sandbox cwd; FileNotFoundError becomes a
   tool error, never a crash. (thomas/tools/engineering.py - codex claim; carve-out requested.)

## Proof
- Unit tests per change. A local benchmark-lane rehearsal: sandbox root `/`-style, absolute reads succeed, git.status
  in a temp dir refuses once, the guard disables instead of aborting.
