# Fork by Overlay Implementation Plan (Every User's Thomas, phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first Redesign-with-AI action creates the user's overlay: a directory the base never writes, holding a manifest of what the user overrides (tokens, themes, restyled elements, agent identity) that every page and every tab document applies at load, so stock Thomas updates slide underneath and the overlay rides on top untouched.

**Architecture:** One writer module (`thomas/server/overlay/manifest.py`) owns an append-only manifest in `THOMAS_OVERLAY_DIR` (default `<THOMAS_HOME>/overlay`), copied from the accepted-risks registry pattern (lock, temp+replace, loud on malformed, quiet on absent). The server renders the manifest into an inline stylesheet plus a JSON view and injects both, with one runtime script, into the HTML the page handlers already rewrite, so chat.html and settings.html stay untouched and every tab document gets the overlay at parse. Client modules that already load everywhere (`workspace_shell.js`, `chat_themes.js`, `ui_edit_layout.js`) read the view: overlay themes and token overrides are merged into the THEMES payload before chat.html captures it (the only way past the inline `#tc-shell` palette), element overrides layer under the per-browser layout book, and a BroadcastChannel fans a write out to every open document. Redesign's Apply records what it changed as manifest records through `POST /api/ui/overlay/records`; its Code brief stops pointing at stock files.

**Tech Stack:** Python 3.12 (stdlib json/os/re, aiohttp routes registered from `app_core.py`), classic-script JS, tokens.css design tokens, node vm harnesses, aiohttp test client, Playwright (python) for the live proof, commits via `scripts/crew/brief/commit.py`.

**Spec:** The owner's program prompt (2026-09-01) and board charter `msg-20260901223229-claude`; reader evidence in `docs/superpowers/plans/2026-09-02-fork-by-overlay-reads.md`; design synthesis from a read/design/judge workflow (winner: manifest-first, grafts from css-first and minimal-first; the judge's two corrections are applied below: `/mission` is served by `mission_support._serve_versioned_page`, not `index`, and `tests/test_deliverable_deep_links_reach_the_live_shell.py:50-51` parses the body of `index` for `web_dir / "x.html"` patterns).

## Global Constraints

- `chat.html` (2998 lines) and `settings.html` (1101) are never staged; `app_routes_init.py` (1471) and `thomas/core/config.py` (962) are over their limits and are not touched: routes register from `app_core.py` (734 lines) beside the realtime mount at lines 343-352; the overlay path resolves from env in a new module.
- Every new file under 300 lines in the commit that creates it; changed files under the 800 soft limit; `settings.script01.js` sits at exactly 800, so its edit is net-zero.
- Commit ONLY via `python scripts/crew/brief/commit.py --agent claude-browser --include <paths> --message $m` from PowerShell with the message read from a file, no double quotes in messages, `Thomas-Agent: claude` trailer, a CHANGELOG entry per commit; the wrapper auto-includes a dirty CHANGELOG.md, so commit only when the cleanup lane has left it clean.
- Python changes are dormant on any running server until it restarts; static web files are live from disk. Never restart or verify against :8899; use a second port with `THOMAS_OVERLAY_DIR` pointed at a scratch directory.
- Pinned tests that must stay green unchanged: `tests/test_workspace_shell.py:20` (the literal five-theme array at `workspace_shell.js:4`), `tests/test_design_tokens_single_source.py:40` (`/css/tokens.css` located by `chat_themes.js`), `tests/test_ui_edit_mode_contract.py:43-46` (the localStorage literals in `ui_edit_layout.js`), `tests/test_ui_redesign_client_contract.py`, `tests/test_deliverable_deep_links_reach_the_live_shell.py:47-54`, `tests/test_the_settings_page_does_not_recurse_on_a_theme_change.py`.
- Decisions taken for phase 2 (owner may overrule on the board): identity covers exactly five surfaces (document title, brand mark, composer placeholder, assistant message header, welcome copy); one overlay per data dir / `THOMAS_PROFILE` (single-user); the Work dashboard spec channel stays out of the overlay; `asset:` addresses are reserved in the schema but asset upload and serving land in phase 3 with export; the runtime hook (view JSON + runtime script) is injected into every page even with no overlay, so the first write fans out to already-open tabs; the dead `/mission` registration in `app_routes_init.py:1286` is reported, not touched.

---

## File Structure

