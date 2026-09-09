# The user overlay

Every User's Thomas, phase 2 the internal design record.

Your overlay is the layer that makes this Thomas yours: themes, restyled
elements, a renamed agent identity, a default theme. It lives outside the
repository, stock Thomas never writes it on its own, and a stock update slides
underneath it without touching a file in it. Phase 3 exports it as a fork with
Thomas as tracked upstream; phase 4 checks every stock update against it.

## Where it lives

`THOMAS_OVERLAY_DIR` when set, otherwise `<THOMAS_HOME>/overlay`, where
`THOMAS_HOME` is the profile-suffixed data dir the config layer exports at boot
(`%LOCALAPPDATA%\Thomas\overlay` by default on Windows; `...\Thomas\work\overlay`
with `THOMAS_PROFILE=work`). `python -m thomas.server.overlay path` prints it.

```
overlay/
  manifest.json        the only source of truth; written only by thomas/server/overlay/manifest.py
  README.md            generated once at birth, never regenerated (it is your file)
  .gitattributes       generated once at birth ('manifest.json diff=json')
  .gitignore           generated once at birth (temp files)
  assets/              reserved for phase 3 (fonts, images addressed by asset records)
overlay.lock           transient O_CREAT|O_EXCL lock BESIDE the directory while a write is in
                       flight, so taking it never creates the directory
```

A refused write leaves no trace: validation and the hard limits run before
anything exists, and the directory, its birth files and the manifest are
created only inside the locked write of an accepted first record
(`thomas/server/overlay/store.py`).

## The boundary (enforced by tests)

- The base READS the overlay at request time and WRITES it only through
  `thomas.server.overlay.manifest.append`, which runs only on an explicit user action
  arriving at `POST /api/ui/overlay/records`. Startup, page serving, the
  web-build fingerprint, plugin install, janitors, migrations and updates never
  create, modify or delete anything under it. `tests/test_overlay_injection_contract.py`
  requests every page with the overlay absent and asserts it is still absent.
- Never in the overlay: the per-browser layout book's draft/history/future
  (`localStorage` `thomas_ui_layout_v2`), the Work dashboard spec channel
  (project data under `<root>/.thomas/work/`), raw CSS, absolute paths, or the
  per-browser theme CHOICE (`thomas_chat_theme` stays in localStorage; the
  overlay may only supply a default through a `setting:default_theme` record).
- Absent vs broken: a missing directory or manifest is stock Thomas (the view
  says `present: false`, one INFO log line). A manifest that exists but cannot
  be parsed, has the wrong shape, or holds a record missing a required key is
  BROKEN, not empty: pages still serve stock (surfacing fails open), the view's
  `notes` carry the error, and every write refuses (destruction fails closed).
  No code path ever falls back from broken to empty.

## The manifest (schema `thomas.overlay/1`)

```json
{"version": 1,
 "overlay": {"id": "ovl_7f3c2a9e4b1d", "schema": 1, "created_at": "2026-09-02T02:41:07Z",
   "created_from": {"thomas_version": "0.19.27", "git": "2b3ee4ea", "web_build": "3f9a1c0d77e2", "tokens_sha1": "9c1e0b..."}},
 "records": [
  {"id": "r0001", "at": "2026-09-02T02:41:07Z", "op": "set", "kind": "element",
   "address": "element:chat:desktop:chat.sidebar",
   "value": {"x": 0, "y": 0, "width": 320, "style": {"backgroundColor": "#101a2e"}},
   "anchor": {"exact": true, "fragile": false, "component": "aside", "label": "Chat sidebar", "policy": "move resize", "path": ""},
   "stock_value": null,
   "by": {"actor": "redesign", "action": "act_20260902T024107Z_a1c3", "instruction": "make the sidebar darker and a bit wider", "targets": ["chat.sidebar"]},
   "base": {"thomas_version": "0.19.27", "git": "2b3ee4ea", "web_build": "3f9a1c0d77e2", "tokens_sha1": "9c1e0b..."}},
  {"id": "r0002", "at": "2026-09-02T02:41:07Z", "op": "set", "kind": "token",
   "address": "token:nebula:--c-accent", "value": "#2ecc71", "stock_value": "#8b8cff", "anchor": null,
   "by": {"...": "..."}, "base": {"...": "..."}},
  {"id": "r0003", "at": "2026-09-02T09:12:00Z", "op": "clear", "kind": "element",
   "address": "element:chat:desktop:chat.sidebar", "by": {"...": "..."}, "base": {"...": "..."}}
 ]}
```

- The header is written at birth and never mutated. Records are append-only;
  `rev` is `len(records)`; what is in effect is newest-wins per address and
  `op: clear` retracts an address. Every diff of the file is "+N lines at the end".
