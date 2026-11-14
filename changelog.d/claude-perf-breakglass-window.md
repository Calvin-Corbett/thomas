### Security

- **An emergency override of the safety gates now expires on its own.** Turning off runtime
  protection required a signed authorisation, but nothing made that authorisation stop
  being true: one signed on 2026-09-06 was still switching off fourteen gates two days
  later, each reporting that it had passed and nothing at session start saying so. A
  signature proves someone authorised the override; it does not prove they still mean it
  days afterwards. The override now lasts eight hours, an expiry recorded inside it can
  only shorten that and never extend it, and anything unreadable leaves protection on.
- **The command that clears the message gate can be typed the way people type it.** The
  gate blocks further work until unread messages are acknowledged, and the acknowledgement
  it printed was itself blocked the moment you added `| head`, while command substitution
  slipped through unchecked. Every part of a piped command is now checked on its own.
- **The import check is registered as a protected hook.** It stops a commit whose imports
  would fail on a fresh clone; skipping it previously left no record.

### Fixed

- **Scripts and styles are cached again during development.** Every asset URL already
  carries a fingerprint that moves whenever any front-end file changes, so the header
  forbidding the browser to keep anything was protecting a guarantee already made — at the
  cost of re-downloading and re-parsing the whole bundle on every tab and refresh.