| File | Responsibility | Status |
| --- | --- | --- |
| `thomas/server/overlay/__init__.py` | Package marker, exports `overlay_dir`, `load`, `append`. | create (~10) |
| `thomas/server/overlay/paths.py` | `overlay_dir()` / `manifest_path()` from env; never creates anything. | create (~40) |
| `thomas/server/overlay/style_whitelist.py` | The one style-property whitelist and value guard, mirrored by `ui_edit_layout.js` STYLE_PROPS. | create (~45) |
| `thomas/server/overlay/stock_tokens.py` | Parse tokens.css into `{theme: {key: value}}`; `is_stock_key`. | create (~90) |
| `thomas/server/overlay/records.py` | Address grammar per kind, `validate_record` (write) and `validate_loaded`/`validate_header` (full validation on load), bounds, the base stamp. | create (~175) |
| `thomas/server/overlay/store.py` | The disk transaction: lock beside the directory, hard limits, boundary guard, atomic write with birth inside it; a refused write leaves no trace. | create (~110) |
| `thomas/server/overlay/manifest.py` | Schema, `load` (honesty contract, full validation), `resolve`, `append` with the strict overlay-id precondition. | create (~190) |
| `thomas/server/overlay/render.py` | `current_view()` (mtime cache), `render_css`, `render_view`, `inject`, `invalidate`. | create (~230) |
| `thomas/server/overlay/cli.py` | `python -m thomas.server.overlay path|list|show|check`. | create (~90) |
| `thomas/server/overlay/__main__.py` | Runs `cli.main`. | create (~5) |
| `docs/OVERLAY.md` | The boundary rules, schema, apply path, phase 3/4 expectations. | create (~120) |
| `thomas/server/routes/ui_overlay_routes.py` | `setup_overlay_routes(app, require_api_access)`: GET view, GET manifest, POST records. | create (~200) |
| `thomas/server/app_core.py` | Register overlay routes beside the realtime block. | modify (+9) |
| `thomas/server/app_middleware_helpers.py` | One `inject_overlay(html, stamp)` call per page handler. | modify (+6) |
| `thomas/server/routes/mission_support.py` | Same call in `_serve_versioned_page`. | modify (+4) |
| `thomas/server/routes/ui_redesign_runtime.py` | Import the shared whitelist; theme channel in the plan; Code brief rewrite. | modify (~+60/-15) |
| `thomas/server/routes/work_dashboard_runtime.py` | Pass the active theme; `code_thread` null when only the overlay changed. | modify (+15) |
| `thomas/server/web/js/overlay_runtime.js` | Identity swap, shell repaint, `adopt(view)`, `record(action, records)`, `window.ThomasOverlay`. | create (~250) |
| `thomas/server/web/js/workspace_shell.js` | Read the view; known themes; light check; default theme; `thomas:overlay:changed` relay; late fetch. | modify (+35) |
| `thomas/server/web/js/chat_themes.js` | `mergeOverlay(view)` after derivation; widened regex. | modify (+45) |
| `thomas/server/web/js/ui_edit_layout.js` | `currentMap()` layers overlay elements under local; BroadcastChannel; `refreshOverlay`, `overlaidKeys`. | modify (+45) |
| `thomas/server/web/settings.script01.js` | `normalizeChatTheme` defers to the shell's `safeTheme` (net zero). | modify (0) |
| `thomas/server/web/js/ui_redesign_target.js` | Descriptor carries `policy`; protected targets refused at pick. | modify (+10) |
| `thomas/server/web/js/ui_redesign_select.js` | Build records after Apply, call `ThomasOverlay.record`, honest result lines, prune local keys. | modify (+65) |
| `tests/test_overlay_manifest.py`, `tests/test_overlay_render.py`, `tests/test_overlay_routes.py`, `tests/test_overlay_injection_contract.py`, `tests/test_overlay_client_contract.py`, `tests/web_node/overlay_client.mjs`, `tests/test_the_first_redesign_creates_the_overlay.py` | Sentence-named fixtures-only tests per task. | create |

---

### Task 1: The overlay package (C1)

**Files:**
- Create: `thomas/server/overlay/__init__.py`, `thomas/server/overlay/paths.py`, `thomas/server/overlay/style_whitelist.py`, `thomas/server/overlay/stock_tokens.py`, `thomas/server/overlay/manifest.py`, `thomas/server/overlay/render.py`, `thomas/server/overlay/cli.py`, `thomas/server/overlay/__main__.py`, `docs/OVERLAY.md`
- Modify: `thomas/server/routes/ui_redesign_runtime.py:44-55` (import the whitelist)
- Test: `tests/test_overlay_manifest.py`, `tests/test_overlay_render.py`
- Modify: `CHANGELOG.md`

**Interfaces (produced):**
- `thomas.server.overlay.paths.overlay_dir() -> Path`, `manifest_path() -> Path`.
- `thomas.server.overlay.style_whitelist.STYLE_PROPS: frozenset[str]` (the camelCase keys of `ui_edit_layout.js` STYLE_PROPS), `clean_style(style: dict) -> dict`, `value_ok(value: str) -> bool` (<=160 chars, no `url(`, `expression(`, `@import`, none of `;{}<>`).
- `thomas.server.overlay.stock_tokens.parse(css_text: str) -> dict[str, dict[str, str]]` with keys `nebula` (from `:root`) plus `dark|light|aurora|sandstone`; `load_stock() -> dict` reads `thomas/server/web/css/tokens.css`; `STOCK_THEMES = ("nebula", "dark", "light", "aurora", "sandstone")`.
- `thomas.server.overlay.manifest`: `SCHEMA = 1`; `class ManifestBroken(RuntimeError)` (message names the file); `class OverlayMismatch(RuntimeError)`; `@dataclass(frozen=True) class Manifest: path, header: dict, records: tuple[dict, ...]; rev -> int; overlay_id -> str`; `load(path=None) -> Manifest | None` (None when absent, one INFO log; raises ManifestBroken when present but unparseable, wrong shape, or a record missing a required key); `resolve(records) -> dict[str, dict]` newest-wins per address, `op: clear` removes; `validate_record(rec: dict, stock: dict) -> list[str]` (empty = valid); `append(records, action, base, *, expected_overlay_id=None, path=None, stock=None) -> AppendResult(created, rev, overlay_id, accepted, rejected)`; `birth_base(web_build="") -> dict` (thomas version, short git sha or None, web build, tokens sha1).
- Address grammar: `token:<theme>:<--key>`, `theme:<name>`, `element:<workspace>:<breakpoint>:<ui_id>`, `identity:<field>`, `setting:default_theme`, `asset:<relpath>` (reserved; rejected in phase 2 with reason `assets land in phase 3`).
- `thomas.server.overlay.render`: `current_view(path=None) -> dict` (mtime-keyed cache, 2 s), `invalidate()`, `render_css(view) -> str`, `render_view(view) -> str` (JSON with `</` escaped as `<\/` and U+2028/2029 escaped), `inject(html, stamp_token, view=None) -> str` (inserts before the first `</head>`; no `</head>` means unchanged).
- View shape: `{present: bool, overlay_id, rev, path, themes: {name: {label, tagline, derives_from, color_scheme, swatches, world, meta}}, tokens: {theme: {key: value}}, elements: {workspace: {breakpoint: {ui_id: entry}}}, identity: {field: value}, default_theme: str | None, overrides: [address...], notes: [str...]}`.

