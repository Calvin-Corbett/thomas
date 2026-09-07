# PLAN for EVERY-USERS-THOMAS-P2-FORK-BY-OVERLAY

- Owner: codex-overlay-recovery
- Status: in_progress (recovery complete; independent audit and commit authorization pending; no commit or push)
- Updated At: 2026-09-02T19:07:54+00:00
- Scope: CHANGELOG.md,docs/OVERLAY.md,docs/superpowers/plans/2026-09-02-fork-by-overlay-reads.md,docs/superpowers/plans/2026-09-02-fork-by-overlay.md,plans/thomas/tasks/EVERY-USERS-THOMAS-P2-FORK-BY-OVERLAY/PLAN.md,tests/test_every_document_applies_the_overlay.py,tests/test_overlay_batch_is_coherent.py,tests/test_overlay_client_contract.py,tests/test_overlay_injection_contract.py,tests/test_overlay_manifest.py,tests/test_overlay_refuses_bad_writes.py,tests/test_overlay_render.py,tests/test_overlay_routes.py,tests/test_overlay_write_is_exact.py,tests/test_the_first_redesign_creates_the_overlay.py,tests/test_ui_redesign_client_contract.py,tests/test_ui_redesign_runtime.py,tests/test_workspace_shell.py,tests/web_node/overlay_client.mjs,thomas/server/app_core.py,thomas/server/app_middleware_helpers.py,thomas/server/overlay/__init__.py,thomas/server/overlay/__main__.py,thomas/server/overlay/cli.py,thomas/server/overlay/coherence.py,thomas/server/overlay/manifest.py,thomas/server/overlay/paths.py,thomas/server/overlay/records.py,thomas/server/overlay/render.py,thomas/server/overlay/schema.py,thomas/server/overlay/stock_tokens.py,thomas/server/overlay/store.py,thomas/server/overlay/style_whitelist.py,thomas/server/routes/mission_support.py,thomas/server/routes/ui_overlay_routes.py,thomas/server/routes/ui_redesign_runtime.py,thomas/server/routes/work_dashboard_runtime.py,thomas/server/web/js/browser_shell_docs.js,thomas/server/web/js/chat_themes.js,thomas/server/web/js/overlay_runtime.js,thomas/server/web/js/ui_edit_layout.js,thomas/server/web/js/ui_redesign_select.js,thomas/server/web/js/ui_redesign_target.js,thomas/server/web/js/workspace_shell.js,thomas/server/web/settings.script01.js

## Summary

EVERY-USERS-THOMAS-P2-FORK-BY-OVERLAY

## Approach

Plan: docs/superpowers/plans/2026-09-02-fork-by-overlay.md (reads: ...-reads.md). Contract: docs/OVERLAY.md.

Five commits, each with tests that failed first and a CHANGELOG entry:

- C1 the overlay package under thomas/server/overlay (manifest with full validation on load and a strict overlay-id precondition; records grammar and bounds; store: lock beside the directory, hard limits, boundary guard, atomic write with birth inside it; renderer in tokens.css selector grammar; CLI path|list|show|check).
- C2 injection into the four page handlers and the mission page, exactly once; routes GET view, GET manifest, POST records with stable refusal codes and a byte ceiling on what is read; the injected runtime (identity on five surfaces, reversible; shell font repaint; adopt; record with one retry on a stale id; BroadcastChannel fan-out).
- C3 every document reads the overlay: shell known themes and colour scheme, theme payload merge in manifest order, layout book overlay layer with orphans, settings theme names, net-negative.
- C4 Redesign writes the overlay: policy refused at pick, Apply records what it changed (elements with anchors, theme channel tokens, identity), honest result lines, Code brief rewritten.
- C5 real-browser proof: the first Redesign creates the overlay; every document applies it.

## Evidence

- Fail-first recovery proof: a caller-forged `anchor.policy="move resize"`
  caused `element:chat:desktop:chat.shell` to persist (one focused failure).
  The server now derives protected IDs from its own stock HTML/JavaScript;
  the named regression and both prior protected-target cases pass 3/3.
- Final package and contract gates on the recovered executable bytes: exact
  overlay 113/113; broader overlay/redesign/architecture 170/170; Node client
  13/13; architecture 13/13; Ruff clean; nine JavaScript syntax checks clean.
- Mandatory-Chromium gates on isolated free ports: full overlay 16/16, relay
  14/14, Phase-1 shell lifecycle 29/29, and workspace shell 10/10, all with
  zero skips. The organic matrix passed 1/1 at rev 19 across two live tabs and
  a second browser context, then restarted onto the identical 10,162-byte
  manifest with zero unexpected console/page errors.
- Independent adversarial F1-F10 review and the organic default-theme finding
  each have named regressions covering exact shapes, provenance, wildcard
  precedence, rollback ownership, canonical sink parity, CLI collision stock,
  loaded hard limits/history, stale-ID secrecy, and clear/re-add lifecycle.
- Port 8899 was never touched. Nothing is committed or pushed; the exact
  45-changed-path candidate awaits independent audit and commit authorization.