- Hard limits, refused as a whole with nothing written: 200 records per write,
  20,000 records in total, 500 active overrides on the RESOLVED result (so a
  clear paired with a set in the same write cannot slip past it), 2 MiB of
  manifest. Element numbers (`x, y, width, height, z`) must be finite numbers
  within 20,000 and never booleans; `hidden` must be a boolean; `icon` a
  `ph-` name. The API accepts no client revision: `rev` is always
  `len(records)` as written by the manifest module. `overlay_id` is a strict
  precondition on every write: the key must be present, `null` only while no
  overlay exists, the exact id once one does; anything else writes nothing.
  Every refusal carries a stable `code`: `bad_body`, `too_large` (by the bytes
  actually read, chunked or not), `overlay_mismatch` and `overlay_limit`
  (409, nothing written), `overlay_locked` (503), `overlay_broken` and
  `overlay_unsafe` (500, naming the file or the link).
- On load, the header and every record are fully validated (id shape, the
  integer schema, real ISO-8601 UTC stamps, ids in order, grammar per kind,
  guarded values, typed and bounded `by` and `base`); the JSON itself is strict
  (no NaN or Infinity, no duplicate keys at any depth); anything that fails is
  BROKEN and is never rendered or written over. A theme value is grammar-checked
  field by field (allowlisted keys, three colours for swatches and `meta.bot`,
  guarded text elsewhere) because it reaches chat.html's own theme menu and
  message markup. A disk failure mid-write rolls back only what that write
  created and never touches a preexisting file (`overlay_write_failed`).
- In the page, the JSON view escapes every `<`, so no value can close the view
  element or change how the tags after it parse; identity text is placed with
  `textContent`.
- Required keys on every record: `id, at, op, kind, address, by, base`; a `set`
  record also carries `value`, `stock_value` (what stock had at record time, so
  a later stock move is visible) and `anchor` (elements: how the target was
  found, `fragile: true` for a minted path).
- Addresses:
  - `token:<theme|*>:<--key>` - `--key` must be declared on tokens.css `:root`;
    the value passes the shared style guard (<= 160 chars, no `url(`,
    `expression(`, `@import`, none of `; { } < >`).
  - `theme:<name>` - `^[a-z][a-z0-9-]{1,31}$`, never a stock name; value
    `{label, tagline, derives_from, color_scheme, swatches, world, meta}`. The
    palette is composed at render time from `derives_from` plus token records,
    never baked, so stock updates flow under an overlay theme.
  - `element:<workspace>:<breakpoint>:<ui_id>` - the layout-book entry shape;
    styles are whitelisted by `thomas/server/overlay/style_whitelist.py`, the one copy
    the browser mirrors; a target whose `data-ui-policy` says `protected` or
    `no-edit` is refused.
  - `identity:<field>` - `name, welcome.title, welcome.sub, placeholder, title`;
    plain text, placed with `textContent`. `tagline` and `mark` are reserved
    and refused until a surface applies them. A `clear` must name a valid
    address for its kind, and the action envelope (`actor` 1-80 chars,
    `instruction` <= 2000, `targets` <= 50 short strings) is checked before
    anything is written.
  - `setting:default_theme` - consulted only when the browser has no valid choice.
  - `asset:<relpath>` - reserved; refused until phase 3.

## How it applies

`thomas/server/overlay/render.py` turns the manifest into an inline stylesheet (exact
tokens.css selector grammar, so it wins by source order), a JSON view
(`#thomas-overlay-view`) and one runtime script tag, and the page handlers
that already rewrite served HTML splice them before `</head>`. Every document,
including every tab iframe the browser shell opens, gets it at parse.
`workspace_shell.js` reads the view; `chat_themes.js` merges overlay themes and
token overrides into the theme payload before chat.html captures it;
`ui_edit_layout.js` layers element overrides under the local layout book, and
removing, reverting or resetting an overlaid element writes a `clear` record
rather than deleting a local copy the overlay would quietly re-cover;
`overlay_runtime.js` swaps the identity, adopts live updates and fans a write
out to every open document over `BroadcastChannel('thomas-overlay')`. Every
mutable client table (the theme payloads, the known-theme lists, the shell's
inline fonts, the current theme) is rebuilt from immutable stock on every
adoption, so a clear is as visible as a set in the document that made it, and a
theme cleared while it is shown falls back to the overlay's default theme, else
Nebula, in that document and in the stored choice.

`GET /api/ui/overlay` and `python -m thomas.server.overlay list` show what is
overridden; both call the same resolve, so there is no second summary to drift.
`python -m thomas.server.overlay check` exits non-zero when a record no longer
resolves against the current stock. It is the seed of the phase-4 update
protocol.