- [ ] **Step 1: Write the failing manifest tests**

`tests/test_overlay_manifest.py`:

```python
"""An overlay is a directory the base never writes and a manifest that is loud when broken.

The manifest copies the accepted-risks registry contract (scripts/forge/accepted_risks.py):
a MISSING manifest is stock Thomas and says so once; a manifest that EXISTS but is
malformed is broken, not empty, and never falls back. Records are append-only under a
lock; resolve is newest-wins per address and `clear` retracts.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from thomas.server.overlay import manifest as m
from thomas.server.overlay import stock_tokens

STOCK = {"nebula": {"--c-accent": "#8b8cff", "--c-bg": "#070912"}, "dark": {"--c-accent": "#6e9bff"},
         "light": {}, "aurora": {}, "sandstone": {}}
BASE = {"thomas_version": "0.19.27", "git": "abc1234", "web_build": "0123456789ab", "tokens_sha1": "f" * 40}
ACTION = {"actor": "redesign", "instruction": "make the sidebar darker", "targets": ["chat.sidebar"]}


def element(address="element:chat:desktop:chat.sidebar", **value):
    return {"op": "set", "kind": "element", "address": address,
            "value": value or {"x": 0, "y": 0, "style": {"backgroundColor": "#101a2e"}},
            "anchor": {"exact": True, "fragile": False, "component": "aside", "label": "Chat sidebar", "policy": "move resize", "path": ""}}


def test_a_missing_manifest_is_stock_thomas_not_an_error(tmp_path: Path) -> None:
    assert m.load(tmp_path / "overlay" / "manifest.json") is None


def test_a_broken_manifest_names_its_file_and_never_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(m.ManifestBroken) as info:
        m.load(path)
    assert "manifest.json" in str(info.value)
    path.write_text(json.dumps({"version": 1, "overlay": {"id": "ovl_x"}, "records": [{"id": "r0001"}]}), encoding="utf-8")
    with pytest.raises(m.ManifestBroken):
        m.load(path)


def test_the_first_append_gives_birth_and_writes_nothing_outside_the_overlay_dir(tmp_path: Path) -> None:
    path = tmp_path / "home" / "overlay" / "manifest.json"
    result = m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert result.created is True and result.rev == 1 and result.overlay_id.startswith("ovl_")
    loaded = m.load(path)
    assert loaded is not None and loaded.rev == 1 and loaded.header["created_from"] == BASE
    assert sorted(p.name for p in path.parent.iterdir()) == [".gitattributes", ".gitignore", "README.md", "manifest.json"]
    assert sorted(p.name for p in (tmp_path / "home").iterdir()) == ["overlay"]


def test_resolve_is_newest_wins_and_clear_retracts(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element(style={"backgroundColor": "#111"})], ACTION, BASE, path=path, stock=STOCK)
    m.append([element(style={"backgroundColor": "#222"})], ACTION, BASE, path=path, stock=STOCK)
    live = m.resolve(m.load(path).records)
    assert live["element:chat:desktop:chat.sidebar"]["value"]["style"]["backgroundColor"] == "#222"
    m.append([{"op": "clear", "kind": "element", "address": "element:chat:desktop:chat.sidebar"}], ACTION, BASE, path=path, stock=STOCK)
    assert "element:chat:desktop:chat.sidebar" not in m.resolve(m.load(path).records)
    assert m.load(path).rev == 3


def test_a_token_record_carries_the_stock_value_it_overrides(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([{"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"}], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["token:nebula:--c-accent"]
    rec = m.load(path).records[0]
    assert rec["stock_value"] == "#8b8cff" and rec["base"] == BASE and rec["by"]["actor"] == "redesign"


def test_records_that_lie_about_their_shape_are_rejected_with_a_reason(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    bad = [
        {"op": "set", "kind": "token", "address": "token:nebula:--c-nope", "value": "#000"},
        {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "url(x)"},
        {"op": "set", "kind": "theme", "address": "theme:nebula", "value": {"label": "x", "derives_from": "nebula", "color_scheme": "dark"}},
        {"op": "set", "kind": "element", "address": "element:chat:desktop:chat.shell", "value": {"style": {"backgroundColor": "#000"}},
         "anchor": {"exact": True, "fragile": False, "policy": "root protected"}},
        {"op": "set", "kind": "asset", "address": "asset:fonts/x.woff2", "value": {}},
        {"op": "set", "kind": "identity", "address": "identity:name", "value": "<script>"},
    ]
    result = m.append(bad, ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["identity:name"]  # escaped at render, allowed as text
    reasons = {r["address"]: r["reason"] for r in result.rejected}
    assert "not a stock token" in reasons["token:nebula:--c-nope"]
    assert "value" in reasons["token:nebula:--c-accent"]
    assert "stock" in reasons["theme:nebula"]
    assert "protected" in reasons["element:chat:desktop:chat.shell"]
    assert "phase 3" in reasons["asset:fonts/x.woff2"]


def test_a_foreign_overlay_id_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    first = m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    with pytest.raises(m.OverlayMismatch):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id="ovl_000000000000")
    assert m.load(path).overlay_id == first.overlay_id


def test_two_writers_both_land_and_the_file_is_never_half_written(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)

    def writer(n: int) -> None:
        m.append([element(address=f"element:chat:desktop:row{n}", x=n)], ACTION, BASE, path=path, stock=STOCK)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    loaded = m.load(path)
    assert loaded.rev == 9
    assert not list(path.parent.glob("manifest.json.lock"))


def test_stock_tokens_parse_the_root_and_every_theme_block() -> None:
    stock = stock_tokens.load_stock()
    assert set(stock) == set(stock_tokens.STOCK_THEMES)
    assert stock["nebula"]["--c-accent"].startswith("#")
    assert stock_tokens.is_stock_key("--c-accent", stock) and not stock_tokens.is_stock_key("--c-nope", stock)
```

