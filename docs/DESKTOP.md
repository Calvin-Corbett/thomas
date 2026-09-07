# Thomas Desktop — the browser Thomas owns

Thomas runs two ways. `run-ui.cmd` starts the server and hands the UI to
whatever browser you already have. `desktop.cmd` starts Thomas as its own
windowed application, where tabs are real web views and Thomas can see and
act on them.

```bash
desktop.cmd
```

First run installs the desktop dependencies. It attaches to a Thomas server
already listening on port 8899 and starts one itself if nothing answers.
`desktop.cmd -Port 8932` points it somewhere else; `desktop.cmd -Spike` runs
the gauntlet instead of the app.

## Known blocker: Windows Smart App Control

**As of 2026-08-26 the app will not launch on this machine.** Smart App
Control moved from evaluation to enforcement
(`VerifiedAndReputablePolicyState = 1`) and now blocks the unsigned
`electron.exe`:

```
Program 'electron.exe' failed to run: An Application Control policy has blocked this file
```

Nothing in this repo changed — the app ran and was verified for hours before
the flip, and `Get-AuthenticodeSignature` simply reports `NotSigned`. The fix
is a packaged, **code-signed** build (`electron-builder` plus a certificate;
EV, or OV with reputation, for SAC to accept it). Tracked as
`DESKTOP-CODE-SIGNING`.

Do not disable the policy to get around it: that is the owner's call, and on
Windows 11 turning Smart App Control off is effectively one-way — it cannot
be re-enabled without resetting the machine. `run-ui.cmd` and the browser UI
are unaffected.

## Trying the chrome without the app

While the desktop app is blocked, the same chrome can be attached in an
ordinary browser:

```
http://127.0.0.1:8899/?browser=1
```

or persistently, from the console: `localStorage.thomas_browser_shell = 'on'`
(`'off'`, or `?browser=0`, turns it back off).

It is **off by default** and changes nothing about the normal UI. Everything
works except the parts that need a real window: web tabs fall back to
iframes, which most of the internet refuses to be put in, and the window
buttons say what they cannot do instead of pretending. Tabs, the omnibox,
bookmarks, the side panel and the Ask Thomas quick chat all behave as they do
in the app.

## Why Electron

The requirement was the full modern web, the same engine on every platform,
CDP everywhere, MIT-clean licensing, and engine maintenance carried by
someone else. A Chromium fork fails on solo maintenance; WebView2 fails on
Linux and Mac; Tauri gives a different engine per OS with no CDP outside
Windows.

Iframes were never a candidate: `wellsfargo.com` answers
`X-Frame-Options: SAMEORIGIN`, and so does every search engine worth using,
so a framed "browser" shows blank pages for most of the real web.

Pinned: **Electron 43.4.1** (Chromium 150.0.7871.224). Every dependency is
MIT, ISC, BSD-2, Apache-2.0, Python-2.0 or BlueOak — no GPL or AGPL code is
in this repo, and none may be added.

## What the app is made of

| Piece | What it does |
|---|---|
| `desktop/main.js` | The window, the tabs, the profile, the agent bridge |
| `desktop/preload.js` | The only bridge to the page, and it attaches the chrome |
| `desktop/spike.js` | The Phase 1 gauntlet, kept runnable |
| `thomas/server/web/js/browser_shell.js` | Tabs, omnibox, bookmarks bar |
| `thomas/server/web/js/browser_shell_panel.js` | Side panel + Ask Thomas quick chat |
| `thomas/server/web/js/browser_shell_desktop.js` | The half that only exists in the app |

The chrome is served from `/static` like any other asset but is **not linked
from `chat.html`** — that file is 2998 lines against a 1000-line hard limit
and is unbaselined, so no commit can touch it. `preload.js` attaches the
chrome to the page it hosts instead. When `chat.html` is decomposed, the link
tags move into the page and that injection goes away.

## Security posture

Not preferences — the product. `contextIsolation: true`, `sandbox: true`,
`nodeIntegration: false` on every view; web content gets **no preload at
all**; the agent bridge binds loopback only and demands a random token;
bridge navigation is http(s) only.
`tests/test_the_browser_never_lowers_its_own_walls.py` fails if any of that
changes.

Page content reaches the model as **untrusted data**: the desktop shell sends
`page_context` as a structured field and `chat_page_context.py` wraps it
server-side, where no client can skip it. A page writes its own title, so a
title is a stranger's text.

## The agent channel

One channel, CDP over `webContents.debugger`, exposed to the Python server
through a token-gated loopback WebSocket (`runtime/browser_profile/bridge.json`
holds `{port, token}`). There is deliberately no screenshot-seeing and no
injected-script control as a parallel path — take-control and recorded tasks
extend this same socket.

Verbs: `open_url`, `list_tabs`, `navigate`, `read_dom`, `click`,
`click_named`, `snapshot`, `url`, `metrics`.

`snapshot` returns the accessibility tree — roles and names of what the page
offers. `click_named` acts on one of those anchors: a CSS selector breaks on
the next redesign and a coordinate breaks on the next reflow, but "the link
named English" survives both. A miss is reported, never approximated.

## Your profile

Everything lives in `runtime/browser_profile/`:

| File | Contents |
|---|---|
| `Partitions/thomas/` | Cookies and site data — logins survive a quit |
| `history.jsonl` | One JSON object per visit: `{at, url, title}`, `at` is ISO-8601 UTC |
| `session.json` | `{urls: [...]}` — the tabs reopened on next launch |
| `bridge.json` | `{port, token}` for the agent bridge, rewritten each launch |

It is ours, not a system Chrome profile. Deleting `session.json` is the fix
if the app reopens a pile of stale tabs.

## The gauntlet

An engine we do not maintain has to be re-proven whenever it moves. Seven
gates: single instance, the three security walls, two `WebContentsView`s with
their own renderer processes and live state, `wellsfargo.com` rendering
top-level, a persistent profile surviving relaunch, CDP read plus a real
input-dispatched click, and the Python side driving a tab end to end.

```bash
desktop.cmd -Spike
```

Results land in `desktop/spike-results.json`. The workboard item
`ELECTRON-BUMP-RECURRING` requires this on every new Electron stable major.

Two findings from building it are worth keeping: an unfocused window silently
drops CDP `mousePressed` while still passing `mouseMoved`
(`Emulation.setFocusEmulationEnabled` fixes it), and `npm init -y` leaves
`main: index.js`, which makes `electron .` hang on the default splash forever.

## Why a click can land nowhere

Three separate causes, all silent, and all invisible to a DOM-read check —
`read_dom` happily returns text from a view with a 0x0 viewport, so
read-based verification passes while every click fails.

1. `DOM.getBoxModel` can return coordinates that disagree with the viewport
   the input dispatcher aims at. The click point comes from
   `getBoundingClientRect` after scrolling the element into view instead.
2. A `ResizeObserver` fires once immediately, and before first layout that
   rect is `0x0`. Accepting it sizes the view to nothing.
3. A hidden background tab also reports `0x0`, so acting on one does nothing.
   The click verbs bring the tab forward first.

`metrics` reports geometry from both sides when this comes up again.

## What is not built

Typing and key presses (deliberately deferred — expanding what the agent can
do unattended on logged-in sessions is a decision, not a chore), recorded
task replay, a download shelf beyond a toast, packaging and an update feed.
`electron-updater` is wired but inert until the app is packaged.
