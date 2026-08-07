# Known Issues — recurring pitfalls worth reusing instead of rediscovering

AGENTS.md points here. Add an entry when a gotcha costs real debugging time;
delete an entry when the underlying mechanism is gone.

## Chromium opacifies mismatched-scheme iframes (cost ~1h, 2026-08-06)

An embedded transparent document whose `color-scheme` differs from its
embedding IFRAME ELEMENT gets an opaque canvas from Chromium — every workspace
embed rendered as a white sheet the moment chat.html gained
`color-scheme: dark` from tokens.css. Computed styles all looked correct; only
pixels showed it. Both sides of every frame boundary must state the same
scheme — see `.tc-workspace-frame` in `css/chat_shell.css` and the
`html.is-embedded` rules in `css/workspace_shell.css`. If an embed ever renders
as a flat white/black sheet with "correct" computed styles, check the scheme
pair first.

## Shell heredocs eat backslashes (cost ~30min, 2026-08-07)

Content piped through Bash heredocs can collapse `\\` to `\`, which Python then
interprets: a `\b` regex became a literal 0x08 BACKSPACE byte inside a live JS
file — invisible in every listing, found only because a runtime check refused
to go quiet. Write backslash-heavy or escape-sensitive content to disk with a
proper file-writing tool, never through a heredoc.

## A NUL byte makes ripgrep silently skip a file (found 2026-08-06)

chat.html once used literal NUL characters as a JS value delimiter; ripgrep
classified the whole file as binary and every grep over it silently returned
nothing — "no references found" was a lie for months. The NULs are now
backslash-u0000 escapes (runtime-identical). If a grep over a file you can open
returns nothing, check `file <name>` before believing it.

## The `*_parts` directory pattern blocks every commit that stages it

`scripts/forge/gates/monolith_filename_guard.py` refuses any staged path
matching the split-file patterns, including directories named `*_parts/`.
Renaming the directory is allowed (deletions/renames pass because the guard
skips paths missing from disk), but a rename of protected `thomas/` or
`tests/` paths also needs a `docs/deletions/*.json` record.