- [ ] **Step 2: Run to see it fail**

Run: `python -m pytest tests/test_overlay_manifest.py -q`. Expected: ImportError (`thomas.server.overlay` does not exist).

- [ ] **Step 3: Write the package**

`thomas/server/overlay/paths.py`:

```python
"""Where a user's overlay lives. This module never creates anything.

THOMAS_OVERLAY_DIR wins; otherwise <THOMAS_HOME>/overlay, where THOMAS_HOME is
the profile-suffixed data dir the config layer exports at boot
(thomas/core/config.py apply_runtime_data_env_defaults). The base reads this
directory at request time and writes it only through thomas.server.overlay.manifest on
an explicit user action; nothing at startup, page serving, fingerprinting,
plugin install or update may create it. docs/OVERLAY.md is the contract.
"""

from __future__ import annotations

import os
from pathlib import Path


def overlay_dir() -> Path:
    raw = str(os.environ.get("THOMAS_OVERLAY_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    home = str(os.environ.get("THOMAS_HOME") or os.environ.get("THOMAS_DATA_DIR") or "").strip()
    if home:
        return Path(home).expanduser() / "overlay"
    from thomas.core.config import resolve_thomas_data_dir  # heavy import, CLI use only

    return Path(resolve_thomas_data_dir()) / "overlay"


def manifest_path() -> Path:
    return overlay_dir() / "manifest.json"
```

(Check the signature of `resolve_thomas_data_dir` at `thomas/core/config.py:167` before relying on the no-argument call; pass `os.environ` if it takes an env map.)

`thomas/server/overlay/style_whitelist.py`:

```python
"""The one list of style properties an overlay may set, and the value guard.

Mirrors STYLE_PROPS in thomas/server/web/js/ui_edit_layout.js; the client
contract test asserts the two sets are equal. ui_redesign_runtime.py imports
this instead of carrying its own copy.
"""

from __future__ import annotations

import re

STYLE_PROPS: frozenset[str] = frozenset({
    # copy the EXACT list from ui_edit_layout.js STYLE_PROPS before landing
})

_FORBIDDEN = re.compile(r"url\(|expression\(|@import|[;{}<>]", re.IGNORECASE)


def value_ok(value: object) -> bool:
    text = str(value if value is not None else "").strip()
    return 0 < len(text) <= 160 and not _FORBIDDEN.search(text)


def clean_style(style: object) -> dict[str, str]:
    if not isinstance(style, dict):
        return {}
    return {k: str(v).strip() for k, v in style.items() if k in STYLE_PROPS and value_ok(v)}
```

Before writing this file, copy the EXACT property list from `ui_edit_layout.js` STYLE_PROPS (the client contract test in Task 3 compares the two sets).

`thomas/server/overlay/stock_tokens.py`:

```python
"""Read the stock design tokens out of tokens.css so overrides can name what they override."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

TOKENS_CSS = Path(__file__).resolve().parents[1] / "server" / "web" / "css" / "tokens.css"
STOCK_THEMES = ("nebula", "dark", "light", "aurora", "sandstone")
_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
_BLOCK = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}", re.DOTALL)


def parse(css_text: str) -> dict[str, dict[str, str]]:
    themes: dict[str, dict[str, str]] = {name: {} for name in STOCK_THEMES}
    for match in _BLOCK.finditer(css_text):
        selector = " ".join(match.group("selector").split())
        body = match.group("body")
        target = None
        if selector == ":root" and not themes["nebula"]:
            target = "nebula"
        else:
            named = re.search(r'data-thomas-theme="([a-z]+)"', selector)
            if named and named.group(1) in themes:
                target = named.group(1)
        if target is None:
            continue
        for key, value in _DECL.findall(body):
            themes[target].setdefault(key, " ".join(value.split()))
    return themes


def load_stock(path: Path = TOKENS_CSS) -> dict[str, dict[str, str]]:
    return parse(path.read_text(encoding="utf-8"))


def tokens_sha1(path: Path = TOKENS_CSS) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def is_stock_key(key: str, stock: dict[str, dict[str, str]]) -> bool:
    return key in stock.get("nebula", {})
```

`thomas/server/overlay/manifest.py` (the writer; ~290 lines): module docstring stating the envelope (`{"version": 1, "overlay": {...}, "records": [...]}`, the same as `docs/ops/accepted_risks.json`), the honesty contract, and append-only semantics. Contents:

