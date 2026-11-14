### Fixed

- **Hidden tabs stopped asking the server for work nobody can see.** Every Chat, Build and
  Work tab is its own document, and the shell already marked the inactive ones — but the
  only thing reading that mark was a CSS rule that paused animations. Both panels guarded
  their polling on `document.hidden`, which is only true when the whole browser window is
  in the background, so a tab you had switched away from kept asking twice a second
  forever. Measured on an idle page: 79 requests a minute, multiplied by every tab left
  open. A hidden tab now asks for nothing and refreshes the instant you switch back to it;
  the tab you are looking at is unchanged.
- **Opening a conversation no longer draws the whole transcript twice.** The thread was
  painted from the cached copy, then re-fetched and rebuilt from scratch even when nothing
  had changed, and every message carries a fade-in — so the entire conversation visibly
  re-animated on every open. It is now drawn once unless the refetch actually differs.
- **Scripts and styles are cached again during development.** Every asset URL already
  carries a fingerprint that changes whenever any front-end file changes, and the server
  already answered a conditional request correctly — then sent a header forbidding the
  browser to keep anything. That reloaded and re-parsed roughly 700 KB of JavaScript for
  every tab and every refresh, to protect a freshness guarantee the fingerprint had
  already made. Edits still appear immediately on reload.
- **A workspace left open in a background tab stopped rebuilding itself every fifteen
  seconds.** It refreshes when you return to it instead.

### Security

- **An emergency override of the safety gates now expires on its own.** Disabling runtime
  protection required a signed authorisation, but nothing made that authorisation stop
  being true: one signed on 2026-09-06 was still switching off fourteen gates two days
  later, each reporting that it had passed. A signature proves someone authorised the
  override; it does not prove they still mean it days afterwards. The override now lasts
  eight hours, an expiry recorded inside it can only shorten that and never extend it, and
  anything unreadable leaves protection on.
- **Every session now reports whether the safety gates are actually enforcing.** While an
  override is open, the checks that guard protected files, deletions, merges and worktrees
  report success without inspecting anything — and nothing said so. The session-start
  report now names that state, and a test holds it to actually being run.
- **The command that clears the message gate can now be typed the way people type it.**
  The gate blocked further work until unread messages were acknowledged, and the
  acknowledgement it printed was itself blocked the moment you added `| head` — while
  command substitution slipped through unchecked. Every part of a piped command is now
  checked on its own.

### Added

- **A proof that the import check can fail.** It stops a commit whose imports would break a
  fresh clone, and it had no test showing it ever refuses anything.
