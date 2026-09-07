# Web Tab Shell Implementation Plan (Every User's Thomas, phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The web UI at `/` (chat.html, port 8899) shows a Chrome-style tab strip by default, with zero Electron, where every tab owns one live document that is only ever hidden on a switch, so drafts, scroll and in-flight streams survive switching.

**Architecture:** The existing browser chrome (`browser_shell.js`, attached at runtime by `workspace_shell.js`) becomes the web path's first-class shell instead of an opt-in. The top-level page stays the pinned home tab; every additional conversation and every Build/Work tab is a second `chat.html` document in an iframe (`/?embed=1&browser=0`) that the shell shows and hides with `visibility` + `inert`, never `display:none`, never detached. Workspace tabs already are one iframe per tab. Sidebar rows and mode buttons are intercepted in the capture phase and routed through pure policy functions (focus the tab that already holds a conversation, adopt a blank surface, otherwise open a new tab).

**Tech Stack:** Vanilla classic-script JS under `thomas/server/web/js/`, CSS on the tokens.css design tokens, node `vm` harnesses under `tests/web_node/`, Playwright (python sync API) against a stdlib `ThreadingHTTPServer` fixture, commits via `scripts/crew/brief/commit.py`.

**Spec:** The owner's program prompt of 2026-09-01 and the two board charters `msg-20260901222616-claude` and `msg-20260901223229-claude` in `plans/thomas/WORKBOARD.md`; the design synthesis came from a nine-agent read/design/judge workflow on 2026-09-01 (hybrid design won: home tab is the top-level document, every other Chat/Build/Work tab is its own document).

## Global Constraints

- `thomas/server/web/chat.html` is 2998 lines against a 1000-line HTML hard limit and is unbaselined: it is NEVER staged. `docs/monolith_guard_baseline.json` is protected: never edited.
- JS/CSS/HTML soft limit 800 lines on any changed unbaselined file (`monolith_guard.py:395-398`); `browser_shell.js` is at 794 and must be split move-only BEFORE it grows.
- No file may grow more than 300 lines in one commit, new files included (`commit_growth_guard.py`, enforced in CI).
- Commit ONLY via `python scripts/crew/brief/commit.py --agent claude-browser --include <paths> --message <text>` from PowerShell with the message read from a file (`$m = Get-Content msg.txt -Raw`); the message must contain no double quote character; every commit ends with the trailer `Thomas-Agent: claude`.
- One `CHANGELOG.md` entry per commit under `## [Unreleased]`, heading shape `### Added (lower-case sentence fragment)`.
- Tests are sentence-named (`tests/test_a_..._.py`) and use fixtures only; node harnesses live in `tests/web_node/*.mjs` and are driven by a `.py` test.
- Never restart or verify against the owner's server on :8899. Static web files are read from disk per request, so the owner sees the change on reload once it lands; verify on a second port (8931 is running for this session).
- No `*_part*` files, no `exec()`, no `--no-verify`, no bare `except Exception`.
- Keyboard honesty: in a plain browser tab Chrome and Edge reserve Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab and Ctrl+PageUp/PageDown; the page never sees them. Ctrl+1-9 is expected to arrive (medium-high confidence, unverified). Alternates that always reach the page: Alt+1-9, Alt+PageDown / Alt+PageUp. Never a Ctrl+Shift combination: the layout editor (ui_edit_mode.js) treats a Ctrl+Shift press-and-release as its Redesign chord, and a swallowed middle key arms it inside every tab document (found live on 2026-09-01; the Ctrl+Shift bracket pair in Task 5 was removed for that reason). Headless CDP key delivery in tests is evidence of the handler, not proof of real-browser delivery.

---

## File Structure

| File | Responsibility | Status |
| --- | --- | --- |
| `thomas/server/web/js/browser_shell.js` | The shell: chrome DOM, tab strip machinery, workspace tabs, toolbar, boot. 794 lines today. | modify (shrinks to ~690 in task 1, ~720 after task 3) |
| `thomas/server/web/js/browser_shell_web.js` | Web tabs, the + page, the history page: moved verbatim out of the shell. | create (~150) |
| `thomas/server/web/js/browser_shell_docs_policy.js` | Pure decisions: `decideRowClick`, `decideModeClick`, `decideNewChat`, `blankIdle`, `docUrlFor`. No DOM. | create (~70) |
| `thomas/server/web/js/browser_shell_docs.js` | Document tabs: open, wire, show/hide, interceptors, observers, reload-target, theme relay. | create (~260) |
| `thomas/server/web/js/browser_shell_keys.js` | Keyboard bindings, now with alternates the browser does not eat and `attachTo(win)`. | modify (78 to ~115) |
| `thomas/server/web/js/browser_shell_panel.js` | Side panel: gains a `doc` case. | modify (+8) |
| `thomas/server/web/js/workspace_shell.js` | Attaches the chrome; gate flips to on-by-default; chain gains the new modules. | modify (+10/-6) |
| `thomas/server/web/js/unified_code_projects.js` | A tab document never records or restores `thomas.lastSurface`. | modify (+3) |
| `thomas/server/web/css/browser_shell.css` | `.bt-doc` frame rules, pinned home. | modify (+16) |
| `thomas/server/web/css/chat_shell.css` | Embedded instance hides its header; hidden documents pause their living worlds. | modify (+10) |
| `desktop/preload.js` | Same chain, plus an already-attached guard. | modify (+3) |
| `tests/web_node/browser_shell_docs_policy.mjs` | vm harness over the policy module. | create (~80) |
| `tests/web_node/browser_shell_keys.mjs` | vm harness over the keys module. | create (~70) |
| `tests/web_node/workspace_shell_gate.mjs` | vm harness over the chrome gate. | create (~60) |
| `tests/web_fixtures/thomas_chat_fixture.py` | Threaded HTTP server: serves chat.html + static from disk, stubs every API the page hits, drips an NDJSON reply. | create (~200) |
| `tests/test_a_sidebar_click_focuses_the_tab_that_already_has_it.py` | Policy table. | create (~100) |
| `tests/test_a_tab_switch_is_only_ever_a_hide.py` | Real browser: one document per tab, draft/scroll/stream survive, close. | create (~250) |
| `tests/test_a_conversation_exists_once_across_tabs.py` | Real browser: Build tab, focus-not-duplicate, settings, theme relay. | create (~220) |
| `tests/test_a_shortcut_the_browser_keeps_still_has_a_twin_here.py` | Keys table. | create (~90) |
| `tests/test_the_chrome_is_on_unless_you_turn_it_off.py` | Gate table + source pins. | create (~80) |

Module wiring contract (all classic scripts, loaded sequentially by `workspace_shell.js` and `desktop/preload.js` in this order): `browser_shell_panel.js`, `browser_shell_desktop.js`, `browser_shell_keys.js`, `browser_shell_search.js`, `browser_shell_web.js`, `browser_shell_docs_policy.js`, `browser_shell_docs.js`, `browser_shell.js`. Each exposes one global (`window.ThomasBrowserWeb`, `window.ThomasBrowserDocsPolicy`, `window.ThomasBrowserDocs`) with a `wire(ctx)` (or pure functions) after the `browser_shell_search.js` pattern.

---

### Task 1: The shell is split before it grows (move-only)

**Files:**
- Create: `thomas/server/web/js/browser_shell_web.js`
- Modify: `thomas/server/web/js/browser_shell.js:539-665` (remove), `:687-716` and `:749-790` (call sites)
- Modify: `thomas/server/web/js/workspace_shell.js:213-219` (chain), `desktop/preload.js:42-48` (chain)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `window.ThomasBrowserWeb.wire(ctx) -> { hostOf, attachWebFrame, openWebTab, navigateWebTab, openUrl, openNtp, convertNtpToWeb, openHistoryTab }` where ctx is `{ desktop, bodyRow, h, esc, SVG, icons, wsByMode, bookmarks, makeTab, byId, activate, setTitle, setStatus, toast, viewTabs, reportBounds, getActiveId, openWorkspaceTab, omni, websearch }` and `websearch` is a getter function (`() => websearch`) because the search module is created after the web module.

- [ ] **Step 1: Record the before state**

Run (PowerShell): `(Get-Content thomas/server/web/js/browser_shell.js).Count` and `node --check thomas/server/web/js/browser_shell.js`. Expected: 794 (git `wc -l`), check passes. Run the baseline driver `python <scratchpad>/drive_baseline.py http://127.0.0.1:8931` and keep its JSON: `browser1.tabs == ["Chat"]`, no errors.

- [ ] **Step 2: Create `browser_shell_web.js` with the moved code**

Header comment, then `(function () { "use strict"; function wire(ctx) { const { desktop, bodyRow, h, esc, SVG, icons, wsByMode, bookmarks, makeTab, byId, activate, setTitle, setStatus, toast, viewTabs, reportBounds, getActiveId, openWorkspaceTab, omni, websearch } = ctx;` followed by lines 539-665 of today's `browser_shell.js` VERBATIM (from `function hostOf(url)` through the end of `function openHistoryTab()`), with exactly these substitutions inside the moved text: `activeId` becomes `getActiveId()`; `websearch.` becomes `websearch().`; nothing else changes. Then `return { hostOf, attachWebFrame, openWebTab, navigateWebTab, openUrl, openNtp, convertNtpToWeb, openHistoryTab }; } window.ThomasBrowserWeb = { wire }; }());`.

The header comment states: moved out of browser_shell.js, which sat at 794 lines against the 800-line soft limit; behaviour unchanged by the move; the shell hands it a context object the way browser_shell_search.js receives one.

- [ ] **Step 3: Replace the block in `browser_shell.js`**

Delete lines 539-665. In their place:

```js
  /* ── Web tabs, the + page and History live in their own module ─────── */
  const web = window.ThomasBrowserWeb.wire({
    desktop, bodyRow, h, esc, SVG, icons, wsByMode, bookmarks, makeTab, byId, activate,
    setTitle, setStatus, toast, viewTabs, reportBounds, openWorkspaceTab, omni,
    getActiveId: () => activeId,
    websearch: () => websearch,
  });
  const { openNtp, openUrl, hostOf, openWebTab, openHistoryTab } = web;
```

`omni` is declared at line 138 and `bookmarks` at 222, both before this point; `websearch` is a `const` declared at the end of the file and is only dereferenced through the getter at call time. Every later call site (`renderBookmarks` click, `closeTab`, `#bt-star`, omnibox Enter, `newBtn`, keys `newTab`, desktop wiring ctx, search ctx `openUrl: url => openUrl(url)`) keeps its name because of the destructuring line. `renderBookmarks` (line 229) runs at boot before `web` exists but only binds click handlers that call `openUrl` later, so no temporal dead zone is hit; `closeTab` calls `openNtp` only on user action.

- [ ] **Step 4: Add the chain entries**

`workspace_shell.js` chain array: insert `"/static/js/browser_shell_web.js",` immediately before `"/static/js/browser_shell.js",`. `desktop/preload.js` chain: the same line, plain ASCII (the walls test scans that file).

- [ ] **Step 5: Verify move-only**

Run: `node --check thomas/server/web/js/browser_shell.js; node --check thomas/server/web/js/browser_shell_web.js`. Count lines: shell about 690, web about 150. Run `python -m pytest tests/test_a_click_that_lands_nowhere_is_never_silent.py tests/test_a_search_result_cannot_smuggle_a_script.py tests/test_the_browser_never_lowers_its_own_walls.py -q`. Expected: pass (the zero-rect pin lives in `reportBounds`, which stays). Reload `http://127.0.0.1:8931/?browser=1` in the driver: the + button opens the + page, a URL in the omnibox opens a web tab, the star bookmarks it, the profile menu has no History item (plain browser), no console errors.

- [ ] **Step 6: CHANGELOG + commit**

CHANGELOG under `## [Unreleased]`:

```
### Changed (the browser shell is split before it grows)

- **`js/browser_shell_web.js`** now holds the web tabs, the + page and the
  History page, moved verbatim out of `browser_shell.js`, which sat six lines
  under the 800-line soft limit. Nothing behaves differently; the shell hands
  the module a context object the way it already does for search.
```

Commit message file (no double quotes anywhere):

```
refactor(browser): the shell is split before it grows

browser_shell.js sat at 794 lines against the 800-line soft limit, so the
next feature could not land in it. The web-tab, + page and History code
moves verbatim into browser_shell_web.js with a context object, the same
seam browser_shell_search.js uses. No behaviour changes: the moved
functions are re-exported under their old names at the old position.

Thomas-Agent: claude
```

Run: `python scripts/crew/brief/commit.py --agent claude-browser --include thomas/server/web/js/browser_shell.js,thomas/server/web/js/browser_shell_web.js,thomas/server/web/js/workspace_shell.js,desktop/preload.js,CHANGELOG.md --message $m`. Expected: PASS, `git status --porcelain` on those paths empty.

---

### Task 2: The row-click policy, test first

**Files:**
- Create: `tests/web_node/browser_shell_docs_policy.mjs`
- Create: `tests/test_a_sidebar_click_focuses_the_tab_that_already_has_it.py`
- Create: `thomas/server/web/js/browser_shell_docs_policy.js`

**Interfaces:**
- Produces: `window.ThomasBrowserDocsPolicy = { decideRowClick, decideModeClick, decideNewChat, blankIdle, docUrlFor }`.
  - `decideRowClick({ surface, row: {id, mode, title}, tabs, modifiers: {ctrl, meta, middle} }) -> { action: 'focus', tab } | { action: 'adopt' } | { action: 'open' }`
  - `decideModeClick({ mode, home, tabs }) -> { action: 'focus', tab } | { action: 'open', mode }`
  - `decideNewChat({ surface }) -> { action: 'adopt' } | { action: 'open', mode }`
  - `blankIdle(surface) -> boolean` where surface is `{ mode, chatId, busy, draft, hasContent }`
  - `docUrlFor({ mode, chatId }) -> string` always starting `/?embed=1&browser=0`, adding `&forge_code=<id>` only for mode `code` with an id.
  - Tabs passed in carry `{ id, kind, mode, chatId, activatedAt }`; `home` is the chat-home tab object.

- [ ] **Step 1: Write the harness**

`tests/web_node/browser_shell_docs_policy.mjs`:

```js
// Runs browser_shell_docs_policy.js in a vm context and reports what its
// decisions actually are, so the Python test asserts behaviour, not source.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const modulePath = process.argv[2];
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(modulePath, 'utf8'), sandbox, { filename: 'browser_shell_docs_policy.js' });
const policy = sandbox.window.ThomasBrowserDocsPolicy;
if (!policy) { process.stderr.write('window.ThomasBrowserDocsPolicy missing\n'); process.exit(1); }

const home = { id: 1, kind: 'chat-home', mode: 'chat', chatId: 'a', activatedAt: 5 };
const docB = { id: 2, kind: 'doc', mode: 'chat', chatId: 'b', activatedAt: 7 };
const build1 = { id: 3, kind: 'doc', mode: 'code', chatId: '', activatedAt: 2 };
const build2 = { id: 4, kind: 'doc', mode: 'code', chatId: '', activatedAt: 9 };
const tabs = [home, docB, build1, build2];
const blank = { mode: 'chat', chatId: '', busy: false, draft: '', hasContent: false };
const drafted = Object.assign({}, blank, { draft: 'half a thought' });
const busy = Object.assign({}, blank, { busy: true });
const rowA = { id: 'a', mode: 'chat', title: 'Alpha' };
const rowB = { id: 'b', mode: 'chat', title: 'Beta' };
const rowZ = { id: 'z', mode: 'chat', title: 'Zeta' };
const decide = (surface, row, modifiers) => policy.decideRowClick({ surface, row, tabs, modifiers: modifiers || {} });
const report = {
  row_held_by_home: decide(blank, rowA).action + ':' + (decide(blank, rowA).tab || {}).id,
  row_held_by_doc: decide(blank, rowB).action + ':' + (decide(blank, rowB).tab || {}).id,
  row_on_blank_surface: decide(blank, rowZ).action,
  row_on_blank_with_ctrl: decide(blank, rowZ, { ctrl: true }).action,
  row_on_blank_with_middle: decide(blank, rowZ, { middle: true }).action,
  row_on_drafted_surface: decide(drafted, rowZ).action,
  row_on_busy_surface: decide(busy, rowZ).action,
  row_on_other_mode_surface: decide(Object.assign({}, blank, { mode: 'code' }), rowZ).action,
  mode_click_home_mode: policy.decideModeClick({ mode: 'chat', home, tabs }).tab.id,
  mode_click_newest_doc: policy.decideModeClick({ mode: 'code', home, tabs }).tab.id,
  mode_click_no_doc: policy.decideModeClick({ mode: 'work', home, tabs }).action,
  new_chat_on_blank: policy.decideNewChat({ surface: blank }).action,
  new_chat_on_drafted: policy.decideNewChat({ surface: drafted }).action,
  new_chat_on_busy_keeps_mode: policy.decideNewChat({ surface: Object.assign({}, busy, { mode: 'code' }) }).mode,
  url_chat: policy.docUrlFor({ mode: 'chat', chatId: 'a b' }),
  url_code: policy.docUrlFor({ mode: 'code', chatId: 'c/1' }),
  url_work: policy.docUrlFor({ mode: 'work' }),
  blank_idle_with_content: policy.blankIdle(Object.assign({}, blank, { hasContent: true })),
};
process.stdout.write(JSON.stringify(report));
```

- [ ] **Step 2: Write the failing test**

`tests/test_a_sidebar_click_focuses_the_tab_that_already_has_it.py`:

```python
"""A sidebar row opens a tab the way Chrome opens one, and a conversation exists once.

Calvin's direction (2026-08-25): when I click on the left it actually opens up a
tab up top like Chrome, and a conversation exists once. So a row whose
conversation is already held by a tab focuses that tab; a row clicked on a
blank, idle surface navigates that surface in place, the way Chrome's new-tab
page does; anything else opens a new tab. Ctrl-click and middle-click always
open one. These are pure decisions, so they are driven through the real module
in a vm context by ``tests/web_node/browser_shell_docs_policy.mjs``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "browser_shell_docs_policy.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "browser_shell_docs_policy.mjs"


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    result = subprocess.run(
        ["node", str(HARNESS), str(POLICY_JS)],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_row_whose_conversation_a_tab_already_holds_focuses_that_tab(report) -> None:
    assert report["row_held_by_home"] == "focus:1"
    assert report["row_held_by_doc"] == "focus:2"


def test_a_row_on_a_blank_idle_surface_navigates_that_surface_in_place(report) -> None:
    assert report["row_on_blank_surface"] == "adopt"


def test_a_modifier_click_always_opens_a_new_tab(report) -> None:
    assert report["row_on_blank_with_ctrl"] == "open"
    assert report["row_on_blank_with_middle"] == "open"


def test_a_draft_or_a_running_turn_is_never_navigated_away_from(report) -> None:
    assert report["row_on_drafted_surface"] == "open"
    assert report["row_on_busy_surface"] == "open"
    assert report["blank_idle_with_content"] is False


def test_a_row_of_another_mode_never_adopts_this_surface(report) -> None:
    assert report["row_on_other_mode_surface"] == "open"


def test_a_mode_button_focuses_the_newest_tab_of_that_mode_or_opens_one(report) -> None:
    assert report["mode_click_home_mode"] == 1
    assert report["mode_click_newest_doc"] == 4
    assert report["mode_click_no_doc"] == "open"


def test_new_chat_reuses_a_blank_surface_and_spares_a_busy_one(report) -> None:
    assert report["new_chat_on_blank"] == "adopt"
    assert report["new_chat_on_drafted"] == "open"
    assert report["new_chat_on_busy_keeps_mode"] == "code"


def test_a_tab_document_address_never_attaches_the_chrome_and_only_code_deep_links(report) -> None:
    assert report["url_chat"] == "/?embed=1&browser=0"
    assert report["url_code"] == "/?embed=1&browser=0&forge_code=c%2F1"
    assert report["url_work"] == "/?embed=1&browser=0"
```

