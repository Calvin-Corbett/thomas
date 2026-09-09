---
name: incremental-cache-cli-modes
description: Use when implementing incremental caches, cache invalidation, cache stats, cache summary, list/import/export/prune/clear cache CLI modes, or CLI side-effect/reporting paths where normal analysis output and diagnostic output must not interfere.
---

# Incremental Cache And CLI Modes

Use this for tools that add incremental analysis, persistent file caches, cache hit/miss metrics, or cache-management CLI flags.

## Core Workflow

1. Map every CLI flag into one of these categories before coding:
   - **analysis modes**: run normal analysis and optionally use/update the cache.
   - **side-effect-only modes**: clear, prune, import, export, stats, summary, list cached files.
   - **hybrid modes**: warm cache, force rescan, analysis with cache metrics.
2. Side-effect-only modes must not accidentally run the normal analysis/report pipeline unless the spec explicitly requires it.
3. Keep report output ownership separate from diagnostics. If formatters or output-file code may close or replace `stdout`, print cache stats/summary/list output through a live stream that you own, or return before the formatter path closes it.
4. Cache entries must be keyed by both file content and effective analysis configuration, not by path alone.
5. Preserve user-visible result semantics when serving from cache: issue severity, confidence, CWE, line number/range, filename, code snippets when applicable, skipped files, and exit codes.

## Required Edge Checks

Run or create focused checks for:

- first run misses, second run hits;
- modified file rescans and updates cached results;
- deleted file does not appear as a stale cached issue;
- severity/confidence/test/profile/config changes invalidate cache entries;
- `--force-rescan` bypasses reads but still writes fresh entries;
- `--warm-cache` populates cache without reporting issues and exits successfully;
- stats/summary/list/clear/prune/import/export work with and without positional targets;
- cache corruption, incompatible format versions, and partial files are ignored without crashing;
- cache size limits are enforced after writes and stats still report `cache_file_size_bytes`.

## Output Rules

- Cache stats and summaries are operational output, not scan findings. Do not route them through a formatter that may close the output file or suppress stdout.
- When a flag is meant to answer a cache question, print the answer before returning from the CLI command path.
- If the CLI accepts targets with a stats/list flag, treat targets as optional context for locating config/cache, not as a reason to run a full scan unless the contract says so.
- If normal analysis output and cache diagnostics can both be requested, make their ordering deterministic and test the combined path.

## Implementation Pattern

- Centralize cache serialization/deserialization in a small module.
- Store `format_version`, file content hash, effective config hash, timestamp, and serialized issue records.
- Keep invalidation reasons explicit: `not_cached`, `file_changed`, `config_changed`, `expired`, `corrupt`, or equivalent.
- Keep cache metrics on the manager/session object and expose them to JSON or machine-readable formatters under a stable `cache_info` object.
- Test the CLI as a subprocess for stream ownership, because direct function tests often miss closed-stdout bugs.