```python
SCHEMA = 1
REQUIRED_KEYS = ("id", "at", "op", "kind", "address", "by", "base")
KINDS = ("token", "theme", "element", "identity", "setting", "asset")
IDENTITY_FIELDS = ("name", "tagline", "welcome.title", "welcome.sub", "placeholder", "title", "mark")
THEME_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ELEMENT_ADDRESS = re.compile(r"^element:([a-z0-9_-]+):(desktop|tablet|mobile):(.+)$")
TOKEN_ADDRESS = re.compile(r"^token:([a-z0-9-]+|\*):(--[a-z0-9-]+)$")
_LOCK_MAX_RETRIES, _LOCK_RETRY_INTERVAL, _LOCK_STALE_SECONDS = 20, 0.25, 30.0


class ManifestBroken(RuntimeError): ...
class OverlayMismatch(RuntimeError): ...

@dataclass(frozen=True)
class Manifest:
    path: Path
    header: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    rev -> len(records); overlay_id -> header["id"]

@dataclass
class AppendResult: created, rev, overlay_id, accepted: list[str], rejected: list[dict[str, str]]

def load(path=None) -> Manifest | None:
    # missing -> log.info + None; unreadable JSON / wrong version / bad header / record missing a key -> ManifestBroken naming the path

def resolve(records) -> dict[str, dict]:
    # iterate in order; op clear pops the address; otherwise the record replaces the address

def validate_record(rec, stock) -> list[str]:
    # op in {set, clear}; kind in KINDS and address starts with "<kind>:"; clear needs nothing else
    # token: TOKEN_ADDRESS, key on stock nebula (:root), value_ok
    # theme: THEME_NAME, not a stock name, value dict with derives_from in STOCK_THEMES and color_scheme in {dark, light}
    # element: ELEMENT_ADDRESS; anchor.policy containing the word protected or no-edit -> "this region is protected"; value dict; a style with no whitelisted property -> error
    # identity: field in IDENTITY_FIELDS; value str 1-80 chars
    # setting: address == setting:default_theme, value str
    # asset: "assets land in phase 3 with export"

def birth_base(web_build="") -> dict:  # thomas.__version__, git short sha via subprocess (None on failure), web_build or None, tokens_sha1()

@contextmanager
def _locked(lock_path):  # O_CREAT|O_EXCL, bounded retries, stale break after _LOCK_STALE_SECONDS, RuntimeError naming the lock when exhausted, unlink in finally

def _atomic_write(path, payload):  # temp in the same dir (pid-suffixed) then os.replace; indent=1, ensure_ascii=False, LF newlines

def _birth_files(directory):  # mkdir parents; README.md, .gitattributes ("manifest.json diff=json"), .gitignore ("manifest.json.lock", "*.tmp"); never overwrite

def _stock_value(address, stock):  # token records only: the stock value for that theme, falling back to nebula; else None

def append(records, action, base, *, expected_overlay_id=None, path=None, stock=None) -> AppendResult:
    # validate every record first (accepted / rejected with joined reasons); _birth_files; under the lock: load()
    # (ManifestBroken propagates: writes refuse while broken); created when absent -> header {id: ovl_<12hex>, schema, created_at, created_from: base};
    # expected_overlay_id mismatch -> OverlayMismatch; stamp id r%04d, at, op, kind, address, by {actor, action act_<stamp>_<4hex>, instruction[:2000], targets}, base;
    # for set: value (element styles cleaned), stock_value, anchor; write when accepted or created; log.info on birth
```

`thomas/server/overlay/render.py` (~230 lines): `empty_view(path, notes)`, `build_view(loaded)` (resolve, then group by kind into the view shape; `overrides` in resolve order), `current_view(path=None)` (mtime-keyed cache, 2 s, `ManifestBroken` becomes `notes`), `invalidate()`, `render_css(view)`:

- nebula (or `*`) tokens under `:root{}`; other stock themes under `html[data-thomas-theme="x"], html[data-theme="x"]{}` (the exact tokens.css selector grammar so later source order wins over tokens.css and the literal re-declarations in settings.style01.css / mission.style01.css);
- each overlay theme as a full block: stock nebula, then stock `derives_from`, then token records of `derives_from`, then the theme's own token records, plus `color-scheme`;
- any value failing `value_ok` at render time is skipped and named in `view["notes"]`.

`render_view(view)` is `json.dumps(..., ensure_ascii=False)` with `</` replaced by `<\/` and U+2028/2029 escaped. `inject(html, stamp_token, view=None)` inserts, before the first `</head>`: `<style id="thomas-overlay-css">` only when CSS is non-empty; `<script id="thomas-overlay-view" type="application/json">` always; `<script src="/static/js/overlay_runtime.js?v=<stamp_token>" defer>` always (the stamp token is the placeholder the calling handler rewrites next). Identity values reach the page only through the JSON view and are inserted by the runtime with `textContent`, never `innerHTML`.

`thomas/server/overlay/cli.py`: `path` (prints `overlay_dir()`), `list` (resolved addresses grouped by kind, `--json`), `show <address>`, `check` (exit 2 when a fragile element anchor exists, a token key is no longer on stock `:root`, or the manifest is broken; exit 0 otherwise, printing one line per problem). `__main__.py` calls `cli.main()`.

`ui_redesign_runtime.py:44-55`: delete the private `_STYLE_PROPS` and `_clean_style`, import `clean_style` from `thomas.server.overlay.style_whitelist` and use it where `_clean_style` was called (read lines 84-104 first).

- [ ] **Step 4: Write the render tests**

`tests/test_overlay_render.py`: an absent manifest renders no style block, a view with `present: false`, and the runtime script tag; a manifest with a nebula token renders `:root{--c-accent:#2ecc71;}`; a dark token renders under `html[data-thomas-theme="dark"], html[data-theme="dark"]`; an overlay theme `ember` derived from nebula renders a full block containing every stock nebula key plus its overrides and `color-scheme:dark`; a hand-built view value containing `}` never reaches the CSS and lands in `notes`; an identity value `</script><b>x` is escaped in the view script and the resulting HTML still has exactly one `</head>`; `inject` on HTML without `</head>` returns it unchanged; `inject` leaves the `__THOMAS_WEB_BUILD__` placeholder in the script tag when that is the stamp token.

- [ ] **Step 5: Run, ruff, docs, commit**

Run: `python -m pytest tests/test_overlay_manifest.py tests/test_overlay_render.py tests/test_ui_redesign_runtime.py -q` and `ruff check thomas/server/overlay tests/test_overlay_manifest.py tests/test_overlay_render.py thomas/server/routes/ui_redesign_runtime.py`. Write `docs/OVERLAY.md` (boundary rules, schema and example, the apply path summary, what phases 3 and 4 will rely on). CHANGELOG `### Added (a user overlay has a home the base never writes)`. Commit subject `feat(overlay): the manifest, its boundary and its renderer`.