- [ ] **Step 3: Run it to see it fail**

Run: `python -m pytest tests/test_a_sidebar_click_focuses_the_tab_that_already_has_it.py -q`. Expected: FAIL in the fixture (`window.ThomasBrowserDocsPolicy missing` because the module file does not exist yet, so node exits 1).

- [ ] **Step 4: Write the policy module**

`thomas/server/web/js/browser_shell_docs_policy.js`:

```js
/* browser_shell_docs_policy.js — what a click on the left means, decided once.
 *
 * Calvin's rules (2026-08-25): a sidebar click opens a tab up top like Chrome,
 * and a conversation exists once. Chrome's own rule fills the gap: a row
 * clicked on a blank new-tab page navigates that page in place, and a
 * modifier click always opens a new tab. These decisions take plain values
 * and touch no DOM, so the node harness drives them without a browser and
 * every tab, home included, asks the same question the same way.
 */
"use strict";

(function () {
  const DOC_URL = "/?embed=1&browser=0";

  function docUrlFor(spec) {
    const mode = spec && (spec.mode === "code" || spec.mode === "work") ? spec.mode : "chat";
    const id = spec && spec.chatId ? String(spec.chatId) : "";
    return DOC_URL + (mode === "code" && id ? "&forge_code=" + encodeURIComponent(id) : "");
  }

  // A surface with nothing on it and nothing running: navigating it in place
  // loses nothing, exactly like Chrome's new-tab page.
  function blankIdle(surface) {
    if (!surface) return false;
    if (surface.chatId || surface.busy) return false;
    if (String(surface.draft || "").trim()) return false;
    return !surface.hasContent;
  }

  function holder(tabs, mode, id) {
    if (!id) return null;
    return (tabs || []).find(t => t && t.mode === mode && t.chatId === id) || null;
  }

  function decideRowClick(input) {
    const row = (input && input.row) || {};
    const tabs = (input && input.tabs) || [];
    const mods = (input && input.modifiers) || {};
    const held = holder(tabs, row.mode, row.id);
    if (held) return { action: "focus", tab: held };
    if (mods.ctrl || mods.meta || mods.middle) return { action: "open" };
    const surface = input && input.surface;
    if (surface && surface.mode === row.mode && blankIdle(surface)) return { action: "adopt" };
    return { action: "open" };
  }

  function decideModeClick(input) {
    const mode = input && input.mode;
    const home = input && input.home;
    if (home && home.mode === mode) return { action: "focus", tab: home };
    const docs = ((input && input.tabs) || []).filter(t => t && t.kind === "doc" && t.mode === mode);
    if (!docs.length) return { action: "open", mode };
    docs.sort((a, b) => (b.activatedAt || 0) - (a.activatedAt || 0));
    return { action: "focus", tab: docs[0] };
  }

  function decideNewChat(input) {
    const s = (input && input.surface) || {};
    if (s.busy || String(s.draft || "").trim()) return { action: "open", mode: s.mode || "chat" };
    return { action: "adopt" };
  }

  window.ThomasBrowserDocsPolicy = { decideRowClick, decideModeClick, decideNewChat, blankIdle, docUrlFor };
}());
```

- [ ] **Step 5: Run the test to see it pass**

Run: `python -m pytest tests/test_a_sidebar_click_focuses_the_tab_that_already_has_it.py -q`. Expected: 8 passed. Do not commit yet: the module has no caller until Task 3 lands (this repo treats finished code with no caller as debt), so Task 2 and Task 3 share one commit.

---

### Task 3: A tab is a document that is only ever hidden

**Files:**
- Create: `thomas/server/web/js/browser_shell_docs.js`
- Modify: `thomas/server/web/js/browser_shell.js` (tab machinery, interceptors, activate/hideAll/closeTab, home tab, panel ctx, boot)
- Modify: `thomas/server/web/js/browser_shell_panel.js:46-56` (doc case), `thomas/server/web/css/browser_shell.css`, `thomas/server/web/css/chat_shell.css`, `thomas/server/web/js/unified_code_projects.js:598-611`, `thomas/server/web/js/workspace_shell.js` (chain), `desktop/preload.js` (chain), `CHANGELOG.md`

**Interfaces:**
- Consumes: `window.ThomasBrowserDocsPolicy` (Task 2), `window.ThomasBrowserKeys` `attachTo` (Task 5; until then `keys.attachTo` is absent and skipped).
- Produces: `window.ThomasBrowserDocs.wire(ctx) -> docs` with `docs.open({mode, chatId, title}) -> tab`, `docs.hideAll()`, `docs.show(tab)`, `docs.remove(tab)`, `docs.reload(tab)`, `docs.installOn(tab, doc)` (interceptors for the top-level document), `docs.forwardSidebarToggle() -> boolean`, `docs.list() -> tab[]`. ctx is `{ rowWrap, asideEl, makeTab, byId, activate, setTitle, setStatus, getActiveId, getTabs, homeTab, keys, toast, wsByLabel, openWorkspaceTab, faceFor }`.
- Tab fields for kind `doc`: `{ mode: 'chat'|'code'|'work', chatId, frame, ready, suppress, activatedAt }`. Home tab gains `mode` (learned), `chatId` (learned), `pinned: true`.

- [ ] **Step 1: Read the three markers the wiring depends on**

Read `chat.html:995-1004` for the selected-row inline style (the selected row's `style` contains `--c-surface-2`), `chat.html:553-575` for the theme menu markup (`#tc-theme-btn` opens, `#tc-theme-options` holds one button per theme carrying the theme name text), and `unified_code_mode.js:698-708` for the code row `is-active` class. If any differs from this description, adapt `selectedRow()` and `pickTheme()` below to the actual markup and say so in the commit body.

- [ ] **Step 2: Write `browser_shell_docs.js`**

```js
/* browser_shell_docs.js — a tab is a document that is only ever hidden.
 *
 * Calvin's invariant (2026-09-01): one live DOM per tab. Switching shows and
 * hides persistent containers; drafts, scroll and in-flight streams survive;
 * nothing re-mounts on a switch. chat.html cannot give a second conversation
 * its own thread (selectChat wipes #tc-thread and aborts the stream, and the
 * file is beyond the monolith limit so it cannot change), so every extra
 * Chat, Build or Work tab is a second chat.html document in an iframe. The
 * top-level page stays the home tab and is never driven by the strip again.
 *
 * Hidden means visibility:hidden + inert on the frame and a paused living
 * world inside it — never display:none (which drops the child's layout and
 * scroll) and never a DOM move (which reloads an iframe).
 */
"use strict";

(function () {
  const policy = window.ThomasBrowserDocsPolicy;
  const LAST_CHAT = "thomas_last_chat";
  const LAST_SESSION = "thomas_last_session";
  const ROW_WAIT_MS = 15000;

  function wire(ctx) {
    const { rowWrap, asideEl, makeTab, byId, activate, setTitle, setStatus, getActiveId,
      getTabs, homeTab, keys, toast, wsByLabel, openWorkspaceTab, faceFor } = ctx;
    const docs = [];
    let seed = { session: null };

    function storage(fn) { try { return fn(localStorage); } catch (_) { return null; } }
    function docOf(tab) { return tab.frame && tab.frame.contentDocument; }
    function winOf(tab) { return tab.frame && tab.frame.contentWindow; }
    function shellOf(doc) { return doc && doc.getElementById("tc-shell"); }

    /* ── What a document says about itself ───────────────────────────── */
    function isBusy(doc, mode) {
      const btn = doc && doc.querySelector('.tc-mode-button[data-thomas-mode="' + mode + '"]');
      return Boolean(btn && btn.hasAttribute("data-running"));
    }
    function selectedRow(doc, mode) {
      if (!doc) return null;
      if (mode === "chat") {
        return Array.from(doc.querySelectorAll("#tc-chats [data-history-id]"))
          .find(r => (r.getAttribute("style") || "").indexOf("--c-surface-2") >= 0) || null;
      }
      return doc.querySelector("#tc-chats [data-history-id].is-active");
    }
    function surfaceState(tab, doc) {
      const input = doc && doc.getElementById("tc-input");
      const thread = doc && doc.getElementById("tc-thread");
      return {
        mode: tab.mode, chatId: tab.chatId || "", busy: isBusy(doc, tab.mode),
        draft: input ? input.value : "",
        hasContent: tab.mode === "chat" ? Boolean(thread && thread.childElementCount) : Boolean(selectedRow(doc, tab.mode)),
      };
    }
    function learn(tab, doc) {
      const row = selectedRow(doc, tab.mode);
      const id = row ? row.dataset.historyId : "";
      if (id !== (tab.chatId || "")) {
        tab.chatId = id;
        const label = row ? (row.dataset.historyTitle || "") : "";
        setTitle(tab, label || { chat: "Chat", code: "Build", work: "Work" }[tab.mode]);
        if (tab === homeTab) writeReloadTarget();
      }
    }

    /* ── Reload target: a reload of / comes back to what HOME held ─────── */
    function writeReloadTarget() {
      storage(ls => {
        if (homeTab.chatId) { ls.setItem(LAST_CHAT, homeTab.chatId); ls.setItem(LAST_SESSION, homeTab.chatId); }
        else { ls.removeItem(LAST_CHAT); if (seed.session) ls.setItem(LAST_SESSION, seed.session); else ls.removeItem(LAST_SESSION); }
      });
    }

    /* ── Interceptors: the same question from every document ──────────── */
    function decideRow(tab, doc, e) {
      const row = e.target.closest("#tc-chats [data-history-id]");
      if (!row || tab.suppress) return null;
      if (e.type === "auxclick" && e.button !== 1) return null;
      const spec = { id: row.dataset.historyId, mode: row.dataset.historyMode || tab.mode, title: row.dataset.historyTitle || "" };
      const d = policy.decideRowClick({ surface: surfaceState(tab, doc), row: spec, tabs: getTabs(),
        modifiers: { ctrl: e.ctrlKey, meta: e.metaKey, middle: e.type === "auxclick" } });
      return { spec, d };
    }
    function installOn(tab, doc) {
      const stop = e => { e.preventDefault(); e.stopPropagation(); };
      const onRow = e => {
        const hit = decideRow(tab, doc, e); if (!hit) return;
        if (hit.d.action === "adopt") { setTimeout(() => learn(tab, doc), 0); return; }
        stop(e);
        if (hit.d.action === "focus") activate(hit.d.tab.id);
        else open({ mode: hit.spec.mode, chatId: hit.spec.id, title: hit.spec.title });
      };
      doc.addEventListener("click", onRow, true);
      doc.addEventListener("auxclick", onRow, true);
      doc.addEventListener("click", e => {
        const btn = e.target.closest(".tc-mode-button[data-thomas-mode]"); if (!btn) return;
        stop(e);
        const d = policy.decideModeClick({ mode: btn.dataset.thomasMode, home: homeTab, tabs: getTabs() });
        if (d.action === "focus") activate(d.tab.id); else open({ mode: d.mode });
      }, true);
      doc.addEventListener("keydown", e => {
        if (!e.target.closest || !e.target.closest(".tc-mode-button[data-thomas-mode]")) return;
        if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(e.key) >= 0) stop(e);
      }, true);
      doc.addEventListener("click", e => {
        if (!e.target.closest("#tc-newchat")) return;
        const d = policy.decideNewChat({ surface: surfaceState(tab, doc) });
        if (d.action === "adopt") { setTimeout(() => learn(tab, doc), 0); return; }
        stop(e); open({ mode: d.mode });
      }, true);
      doc.addEventListener("click", e => {
        if (!e.target.closest("#tc-settings")) return;
        stop(e); openWorkspaceTab("settings");
      }, true);
      if (tab !== homeTab) doc.addEventListener("click", e => {
        const btn = e.target.closest("#tc-workspaces button"); if (!btn) return;
        const mode = wsByLabel[(btn.textContent || "").trim()]; if (!mode) return;
        stop(e); openWorkspaceTab(mode);
      }, true);
      // Busy per document: the mode button carries data-running for its mode.
      const sw = doc.getElementById("tc-mode-switch");
      if (sw) new MutationObserver(() => {
        const busy = isBusy(doc, tab.mode);
        if (busy && tab.status !== "working") setStatus(tab, "working");
        else if (!busy && tab.status === "working") { setStatus(tab, "done"); setTimeout(() => learn(tab, doc), 0); }
      }).observe(sw, { attributes: true, subtree: true, attributeFilter: ["data-running"] });
      const chats = doc.getElementById("tc-chats");
      if (chats) new MutationObserver(() => learn(tab, doc)).observe(chats, { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class"] });
      const shell = shellOf(doc);
      if (shell && tab === homeTab) new MutationObserver(() => { tab.mode = shell.dataset.surfaceMode || "chat"; })
        .observe(shell, { attributes: true, attributeFilter: ["data-surface-mode"] });
    }

    /* ── Opening and wiring a document tab ────────────────────────────── */
    function waitForRow(doc, id) {
      return new Promise(resolve => {
        const find = () => doc.querySelector('#tc-chats [data-history-id="' + CSS.escape(id) + '"]');
        const now = find(); if (now) return resolve(now);
        const wrap = doc.getElementById("tc-chats");
        if (!wrap) return resolve(null);
        const timer = setTimeout(() => { mo.disconnect(); resolve(null); }, ROW_WAIT_MS);
        const mo = new MutationObserver(() => { const r = find(); if (r) { clearTimeout(timer); mo.disconnect(); resolve(r); } });
        mo.observe(wrap, { childList: true, subtree: true });
      });
    }
    async function settle(tab, doc) {
      const row = await waitForRow(doc, tab.chatId);
      if (!row) { setStatus(tab, "error"); setTitle(tab, "Not in the list"); return; }
      if (selectedRow(doc, tab.mode) !== row) {
        tab.suppress = true;
        try { row.click(); } finally { setTimeout(() => { tab.suppress = false; }, 0); }
      }
    }
    async function wireDoc(tab) {
      const doc = docOf(tab), win = winOf(tab);
      if (!doc || !win || !shellOf(doc)) { setStatus(tab, "error"); return; }
      if (tab.mode !== "chat" && shellOf(doc).dataset.surfaceMode !== tab.mode && win.ThomasUnifiedModes) {
        try { await win.ThomasUnifiedModes.setMode(tab.mode); } catch (_) { /* the mode buttons stay honest */ }
      }
      if (tab.chatId && !(tab.mode === "code")) await settle(tab, doc);
      installOn(tab, doc);
      if (keys && keys.attachTo) keys.attachTo(win);
      tab.ready = true;
      tab.frame.classList.add("is-ready");
      if (getActiveId() === tab.id) show(tab);
      setStatus(tab, isBusy(doc, tab.mode) ? "working" : "idle");
      learn(tab, doc);
      writeReloadTarget();
    }
    function open(spec) {
      const mode = spec.mode === "code" || spec.mode === "work" ? spec.mode : "chat";
      const held = spec.chatId && getTabs().find(t => t.mode === mode && t.chatId === spec.chatId && (t.kind === "doc" || t === homeTab));
      if (held) { activate(held.id); return held; }
      const title = spec.title || { chat: "Chat", code: "Build", work: "Work" }[mode];
      const tab = makeTab({ kind: "doc", mode, chatId: spec.chatId || "", title, face: faceFor(mode),
        url: "thomas://" + mode + (spec.chatId ? "/" + spec.chatId : "") });
      tab.ready = false; tab.suppress = false;
      setStatus(tab, "working");
      if (mode === "chat" && spec.chatId) storage(ls => {
        if (seed.session == null) seed.session = ls.getItem(LAST_SESSION) || "";
        ls.setItem(LAST_CHAT, spec.chatId);
      });
      const frame = document.createElement("iframe");
      frame.className = "bt-doc";
      frame.title = title;
      frame.inert = true;
      frame.setAttribute("aria-hidden", "true");
      frame.addEventListener("load", () => { wireDoc(tab).catch(() => setStatus(tab, "error")); });
      frame.src = policy.docUrlFor({ mode, chatId: spec.chatId });
      rowWrap.appendChild(frame);
      tab.frame = frame;
      docs.push(tab);
      activate(tab.id);
      return tab;
    }

    /* ── Show and hide: the only thing a switch ever does ─────────────── */
    function pauseWorld(tab, paused) {
      const doc = docOf(tab);
      if (doc && doc.documentElement) doc.documentElement.classList.toggle("bt-doc-hidden", paused);
    }
    function hideAll() {
      docs.forEach(t => { t.frame.classList.remove("is-active"); t.frame.inert = true; t.frame.setAttribute("aria-hidden", "true"); pauseWorld(t, true); });
      asideEl.inert = true;
    }
    function show(tab) {
      tab.frame.classList.add("is-active"); tab.frame.inert = false; tab.frame.removeAttribute("aria-hidden");
      pauseWorld(tab, false);
      tab.activatedAt = Date.now();
      const doc = docOf(tab);
      if (tab.ready && doc && (!doc.activeElement || doc.activeElement === doc.body)) {
        const input = doc.getElementById("tc-input"); if (input) setTimeout(() => input.focus(), 40);
      }
    }
    function remove(tab) {
      const i = docs.indexOf(tab); if (i >= 0) docs.splice(i, 1);
      if (tab.frame) tab.frame.remove();
    }
    function reload(tab) {
      tab.ready = false; tab.frame.classList.remove("is-ready"); setStatus(tab, "working");
      if (tab.mode === "chat" && tab.chatId) storage(ls => ls.setItem(LAST_CHAT, tab.chatId));
      tab.frame.src = policy.docUrlFor({ mode: tab.mode, chatId: tab.chatId });
    }
    function forwardSidebarToggle() {
      const t = byId(getActiveId()); if (!t || t.kind !== "doc") return false;
      const btn = docOf(t) && docOf(t).getElementById("tc-sidebar-toggle");
      if (btn) btn.click();
      return true;
    }

    /* ── Theme relay: drive each document's own switcher ──────────────── */
    function pickTheme(doc, name) {
      const shell = shellOf(doc); if (!shell || shell.dataset.theme === name) return;
      const btn = doc.getElementById("tc-theme-btn"); if (!btn) return;
      btn.click();
      const label = (window.ThomasChatThemes && window.ThomasChatThemes.THEMES[name] || {}).name || name;
      const opt = Array.from(doc.querySelectorAll("#tc-theme-options button")).find(b => (b.textContent || "").indexOf(label) >= 0);
      if (opt) opt.click(); else btn.click();
    }
    window.addEventListener("thomas:themechange", e => {
      const name = e.detail && e.detail.theme; if (!name) return;
      docs.forEach(t => { const doc = docOf(t); if (doc) pickTheme(doc, name); });
    });
    window.addEventListener("pagehide", writeReloadTarget);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") writeReloadTarget(); });

    return { open, hideAll, show, remove, reload, installOn, forwardSidebarToggle, list: () => docs.slice(), learn };
  }

  window.ThomasBrowserDocs = { wire };
}());
```

- [ ] **Step 3: Rewire `browser_shell.js`**

Exact edits, top to bottom:

1. Home tab (today `const homeTab = makeTab({ kind: "chat-home", ... })`): add `mode: shell.dataset.surfaceMode || "chat", chatId: "", pinned: true` to the spec, and after creation `homeTab.el.classList.add("is-pinned")`.
2. Delete `clickModeButton`, `clickChatRow` and `suppressIntercept` (lines 331-345 today), the mode-button capture listener (416-425), the conversation-row capture listener (430-437), the `newChatBtn` listener (440-441), `openModeTab` and `openChatTabFor` (399-411), and the `#tc-send-icon` MutationObserver block (726-740).
3. `hideAllSurfaces()`: keep the `.tc-workspace-frame` sweep and the primary column lines; add `docs.hideAll();` as the last statement.
4. `showPrimary()`: add `asideEl.inert = false;`.
5. `activate(id)`: the chat branch becomes `if (tab.kind === "chat-home") { showPrimary(); } else if (tab.kind === "doc") { docs.show(tab); } else if (tab.kind === "ws") { asideEl.inert = false; ... }` and the `web`/`page` branches also set `asideEl.inert = false`. Record `tab.activatedAt = Date.now()` for every kind.
6. `closeTab(id)`: first line after lookup: `if (tab.pinned) return;`; add `if (tab.kind === "doc") docs.remove(tab);` before the strip button is removed.
7. `#bt-reload` handler: before the `t.frame` branch add `if (t.kind === "doc") { docs.reload(t); return; }`.
8. Bookmarks-bar sidebar toggle: after `bookbar.appendChild(sidebarToggle)` add `sidebarToggle.addEventListener("click", e => { if (docs.forwardSidebarToggle()) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);`.
9. Panel ctx: pass `bodyRow: rowWrap` (so the side panel is appended into `.bt-row` and paints above document frames).
10. After the keys wiring and before the search wiring, create the docs module:

```js
  /* ── Document tabs: every extra Chat, Build or Work tab is its own page ── */
  const docs = window.ThomasBrowserDocs.wire({
    rowWrap, asideEl, makeTab, byId, activate, setTitle, setStatus, toast, wsByLabel, openWorkspaceTab,
    getActiveId: () => activeId, getTabs: () => tabs.slice(), homeTab, keys,
    faceFor: mode => ({ chat: "chat", code: "build", work: "work" }[mode] || "chat"),
  });
  docs.installOn(homeTab, document);
```

`docs` is referenced by `hideAllSurfaces`/`activate`/`closeTab` only at call time (after boot), so declaring it here is safe; `activate(homeTab.id)` at boot runs after this block. Keep the `docs` declaration ABOVE the final `activate(homeTab.id)`.

11. Boot: unchanged `loadPluginRoutes(); activate(homeTab.id);`.

- [ ] **Step 4: Panel doc case**

In `renderContextPanel`, before the final `else`:

```js
      } else if (t.kind === "doc") {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<button class="bt-pm-item" type="button" data-sp="reload">' + SVG.reload + " Reload this tab</button>"
          + '<p class="bt-sp-note">' + ({ chat: "This conversation", code: "This build", work: "This job" }[t.mode] || "This tab")
          + " has its own page. Switching tabs hides it and never resets it.</p>";
```

and change the reload handler's frame branch to `else if (t.kind === "doc") navrow.querySelector("#bt-reload").click(); else if (t.frame) t.frame.src = t.frame.src;`.

- [ ] **Step 5: CSS**

`browser_shell.css`, after the `.bt-page` rules:

```css
/* ── Document tabs ──────────────────────────────────────────────────── */
/* A second chat.html per tab. Hidden with visibility, never display: the
   child keeps its layout, so its scroll position and its running stream are
   untouched. The frame covers sidebar and main, so each tab is a whole
   Thomas with its own sidebar. Deliberately NOT .tc-workspace-frame: the
   chat page's own frame sweeps must never touch these. */
.bt-doc { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; z-index: 20;
  background: var(--c-bg); visibility: hidden; pointer-events: none; color-scheme: dark; }
.bt-doc.is-active.is-ready { visibility: visible; pointer-events: auto; }
html[data-theme="light"] .bt-doc, html[data-theme="sandstone"] .bt-doc { color-scheme: light; }
/* The home tab is pinned in this version: closing it would orphan the page. */
.bt-tab.is-pinned .bt-tab-x { display: none; }
```

`chat_shell.css`, at the end:

```css
/* A tab document (chat.html embedded by the browser shell) shows no header:
   the shell already carries one model pill and one theme switcher. */
html.is-embedded main > header { display: none !important; }
html.is-embedded #tc-build-badge { display: none !important; }
/* A hidden tab keeps its DOM but not its animations. */
html.bt-doc-hidden .tc-world, html.bt-doc-hidden .tc-world * { animation-play-state: paused !important; }
```

- [ ] **Step 6: Guard the surface snapshot in `unified_code_projects.js`**

At the top of `bootSurfaceRestore()`:

```js
    // A tab document is not the reload target: it neither restores nor records
    // the last surface, or every hidden Build tab would rewrite it each second.
    if (window.parent !== window) return;
```

- [ ] **Step 7: Chains**

`workspace_shell.js` and `desktop/preload.js`: insert `"/static/js/browser_shell_docs_policy.js",` and `"/static/js/browser_shell_docs.js",` after the `browser_shell_web.js` entry and before `browser_shell.js`.

- [ ] **Step 8: Verify by hand on 8931 before the browser test exists**

`node --check` on every touched JS; line counts (`browser_shell.js` under 800, each new file under 300). In the driver, open `/?browser=1`, click a sidebar conversation: a `.bt-doc` iframe appears in `.bt-row`, its computed `visibility` is `visible` only after `is-ready`, the top-level `#tc-primary-column` computed visibility is `hidden`, the top-level `#tc-thread` did not change. Type in the doc's composer, click the Chat tab, click back: the text is still there. Console has no errors. Run the Task 2 test again: pass.

- [ ] **Step 9: CHANGELOG + commit**

CHANGELOG:

```
### Added (every tab is its own document, and switching never re-mounts one)

- **Conversations and Build/Work tabs now hold their own page.** Calvin asked
  for tabs that come back exactly where you left off. Until now the strip
  drove the one shared chat surface: switching to another conversation wiped
  your draft, emptied the thread and aborted the running reply. Every extra
  Chat, Build or Work tab is now a second chat page in its own frame
  (`js/browser_shell_docs.js`), hidden with visibility and inert on a switch,
  never with display:none and never detached, so drafts, scroll position and
  in-flight streams survive.
- **A conversation exists once** (`js/browser_shell_docs_policy.js`): a row
  already held by a tab focuses it; a row clicked on a blank idle tab opens
  in place; anything else opens a new tab; Ctrl-click and middle-click always
  open one. The home tab is pinned in this version, and a conversation that
  never renders a row is titled Not in the list rather than faked.
```

Commit subject: `feat(browser): a tab is a document that is only ever hidden`. Body: what changed and why in prose, the marker facts from Step 1, and the trailer. Include paths: the two new modules, `browser_shell.js`, `browser_shell_panel.js`, `browser_shell.css`, `chat_shell.css`, `unified_code_projects.js`, `workspace_shell.js`, `desktop/preload.js`, the two Task 2 test files, `CHANGELOG.md`.

---

### Task 4: A tab switch is only ever a hide, proven in a browser

**Files:**
- Create: `tests/web_fixtures/__init__.py` (empty), `tests/web_fixtures/thomas_chat_fixture.py`
- Create: `tests/test_a_tab_switch_is_only_ever_a_hide.py`
- Create: `tests/test_a_conversation_exists_once_across_tabs.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `thomas_chat_fixture.serve() -> ThomasFixture` context manager with `.url` (`http://127.0.0.1:<port>`), `.requests` (list of `(method, path)`), `.chat_calls` (count of POST /api/v2/chat). Serves `/` (any query) with chat.html from disk (placeholder `__THOMAS_WEB_BUILD__` replaced by `fixture`), `/static/*` from `thomas/server/web/`, and the API stubs below. Non-loopback hosts are never contacted because the page only ever asks its own origin; the tests additionally `page.route("**/*", abort)` for any non-loopback URL.

- [ ] **Step 1: Write the fixture server**

```python
"""A tiny Thomas that serves the real chat page and answers every API it asks.

Every stub is the smallest body the page tolerates at boot. The reply to
POST /api/v2/chat drips one NDJSON text event every 150 ms for about three
seconds, which is what lets a test watch a bubble grow inside a HIDDEN tab.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "thomas" / "server" / "web"
CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                 ".html": "text/html", ".json": "application/json", ".svg": "image/svg+xml",
                 ".png": "image/png", ".woff2": "font/woff2"}


def _messages(prefix: str, count: int) -> list[dict[str, str]]:
    rows = []
    for i in range(count):
        rows.append({"role": "user", "content": f"{prefix} question {i}"})
        rows.append({"role": "assistant", "content": f"{prefix} answer {i} " + "words " * 30})
    return rows


def chats_body() -> dict[str, object]:
    return {"chats": [
        {"id": cid, "session_id": cid, "title": title, "updatedAt": 1000 + n,
         "messages": _messages(title, 20), "model": "fixture"}
        for n, (cid, title) in enumerate([("chat-a", "Alpha"), ("chat-b", "Beta"), ("chat-c", "Gamma")])
    ]}


STUBS: dict[str, object] = {
    "/api/models": {"profiles": [{"name": "local", "provider": "local", "has_api_key": True,
                                   "models": [{"id": "fixture-1", "label": "Fixture model"}]}],
                    "preferences": {"active_profile": "local"}, "default": "local"},
    "/api/marketplace/installed": {"plugins": []},
    "/api/preferences": {},
    "/api/health": {"status": "ok", "version": "fixture", "commit": "fixture"},
    "/api/evolve/agent/status": {"running": False},
    "/api/evolve/agent/conversations": {"conversations": []},
    "/api/local/projects": {"projects": []},
    "/api/chats/title": {},
    "/api/issues": {},
}


@dataclass
class ThomasFixture:
    url: str
    requests: list[tuple[str, str]] = field(default_factory=list)
    chat_calls: int = 0


def _handler(fixture: ThomasFixture):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:  # keep pytest output clean
            return

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object) -> None:
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            fixture.requests.append(("GET", self.path))
            if path == "/":
                html = (WEB_DIR / "chat.html").read_text(encoding="utf-8").replace("__THOMAS_WEB_BUILD__", "fixture")
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                target = (WEB_DIR / path[len("/static/"):]).resolve()
                if WEB_DIR in target.parents and target.is_file():
                    return self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
                return self._send(404, b"", "text/plain")
            if path.startswith("/api/chats") and "mode=chat" in self.path:
                return self._json(chats_body())
            if path.startswith("/api/v2/chat/session/"):
                return self._json({"delegations": []})
            if path in STUBS:
                return self._json(STUBS[path])
            return self._json({})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            fixture.requests.append(("POST", self.path))
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if path == "/api/session/new":
                return self._json({"session_id": f"fresh-{len(fixture.requests)}"})
            if path == "/api/v2/chat":
                fixture.chat_calls += 1
                return self._drip(body)
            return self._json({})

        def _drip(self, body: bytes) -> None:
            try:
                asked = json.loads(body.decode("utf-8") or "{}").get("message", "")
            except (ValueError, UnicodeDecodeError):
                asked = ""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for i in range(20):
                line = json.dumps({"type": "text", "text": f"piece {i} of the reply to {asked[:12]}. "}) + "\n"
                chunk = line.encode("utf-8")
                self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                self.wfile.flush()
                time.sleep(0.15)
            done = (json.dumps({"type": "done", "session_id": "fresh-done"}) + "\n").encode("utf-8")
            self.wfile.write(f"{len(done):x}\r\n".encode("ascii") + done + b"\r\n0\r\n\r\n")
            self.wfile.flush()

        def do_PATCH(self) -> None:  # noqa: N802
            fixture.requests.append(("PATCH", self.path))
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._json({})

        def do_DELETE(self) -> None:  # noqa: N802
            fixture.requests.append(("DELETE", self.path))
            return self._json({})

    return Handler


class serve:
    """Context manager: a fixture Thomas on a free loopback port."""

    def __enter__(self) -> ThomasFixture:
        self.fixture = ThomasFixture(url="")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.fixture))
        self.server.daemon_threads = True
        self.fixture.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.fixture

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
```

- [ ] **Step 2: Write the first browser test**

`tests/test_a_tab_switch_is_only_ever_a_hide.py` (the `_browser_ok` probe copied from `tests/test_the_run_report_verdict_tells_the_truth.py:98-120`, `pytestmark = pytest.mark.skipif(not _browser_ok(), ...)`, and a module fixture that starts the fixture server, launches chromium at 1440x900, routes any non-loopback URL to abort, and opens `/?browser=1`):

```python
VIS = """(sel) => { const el = document.querySelector(sel); if (!el) return null;
  const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
  return { visibility: cs.visibility, display: cs.display, w: Math.round(r.width), h: Math.round(r.height), inert: !!el.inert }; }"""


def _open_row(page, title: str):
    page.click(f'#tc-chats [data-history-title="{title}"]')
    frame = page.wait_for_selector("iframe.bt-doc.is-ready", timeout=20000)
    return frame


def test_a_sidebar_row_opens_its_own_document_and_leaves_home_untouched(shell) -> None:
    page = shell.page
    home_thread_before = page.evaluate("() => document.getElementById('tc-thread').childElementCount")
    _open_row(page, "Beta")
    assert page.evaluate("() => document.querySelectorAll('iframe.bt-doc').length") == 1
    src = page.evaluate("() => document.querySelector('iframe.bt-doc').getAttribute('src')")
    assert src.startswith("/?embed=1&browser=0") and "forge_code" not in src
    assert page.evaluate(VIS, "iframe.bt-doc")["visibility"] == "visible"
    assert page.evaluate(VIS, "#tc-primary-column")["visibility"] == "hidden"
    assert page.evaluate(VIS, "#tc-primary-column")["inert"] is True
    assert page.evaluate("() => document.querySelector('aside.tc-sidebar').inert") is True
    doc = page.frames[1]
    doc.wait_for_function("() => document.getElementById('tc-thread').childElementCount > 0", timeout=20000)
    assert page.evaluate("() => document.getElementById('tc-thread').childElementCount") == home_thread_before
    assert page.evaluate("() => document.querySelector('.bt-tab.is-active .bt-tab-title').textContent") == "Beta"


def test_a_draft_and_the_scroll_position_survive_a_switch_away_and_back(shell) -> None:
    page = shell.page
    doc = page.frames[1]
    doc.fill("#tc-input", "draft that must survive")
    doc.evaluate("() => { document.getElementById('tc-scroll').scrollTop = 300; }")
    page.fill("#tc-input", "home draft too")
    identity = doc.evaluate("() => { window.__ident = Math.random(); return window.__ident; }")
    page.click(".bt-tab.is-pinned")
    assert page.evaluate(VIS, "iframe.bt-doc")["visibility"] == "hidden"
    assert page.evaluate("() => document.querySelector('iframe.bt-doc').inert") is True
    assert doc.evaluate("() => document.documentElement.classList.contains('bt-doc-hidden')") is True
    page.keyboard.press("Control+2")
    assert page.evaluate(VIS, "iframe.bt-doc")["visibility"] == "visible"
    assert doc.evaluate("() => window.__ident") == identity
    assert doc.evaluate("() => document.getElementById('tc-input').value") == "draft that must survive"
    assert doc.evaluate("() => document.getElementById('tc-scroll').scrollTop") == 300
    assert page.evaluate("() => document.getElementById('tc-input').value") == "home draft too"
    assert doc.evaluate("() => getComputedStyle(document.querySelector('.tc-world.is-nebula > *') || document.body).animationPlayState") != "paused"


def test_a_reply_keeps_streaming_while_its_tab_is_hidden(shell) -> None:
    page = shell.page
    doc = page.frames[1]
    doc.fill("#tc-input", "stream while hidden")
    doc.press("#tc-input", "Enter")
    page.wait_for_timeout(500)
    page.click(".bt-tab.is-pinned")
    page.wait_for_timeout(700)
    grow = "() => { const b = document.querySelectorAll('#tc-thread .tc-bubble'); return b.length ? b[b.length-1].textContent.length : 0; }"
    first = doc.evaluate(grow)
    assert page.evaluate("() => document.querySelectorAll('.bt-tab')[1].querySelector('.bt-light').classList.contains('working')") is True
    page.wait_for_timeout(1200)
    assert doc.evaluate(grow) > first
    doc.wait_for_function("() => !document.querySelector('.tc-mode-button[data-thomas-mode=chat]').hasAttribute('data-running')", timeout=10000)
    assert shell.fixture.chat_calls == 1
    assert "[stopped]" not in doc.evaluate("() => document.getElementById('tc-thread').textContent")


def test_closing_a_document_tab_removes_it_and_the_home_tab_cannot_be_closed(shell) -> None:
    page = shell.page
    page.click(".bt-tab:not(.is-pinned) .bt-tab-x")
    assert page.evaluate("() => document.querySelectorAll('iframe.bt-doc').length") == 0
    assert page.evaluate("() => document.querySelectorAll('.bt-tab').length") == 1
    assert page.evaluate(VIS, ".bt-tab.is-pinned .bt-tab-x")["display"] == "none"
    page.keyboard.press("Control+w")
    assert page.evaluate("() => document.querySelectorAll('.bt-tab').length") == 1
    assert page.evaluate(VIS, "#tc-primary-column")["visibility"] == "visible"
```

The selector `.tc-bubble` must match what chat.html's `buildMessageNode` renders for an assistant message; read `chat.html` around `function buildMessageNode` and use the real class (adjust `grow` if it is different). `data-history-title` is set on each row by `renderChats` (chat.html:1002).

- [ ] **Step 3: Write the second browser test**

`tests/test_a_conversation_exists_once_across_tabs.py` (same probe and fixture):

```python
def test_the_build_button_opens_a_build_document_and_home_stays_in_chat(shell) -> None:
    page = shell.page
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    page.wait_for_selector("iframe.bt-doc.is-ready", timeout=20000)
    build = page.frames[1]
    build.wait_for_function("() => document.getElementById('tc-shell').dataset.surfaceMode === 'code'", timeout=10000)
    assert page.evaluate("() => document.getElementById('tc-shell').dataset.surfaceMode") == "chat"
    assert build.evaluate("() => getComputedStyle(document.getElementById('tc-mode-surface')).display") == "flex"
    page.click(".bt-tab.is-pinned")
    page.click('.tc-mode-button[data-thomas-mode="code"]')
    assert page.evaluate("() => document.querySelectorAll('iframe.bt-doc').length") == 1
    assert page.evaluate("() => document.querySelector('.bt-tab.is-active .bt-tab-title').textContent") == "Build"
    assert page.evaluate("() => localStorage.getItem('thomas.lastSurface') || ''").find('"code"') < 0


def test_a_row_clicked_inside_another_tab_focuses_the_tab_that_holds_it(shell) -> None:
    page = shell.page
    page.click(".bt-tab.is-pinned")
    page.click('#tc-chats [data-history-title="Beta"]')
    page.wait_for_selector("iframe.bt-doc.is-ready >> nth=1", timeout=20000)
    page.click(".bt-tab.is-pinned")
    page.click('#tc-chats [data-history-title="Gamma"]')
    page.wait_for_selector("iframe.bt-doc.is-ready >> nth=2", timeout=20000)
    gamma = page.frames[3]
    gamma.fill("#tc-input", "gamma keeps this")
    gamma.click('#tc-chats [data-history-title="Beta"]')
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.querySelectorAll('iframe.bt-doc').length") == 3
    assert page.evaluate("() => document.querySelector('.bt-tab.is-active .bt-tab-title').textContent") == "Beta"
    assert gamma.evaluate("() => document.getElementById('tc-input').value") == "gamma keeps this"


def test_settings_opens_one_workspace_tab_from_anywhere(shell) -> None:
    page = shell.page
    page.click("#tc-settings")
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.querySelectorAll('iframe.tc-workspace-frame.bt-frame').length") == 1
    assert page.evaluate("() => document.getElementById('tc-direct-frame')") is None
    gamma = page.frames[3]
    gamma.click("#tc-settings")
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.querySelectorAll('iframe.tc-workspace-frame.bt-frame').length") == 1


def test_a_theme_change_reaches_every_document(shell, tmp_path) -> None:
    page = shell.page
    page.click("#bt-profile")
    page.click("#tc-theme-btn")
    page.click('#tc-theme-options button:has-text("Light")')
    page.wait_for_function("() => Array.from(document.querySelectorAll('iframe.bt-doc')).every(f => f.contentDocument.getElementById('tc-shell').dataset.theme === 'light')", timeout=5000)
    for i, frame in enumerate(page.frames[1:], start=1):
        assert frame.evaluate("() => getComputedStyle(document.body).backgroundColor") == page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    page.screenshot(path=str(tmp_path / "light.png"))
```

The `Light` option text must match `window.ThomasChatThemes.THEMES.light.name` (read `chat_themes.js`); adjust the `has-text` if the label is `Daylight` or similar.

- [ ] **Step 4: Run the browser tests**

Run: `python -m pytest tests/test_a_tab_switch_is_only_ever_a_hide.py tests/test_a_conversation_exists_once_across_tabs.py -rs -q`. Expected: all pass and NONE skipped (a skip is not a proof; if the probe skips on this machine, fix the probe or the environment, do not proceed). If an assertion fails, read the page console via `page.on("console")` output captured in the fixture and fix the shell, not the test.

- [ ] **Step 5: CHANGELOG + commit**

CHANGELOG: `### Added (the tab invariant is tested in a real browser)` describing the fixture Thomas and the four survival facts it pins (draft, scroll, document identity, a reply that keeps streaming while hidden). Commit subject: `test(browser): a tab switch is only ever a hide, proven in a browser`. Include the three test files, the fixture package and CHANGELOG.

---

### Task 5: Tab shortcuts the browser does not eat

**Files:**
- Modify: `thomas/server/web/js/browser_shell_keys.js`
- Modify: `thomas/server/web/js/browser_shell.js` (the keys callbacks return booleans; the + page lists the bindings via `browser_shell_web.js`)
- Create: `tests/web_node/browser_shell_keys.mjs`, `tests/test_a_shortcut_the_browser_keeps_still_has_a_twin_here.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `window.ThomasBrowserKeys.wire(ctx) -> { handle, actionFor, attachTo, bindings }`. `handle(action, arg) -> boolean` returns false when the action was a no-op (so the browser default is not cancelled). `attachTo(win)` installs the same capture listener on another window. `bindings() -> [{ keys, does, everywhere }]`.
- ctx callbacks now return booleans: `cycleTab` false when fewer than two tabs, `selectTabIndex` false when no such tab, `goBack`/`goForward` false when disabled, `closeActiveTab` false on the pinned home.

- [ ] **Step 1: Harness + failing test**

`tests/web_node/browser_shell_keys.mjs`: load the module in a vm context with `window = { addEventListener(type, fn) { listeners.push([type, fn]); } }`, `navigator = { platform: 'Win32' }`, wire it with recording callbacks (each returns true except `goBack`, which returns false), then build synthetic events `{ key, code, ctrlKey, metaKey, altKey, shiftKey, getModifierState: () => false, preventDefault() { this.prevented = true; }, stopPropagation() {} }` and report: `actionFor` for Ctrl+2, Ctrl+9, Alt+3 (code Digit3), Alt+3 with AltGraph, Ctrl+Shift+] (code BracketRight), Ctrl+Shift+[ , Alt+PageDown, Alt+PageUp, Ctrl+Tab, plain '3', Ctrl+Shift+3; dispatch Alt+Left through the listener and report `prevented` (must be false because goBack returned false); call `attachTo(fakeWin)` and report that the fake window got a keydown listener; report `bindings().length`.

`tests/test_a_shortcut_the_browser_keeps_still_has_a_twin_here.py` asserts: Ctrl+2 selects tab 2; Ctrl+9 selects 9; Alt+3 selects 3; Alt+3 with AltGraph is null; Ctrl+Shift+] is next-tab and Ctrl+Shift+[ prev-tab; Alt+PageDown/PageUp cycle; Ctrl+Tab still maps to next-tab (kept for the desktop app); plain 3 and Ctrl+Shift+3 are null; Alt+Left leaves `prevented` false; `attachTo` installed a keydown listener on the given window; `bindings()` lists at least the five alternates and marks Ctrl+T/W/Tab as not everywhere.

Run the .py test: FAIL (harness reports missing `attachTo`).

- [ ] **Step 2: Implement in `browser_shell_keys.js`**

Replace `handle` with:

```js
    function handle(action, arg) {
      if (action === "select-tab") return selectTabIndex(arg) !== false;
      const fn = ACTIONS[action];
      if (!fn) return false;
      return fn() !== false;
    }
```

Extend `actionFor`:

```js
    function actionFor(e) {
      const ctrl = e.ctrlKey || e.metaKey;
      const altGraph = typeof e.getModifierState === "function" && e.getModifierState("AltGraph");
      if (ctrl && !e.altKey) {
        const key = String(e.key || "").toLowerCase();
        if (key === "t" && !e.shiftKey) return ["new-tab"];
        if (key === "w" && !e.shiftKey) return ["close-tab"];
        if (key === "l" && !e.shiftKey) return ["focus-omnibox"];
        if (key === "r" && !e.shiftKey) return ["reload"];
        if (e.key === "Tab") return [e.shiftKey ? "prev-tab" : "next-tab"];
        if (/^[1-9]$/.test(e.key) && !e.shiftKey) return ["select-tab", Number(e.key)];
        // Cmd+Shift+brackets is reserved on macOS, so this pair is Ctrl only.
        if (e.shiftKey && e.ctrlKey && !e.metaKey && e.code === "BracketRight") return ["next-tab"];
        if (e.shiftKey && e.ctrlKey && !e.metaKey && e.code === "BracketLeft") return ["prev-tab"];
      }
      if (e.altKey && !ctrl && !altGraph) {
        if (e.key === "ArrowLeft") return ["back"];
        if (e.key === "ArrowRight") return ["forward"];
        if (String(e.key || "").toLowerCase() === "d") return ["focus-omnibox"];
        if (/^Digit[1-9]$/.test(String(e.code || "")) && !/Mac/.test(navigator.platform || "")) return ["select-tab", Number(e.code.slice(5))];
        if (e.key === "PageDown") return ["next-tab"];
        if (e.key === "PageUp") return ["prev-tab"];
      }
      if (e.key === "F5" && !ctrl && !e.altKey) return ["reload"];
      return null;
    }
```

Add:

```js
    function listener(e) {
      const hit = actionFor(e);
      if (!hit) return;
      if (handle(hit[0], hit[1])) { e.preventDefault(); e.stopPropagation(); }
    }
    function attachTo(win) { win.addEventListener("keydown", listener, true); }
    attachTo(window);
    function bindings() {
      return [
        { keys: "Ctrl+1..9", does: "that tab (9 is the last)", everywhere: true },
        { keys: "Alt+1..9", does: "that tab", everywhere: true },
        { keys: "Ctrl+Shift+] / Ctrl+Shift+[", does: "next / previous tab", everywhere: true },
        { keys: "Alt+PageDown / Alt+PageUp", does: "next / previous tab", everywhere: true },
        { keys: "Ctrl+L / Alt+D", does: "the address bar", everywhere: true },
        { keys: "Ctrl+Tab / Ctrl+Shift+Tab", does: "next / previous tab", everywhere: false },
        { keys: "Ctrl+T / Ctrl+W", does: "new / close tab", everywhere: false },
      ];
    }
    return { handle, actionFor, attachTo, bindings };
```

Rewrite the header comment: which combos Chrome and Edge keep for themselves in a plain tab (Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab, Ctrl+PageUp/PageDown), which reach the page (Ctrl+1..9 expected, Ctrl+L, Ctrl+R, F5, Alt+D, Alt+arrows), and the alternates that reach it everywhere. State that a no-op never cancels the browser's own default.

- [ ] **Step 3: Callbacks in `browser_shell.js` return booleans; the + page shows the table**

`cycleTab`: `if (tabs.length < 2) return false; ...; return true;`. `selectTabIndex`: `if (!tab) return false; activate(tab.id); return true;`. `closeActiveTab`: `const t = byId(activeId); if (!t || t.pinned) return false; closeTab(activeId); return true;`. `goBack`/`goForward`: return false when the button is disabled. In `browser_shell_web.js` `ntpHTML`, after the workspace tiles append a `<div class="bt-ntp-label">Shortcuts</div>` plus one line per binding with `everywhere: true` from `ctx.keys.bindings()` (pass `keys` in the web ctx; render with `esc`).

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_a_shortcut_the_browser_keeps_still_has_a_twin_here.py tests/test_a_tab_switch_is_only_ever_a_hide.py -q`. Expected: pass. In the driver on 8931 with a doc tab focused (its composer has focus): Alt+1 goes home, Ctrl+Shift+] goes to the next tab, typing a digit into the composer still types.