---

### Task 2: Routes and injection (C2)

**Files:**
- Create: `thomas/server/routes/ui_overlay_routes.py`
- Modify: `thomas/server/app_core.py:352` (after the realtime block), `thomas/server/app_middleware_helpers.py` (index, classic, settings, companion), `thomas/server/routes/mission_support.py:623-633`
- Test: `tests/test_overlay_routes.py`, `tests/test_overlay_injection_contract.py`
- Modify: `CHANGELOG.md`

**Interfaces (produced):**
- `GET /api/ui/overlay` -> `{ok: true, view, css}`; `GET /api/ui/overlay/manifest` -> the raw manifest or `{present: false}`; `POST /api/ui/overlay/records` with `{overlay_id: str|null, action: {actor, instruction, targets}, records: [...]}` -> `200 {ok, created, rev, overlay_id, view, css, accepted, rejected}`, `409 {ok: false, error}` on a foreign id, `500 {ok: false, error}` naming the file when the manifest is broken, `503` when the lock cannot be taken, `400` on a malformed body. All three behind the same `require_api_access` that guards `/api/ui/redesign`.
- `inject_overlay(html: str, stamp_token: str) -> str` in `thomas/server/app_middleware_helpers.py` wrapping `thomas.server.overlay.render.inject` in a try/except that logs and returns the HTML untouched on `OSError`/`ValueError`/`RuntimeError` (a broken overlay must never take a page down).

- [ ] **Step 1: Failing route tests**

`tests/test_overlay_routes.py` with `aiohttp.test_utils.TestClient` against a minimal `web.Application()` with `setup_overlay_routes(app, require_api_access=lambda request: None)` and `THOMAS_OVERLAY_DIR` monkeypatched to `tmp_path / "overlay"`: GET view on an absent overlay is `present: false` and the directory still does not exist afterwards; POST one element record creates the overlay (rev 1) and the birth files; a second POST with a foreign `overlay_id` is 409 and the manifest is unchanged; a POST with a protected element returns 200 with it in `rejected`; corrupting `manifest.json` by hand makes GET view carry a note and POST return 500 naming the file, bytes unchanged.