- [ ] **Step 5: CHANGELOG + commit**

CHANGELOG `### Added (tab shortcuts the browser does not eat)`: name the alternates, say which Chrome bindings a plain browser keeps for itself, and that a shortcut whose action does nothing no longer swallows the browser's own default. Commit subject: `feat(browser): tab shortcuts the browser does not eat`. State in the body that headless key delivery is evidence of the handler, not proof of real-browser delivery, and which combos were checked by hand (fill in from Task 7).

---

### Task 6: The browser chrome is on unless you turn it off

**Files:**
- Modify: `thomas/server/web/js/workspace_shell.js:180-231`
- Modify: `desktop/preload.js` (attached guard), `thomas/server/web/js/browser_shell.js` (Classic layout item)
- Create: `tests/web_node/workspace_shell_gate.mjs`, `tests/test_the_chrome_is_on_unless_you_turn_it_off.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `window.ThomasWorkspaceShell.browserChromeDecision({ search, stored, desktop, embedded, attached, shell }) -> { attach: boolean, reason: string }` (pure; `maybeAttachBrowserChrome` calls it).

- [ ] **Step 1: Harness + failing test**

`tests/web_node/workspace_shell_gate.mjs`: run `workspace_shell.js` in a vm context with `window = { addEventListener() {}, matchMedia: () => ({ matches: false }), parent: null }` (set `window.parent = window` after creation), `document = { readyState: 'loading', addEventListener() {}, querySelectorAll: () => [], querySelector: () => null, getElementById: () => null, documentElement: { dataset: {}, style: { length: 0, setProperty() {}, removeProperty() {} }, classList: { add() {} } }, body: null }`, `localStorage = { getItem: () => null, setItem() {} }`, `location = { search: '', pathname: '/', origin: 'http://x', href: 'http://x/' }`, `CustomEvent = class {}`, `URLSearchParams`, `Promise`, `setTimeout`, `queueMicrotask`. Report `browserChromeDecision` for: defaults (all falsy, search '') ; `?browser=0`; stored `off`; `?browser=1` with stored `off`; `desktop: true`; `embedded: true`; `attached: true`; `shell: false`.

`tests/test_the_chrome_is_on_unless_you_turn_it_off.py`: asserts on by default, off for `?browser=0`, off for stored `off`, `?browser=1` beats stored `off`, never in the desktop app, never inside an embed, never twice, never without the chat shell; plus two source pins: `desktop/preload.js` contains `getElementById("bt-titlebar")` before its chain loads, and `browser_shell.js` contains `thomas_browser_shell` with `"off"` next to a `Classic layout` label.

- [ ] **Step 2: Implement**

In `workspace_shell.js`, replace `browserChromeRequested` and the guards at the top of `maybeAttachBrowserChrome` with:

```js
  /* The browser chrome is the web UI's default frame (owner charter,
   * 2026-09-01: tabs need no Electron). Off only when asked: ?browser=0, or
   * thomas_browser_shell=off (the profile menu's Classic layout writes it).
   * ?browser=1 always wins, so a link can force the chrome back on. The
   * desktop app attaches the same chain through its preload, so a page that
   * already has window.thomasDesktop or a titlebar never attaches twice. */
  function browserChromeDecision(input) {
    const search = String(input.search || "");
    const params = new URLSearchParams(search);
    if (input.embedded) return { attach: false, reason: "embedded" };
    if (input.desktop) return { attach: false, reason: "desktop-app" };
    if (input.attached) return { attach: false, reason: "already-attached" };
    if (!input.shell) return { attach: false, reason: "no-chat-shell" };
    if (params.get("browser") === "0") return { attach: false, reason: "query-off" };
    if (params.get("browser") === "1") return { attach: true, reason: "query-on" };
    if (String(input.stored || "") === "off") return { attach: false, reason: "stored-off" };
    return { attach: true, reason: "default-on" };
  }
  function maybeAttachBrowserChrome() {
    let stored = "";
    try { stored = localStorage.getItem("thomas_browser_shell") || ""; } catch (_) { stored = ""; }
    const decision = browserChromeDecision({
      search: location.search, stored, desktop: Boolean(window.thomasDesktop),
      embedded: window.parent !== window, attached: Boolean(document.getElementById("bt-titlebar")),
      shell: Boolean(document.getElementById("tc-shell")),
    });
    if (!decision.attach) return;
    ...existing css + chain loading unchanged...
  }
```

Export `browserChromeDecision` on `window.ThomasWorkspaceShell`. In `desktop/preload.js` `attachBrowserChrome()` first line: `if (document.getElementById("bt-titlebar")) return;`. In `browser_shell.js` profile menu, after the Settings item: `'<button class="bt-pm-item" id="bt-pm-classic" type="button">' + SVG.panel + " Classic layout</button>"` with handler `try { localStorage.setItem("thomas_browser_shell", "off"); } catch (_) {} location.reload();`.

- [ ] **Step 3: Run**

`python -m pytest tests/test_the_chrome_is_on_unless_you_turn_it_off.py tests/test_a_tab_switch_is_only_ever_a_hide.py -q` (the browser tests now open `/` without `?browser=1`; change the fixture URL accordingly). Driver on 8931: `/` shows the titlebar by default, `/?browser=0` does not, the profile menu shows Classic layout.

- [ ] **Step 4: CHANGELOG + commit**

CHANGELOG `### Changed (the browser chrome is on unless you turn it off)`: quote the charter ("tabs need no Electron"), name the three escape hatches, and say that the running server serves the new default on the next reload without a restart. Commit subject: `feat(web): the browser chrome is on unless you turn it off`.

---

### Task 7: Live proof, board summary, memory

**Files:**
- Modify: `plans/thomas/WORKBOARD.md` (message), `plans/thomas/tasks/EVERY-USERS-THOMAS-P1-WEB-TAB-SHELL/PLAN.md` (status)