`tests/test_overlay_injection_contract.py`: build the page handlers via `build_page_handlers` (read its signature at `app_middleware_helpers.py:18-21`) with a fake `web_dir` holding minimal `chat.html`, `index.html`, `settings.html`, `companion.html` each with `<head></head>`; with `THOMAS_OVERLAY_DIR` absent every response contains `id="thomas-overlay-view"` and `overlay_runtime.js` before `</head>` and no `thomas-overlay-css`; with a manifest present the style block appears; the overlay directory is still absent after all four requests; `mission_support._serve_versioned_page` on a temp file behaves the same; the source of `index` still contains exactly one distinct `web_dir / "x.html"` name (the deep-links test's rule).

- [ ] **Step 2: Implement**

`ui_overlay_routes.py`: three handlers as in the interface; `records` validates the body shape (400), computes `base = m.birth_base(web_build=...)`, calls `m.append(..., expected_overlay_id=body.get("overlay_id") or None)`, maps `OverlayMismatch` to 409, `ManifestBroken` to 500, the lock `RuntimeError` to 503, then `render.invalidate()` and returns the fresh view and css. Registration:

```python
    # The user overlay: a directory the base never writes, read at request time.
    _overlay_ok = False
    try:
        from thomas.server.routes.ui_overlay_routes import setup_overlay_routes

        setup_overlay_routes(app, require_api_access=_require_api_access)
        _overlay_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
        log.warning("Overlay routes unavailable: %s", e)
    _diagnostics["overlay"] = _overlay_ok
```

`app_middleware_helpers.py`: add `inject_overlay` at module level; in each of the four handlers, immediately BEFORE `html = html.replace("__THOMAS_WEB_BUILD__", web_build)`: `html = inject_overlay(html, "__THOMAS_WEB_BUILD__")`. In `mission_support._serve_versioned_page`, before the `__THOMAS_VERSION__` replace: `html = inject_overlay(html, "__THOMAS_VERSION__")`. Confirm `log` exists in `app_middleware_helpers.py`; add `logging.getLogger(__name__)` if not.

- [ ] **Step 3: Run, ruff, commit**

Run: `python -m pytest tests/test_overlay_routes.py tests/test_overlay_injection_contract.py tests/test_deliverable_deep_links_reach_the_live_shell.py -q`; `ruff check` on the touched Python. Boot check on a spare port with `THOMAS_OVERLAY_DIR=<scratch>/overlay`: `/` contains the view script, the scratch directory does not exist, `/api/ui/overlay` is `present: false`; stop it. CHANGELOG `### Added (every page carries the overlay, and the overlay has an API)`. Commit subject `feat(overlay): every served page carries the user overlay, and records land through one route`. Say in the body that a running server serves the injection only after a restart.

---

### Task 3: The clients read the overlay (C3)

**Files:**
- Create: `thomas/server/web/js/overlay_runtime.js`, `tests/web_node/overlay_client.mjs`, `tests/test_overlay_client_contract.py`
- Modify: `thomas/server/web/js/workspace_shell.js`, `thomas/server/web/js/chat_themes.js`, `thomas/server/web/js/ui_edit_layout.js` (currentMap), `thomas/server/web/settings.script01.js:76-88` (net zero)
- Modify: `CHANGELOG.md`

**Interfaces (produced):**
- `window.ThomasOverlay = { view, adopt(view, css), record(action, records) -> Promise<{ok, rev, view, ...} | {ok:false, unavailable:true, error}>, applyIdentity(view) }` from `overlay_runtime.js`; the view is read once at parse from `#thomas-overlay-view` by `workspace_shell.js` into `window.ThomasOverlayView` so scripts that load before the deferred runtime can use it.
- `window.ThomasWorkspaceShell` gains `knownThemes() -> string[]` (the literal five plus overlay theme names in manifest order) and `overlayView()`; `safeTheme` uses `knownThemes`; the light-theme check consults `view.themes[name].color_scheme`; `storedTheme()` falls back to `view.default_theme`; the message listener relays `{type: 'thomas:overlay:changed', rev}` to frames like the theme message; when no view script exists, `init()` fetches `/api/ui/overlay` late.
- `window.ThomasChatThemes.mergeOverlay(view)` runs after `deriveThemeVarsFromTokens()`: for each overlay theme appends `THEMES[name] = {name: label, tagline, sw: swatches, vars: derived}` and `THEME_META[name]` (copied from `derives_from`, patched by `meta`), in manifest order; token records on stock themes patch `THEMES[t].vars[key]` and map the five meta tokens (`--font-head`, `--font-label`, `--r-card`, `--r-composer`, `--c-menu-bg`) onto `THEME_META[t]`; when `identity.name` is set, replaces the whole word `Thomas` in every `THEME_META[*].welcome` string. The theme-name regex widens to `[a-z0-9-]+`.
- `window.ThomasUiLayout` gains `overlaidKeys() -> string[]` and `refreshOverlay(view)`; `currentMap()` returns `Object.assign({}, overlayMap, localMap)` where `overlayMap = view.elements[workspace()][currentPoint()] || {}`; a `BroadcastChannel('thomas-overlay')` listener on `{type: 'changed', rev}` fetches `/api/ui/overlay`, calls `refreshOverlay`, then `applyAll()`. `KEY`, `read`, `write` are untouched.
- `overlay_runtime.js` on load: identity swap on the five surfaces (whole-node text matches only; `textContent`), one-time shell repaint of `--font-sans/--font-serif/--font-mono` from token records (chat.html sets them inline and `applyTheme` never rewrites them); `adopt(view, css)`: replace the style block text, `mergeOverlay`, repaint `#tc-shell` inline vars and meta for the current theme (a documented mirror of chat.html's applyTheme, which is a closure), `ThomasWorkspaceShell.applyTheme(current, {vars, persist:false})`, identity, `refreshOverlay` + `applyAll`; `record(action, records)`: POST with the view's `overlay_id`, 404 -> `{ok:false, unavailable:true}`, on `ok` adopt and post `{type:'changed', rev}` on the channel.

- [ ] **Step 1: Failing contract tests**

`tests/web_node/overlay_client.mjs` loads `chat_themes.js` in a vm context with a fake `document` whose `styleSheets` expose a stub tokens.css (read the function at chat_themes.js first and copy the shape it reads), calls `mergeOverlay` with a view containing `theme:ember` derived from nebula plus `token:nebula:--c-accent = #2ecc71` and `identity.name = Otto`, and reports: `Object.keys(THEMES)` order ends with `ember`; `THEMES.nebula.vars['--c-accent'] === '#2ecc71'`; `THEMES.ember.vars['--c-bg']` equals nebula's; `THEME_META.ember.rCard` equals nebula's; every `THEME_META[*].welcome` string contains `Otto` and not the word `Thomas`. Then loads `ui_edit_layout.js` with `localStorage` and `document` stubs, seeds a local map and an overlay map with one shared key, and reports that `currentMap()` prefers the local value and includes the overlay-only key, and that `overlaidKeys()` lists the overlay keys.

`tests/test_overlay_client_contract.py` drives the harness and adds source pins: `set(STYLE_PROPS in ui_edit_layout.js) == thomas.server.overlay.style_whitelist.STYLE_PROPS`; `workspace_shell.js` line 4 literal unchanged; `chat_themes.js` still locates `/css/tokens.css`; `BroadcastChannel("thomas-overlay")` appears in `ui_edit_layout.js` and `overlay_runtime.js`; `overlay_runtime.js` never uses `innerHTML`; no Python file outside `thomas/server/overlay/`, `thomas/server/routes/ui_overlay_routes.py` and the `inject_overlay` helper builds an overlay path.

- [ ] **Step 2: Implement** per the interfaces; read `chat.html` around the brand mark, the welcome sub, the composer placeholder and the assistant header before finalising the identity selectors; read `ui_edit_layout.js` `currentMap`/`start` and `chat_themes.js` `deriveThemeVarsFromTokens` before editing; `settings.script01.js` `normalizeChatTheme` defers to `window.ThomasWorkspaceShell.safeTheme` when present in the same line count, and overlay `<option>`s are appended to the theme select at load without growing the file.

- [ ] **Step 3: Verify live before the server half exists**

Static files are live: on a second port (no injection until that server restarts with C2), load `/` and confirm no console error and the theme switcher still works (`mergeOverlay` with `present:false` is a no-op). Then extend the fixture (`tests/web_fixtures/thomas_chat_fixture.py`) to inject a hand-written `#thomas-overlay-view` script, the style block and the runtime into chat.html and settings.html, and assert in headless Chromium: the shell's computed `--c-accent` equals the overlay token on `/` AND on `/settings?embed=1` on `documentElement`; the brand span reads the new name; `theme:ember` appears in the theme menu and selecting it sets `#tc-shell.dataset.theme === 'ember'` in a second tab document via the existing relay.

- [ ] **Step 4: Run, commit**

Run the harness test, the pinned suites listed in Global Constraints, and `tests/test_a_conversation_exists_once_across_tabs.py` (theme relay). CHANGELOG `### Added (every document reads the user overlay)`. Commit subject `feat(web): every document applies the user overlay before it paints`.

---

### Task 4: Redesign writes the overlay (C4)

**Files:**
- Modify: `thomas/server/web/js/ui_redesign_target.js` (describe adds `policy`; pick refuses protected), `thomas/server/web/js/ui_redesign_select.js` (records after Apply; result lines; prune), `thomas/server/routes/ui_redesign_runtime.py` (theme channel, schema hint, brief), `thomas/server/routes/work_dashboard_runtime.py:420-477` (active theme, `code_thread` null when only the overlay changed)
- Test: `tests/test_ui_redesign_runtime.py` (+theme channel cases), `tests/test_ui_redesign_client_contract.py` (+record-call pin)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Request to `/api/ui/redesign` gains `theme: <shell.dataset.theme>`; response gains `theme: {tokens: {key: value}, identity: {field: value}, label}` (validated by `_plan_theme` against the stock `:root` keys and the shared guard; unchanged values dropped) and `overlay_only: bool`.
- Client: after `applyLayout` counts real changes, build `records` (one `element` record per changed entry with `anchor` from the descriptor, `token`/`identity` records from `plan.theme`) and call `ThomasOverlay.record({actor: 'redesign', instruction, targets}, records)`. On `ok`: remove overlaid keys from the local `saved` map (keep versions), show `Saved to your overlay (rev N) - applies on every tab and every reload` with the path from `view.path`; on `unavailable`: `Kept in this browser only - this server predates the overlay endpoint; restart it and Apply again`, and token/identity changes are not applied locally; on a rejected address: roll back that local entry and show the reason.
- `code_thread_prompt` says the change is recorded in the overlay at `<path>` (records under `act_...`), applies everywhere, and that nothing under `thomas/server/web/` needs editing; the stock-file sentence is removed; `code_thread` is null when only the overlay changed.

- [ ] **Step 1: Failing tests**: in `tests/test_ui_redesign_runtime.py` (use the `_install`/`_FakeLLM` monkeypatch) add: a model reply with a `theme.tokens` entry for a stock key yields `plan.theme.tokens` and a non-stock key is dropped into `unsupported`; an unchanged value is not a change; the brief no longer contains `thomas/server/web/`. In the client contract test add pins for `ThomasOverlay.record(` and the two result strings.
- [ ] **Step 2: Implement** per the interface; read each anchor region before editing; keep every existing pin in `tests/test_ui_redesign_client_contract.py` (run it first to list them).
- [ ] **Step 3: Run, commit**: both test files, ruff, the pinned suites. CHANGELOG `### Changed (the first Redesign creates your overlay instead of editing stock files)`. Commit subject `feat(redesign): the first Redesign-with-AI action creates the user overlay`.

---

### Task 5: Live proof (C5)

**Files:**
- Create: `tests/test_the_first_redesign_creates_the_overlay.py`
- Modify: `CHANGELOG.md`, `plans/thomas/tasks/EVERY-USERS-THOMAS-P2-FORK-BY-OVERLAY/PLAN.md`

- [ ] **Step 1: The end-to-end test.** Start the real app on a spare port in-process (read how an existing web smoke test boots one) with `THOMAS_OVERLAY_DIR` at `tmp_path/overlay`; in headless Chromium: `page.route("**/api/ui/redesign", ...)` returns a canned plan `{layout: [{target_index: 0, ui_id: "chat.sidebar", style: {backgroundColor: "#101a2e"}, width: 320}], theme: {tokens: {"--c-accent": "#2ecc71"}, identity: {name: "Otto"}}}`; arm Redesign, pick the sidebar, Apply; assert: `manifest.json` exists with rev 3 and the three birth files; the result line names the overlay; `getComputedStyle(#tc-shell).getPropertyValue('--c-accent')` is `#2ecc71` on `/` AND `documentElement` on `/settings?embed=1` (both, never one); the brand reads `Otto`; a second Chat tab opened from the sidebar shows the sidebar background `#101a2e` on first paint with no theme click; a second write from home is adopted by the already-open tab without reload (BroadcastChannel); `localStorage.thomas_ui_layout_v2` no longer holds `chat.sidebar` under `saved`; `git status --porcelain thomas/server/web` in the repo is empty; the overlay directory contains nothing the base wrote beyond the four files; corrupting `manifest.json` then reloading `/` shows stock and `GET /api/ui/overlay` carries a note.
- [ ] **Step 2: Owner-style run on a second port** with a real model: the same flow with a real instruction (`make the sidebar darker and a bit wider`), screenshots in nebula and light, `python -m thomas.server.overlay list` output kept.
- [ ] **Step 3: Reviews.** Run `/code-review` and `/security-review` on the C1-C4 diff (a new write route under `thomas/server/`); fix rounds until clean; then the phase 2 board summary to `claude`, the task plan status, and a memory note.

---

## Self-review

- Spec coverage: first Redesign creates the overlay (Task 4 + Task 5 proof); themes, restyled elements, renamed identity and additions live as a layer (Task 1 schema, Task 3 apply); tokens.css pattern extended (render emits the exact tokens.css selector grammar; overlay themes derive from stock at render time so base updates flow under); storage shape deliberate and documented (Task 1 `docs/OVERLAY.md`, birth files, boundary tests); manifest of what it overrides (`resolve` exposed by the route and the CLI, never a second summary); phase 3/4 boundary (records carry `base`, `stock_value`, `anchor.fragile`; `python -m thomas.server.overlay check` is the phase-4 seed; assets reserved for phase 3).
- Placeholder scan: the "read first" instructions name the exact function or line range to read; every other step carries its code or its exact edit.
- Type consistency: `AppendResult` fields match the route's response; the `view` shape matches between `render.build_view`, `overlay_runtime.js`, `chat_themes.mergeOverlay` and `ui_edit_layout.refreshOverlay`; `ThomasOverlay.record` signature matches `ui_redesign_select.js`'s call.