- [ ] **Step 1: Drive 8931 like the owner will**

Extend the scratchpad driver: open `/` (no query), open Beta and Gamma from the sidebar and Build from the mode switch (three tabs on different surfaces), type a draft in Beta, switch to Gamma and back, assert the draft; send a real short prompt in Beta, switch to Gamma within a second, read Beta's bubble length twice while hidden; assert computed visibility for every frame and the primary column; press Ctrl+2, Alt+3, Ctrl+Shift+]; switch the theme to Light and back; screenshot each tab in nebula and light into the scratchpad `shots/` folder. Then read every screenshot.

- [ ] **Step 2: Gates**

`python scripts/forge/gates/monolith_guard.py --staged-only` is run by commit.py; additionally run `python scripts/forge/gates/commit_growth_guard.py` over `HEAD~5..HEAD` (CI runs it), `ruff check` on every new .py, `node --check` on every .js, and `python -m pytest tests/test_a_click_that_lands_nowhere_is_never_silent.py tests/test_a_search_result_cannot_smuggle_a_script.py tests/test_the_browser_never_lowers_its_own_walls.py tests/test_architecture.py -q`.

- [ ] **Step 3: Board summary to `claude`**

`python scripts/crew/workboard/message.py --send --from-agent claude-browser --to-agent claude --kind coordination --task-id none --priority p1 --summary ... --requested-action ...` naming the five commits, the screenshots, what was proven in a real browser versus by CDP evidence, and that the owner sees tabs on the next reload of :8899 with no restart (static files are read from disk), with Classic layout as the opt-out.

- [ ] **Step 4: Memory**

Write a memory note (`web-tab-shell-live-2026-09-01.md`) with the design decision, the three markers the wiring depends on, and the verification traps met.

---

## Self-review

- Spec coverage: tab strip as the top frame at :8899 with zero Electron (Task 6 default-on; the chrome is plain web code); each tab hosts a Thomas surface (Chat/Build/Work documents in Task 3, Mission Control/Marketplace/Settings already workspace tabs); one live DOM per tab with show/hide only (Task 3, proven in Task 4); new-tab button and closable tabs (existing, pinned home in Task 3, proven in Task 4); Ctrl+Tab / Ctrl+1-9 (existing bindings kept, alternates and honesty in Task 5); built on the existing shell with the web path first-class in its detection (Task 6 `browserChromeDecision`); verification with computed-style assertions, dark and light, screenshots (Tasks 4 and 7).
- Placeholder scan: every code step carries its code; the only "read and adapt" instructions are the three DOM markers in Task 3 Step 1 and the two class/label names in Task 4, each with the file and line to read.
- Type consistency: `docs.open/hideAll/show/remove/reload/installOn/forwardSidebarToggle/list` match between Task 3's module and the shell edits; `keys.attachTo/bindings/handle` match between Task 5's module and Task 3's use; `browserChromeDecision` input keys match between Task 6's implementation and its harness.
