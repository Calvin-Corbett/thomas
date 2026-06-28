"""Pre-flight verification for generated web deliverables.

Claude Code's defining strength is that it closes the loop: build -> run ->
observe -> fix, and never claims "done" on something it hasn't seen work. Thomas
historically shipped a deliverable the moment a file existed on disk — which is
how a fully-coded football game reached the user as a blank white page (its
index.html referenced a styles.css / src/game.js that the user's browser was
blocked from loading, and nothing ever checked that the app actually rendered).

This module is the missing check: given a finished web deliverable, confirm the
entry document is non-empty and that every first-party asset it references
actually exists. It is intentionally dependency-free and side-effect-free so it
can run inside the worker finalize path and inside the headless stress harness.

A failed verification should downgrade a "completed" claim to "needs attention"
with the specific reason, not silently assert success.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# Reference attributes that point at a loadable sub-resource.
_REF_ATTRS = {
    "link": "href",
    "script": "src",
    "img": "src",
    "source": "src",
    "audio": "src",
    "video": "src",
    "iframe": "src",
}


def _is_external(ref: str) -> bool:
    """True for refs we should NOT treat as a local file we must produce."""
    r = ref.strip()
    if not r:
        return True
    low = r.lower()
    return low.startswith(("http://", "https://", "//", "data:", "blob:", "mailto:", "javascript:")) or r.startswith(
        "#"
    )


class _RefCollector(HTMLParser):
    """Collects everything a deliverable needs to load: generic asset refs, the
    <base href>, ES-module script sources, linked stylesheets, and the raw text of
    inline <script>/<style> blocks (for import/url/fetch scanning)."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.base_href: str = ""
        self.module_srcs: list[str] = []
        self.linked_css: list[str] = []
        self.inline_scripts: list[str] = []
        self.inline_styles: list[str] = []
        self._cap: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        amap = {k.lower(): (v or "") for k, v in attrs}
        if t == "base":
            if amap.get("href"):
                self.base_href = amap["href"]
            return
        if t == "script":
            src = amap.get("src", "")
            if src:
                self.refs.append(src)  # a referenced script must exist on disk
                if amap.get("type", "").lower() == "module":
                    self.module_srcs.append(src)
            else:
                self._cap, self._buf = "script", []
            return
        if t == "style":
            self._cap, self._buf = "style", []
            return
        if t == "link":
            rel = amap.get("rel", "").lower()
            href = amap.get("href", "")
            if href and any(x in rel for x in ("stylesheet", "icon", "preload", "manifest")):
                self.refs.append(href)
                if "stylesheet" in rel:
                    self.linked_css.append(href)
            return
        attr_name = _REF_ATTRS.get(t)
        if attr_name:
            ref = amap.get(attr_name, "")
            if ref:
                self.refs.append(ref)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._cap == "script" and t == "script":
            self.inline_scripts.append("".join(self._buf))
            self._cap, self._buf = None, []
        elif self._cap == "style" and t == "style":
            self.inline_styles.append("".join(self._buf))
            self._cap, self._buf = None, []

    def handle_data(self, data: str) -> None:
        if self._cap:
            self._buf.append(data)


# Tags that mean "there is an actual app/visual here" even with little body text
# (a canvas game has a near-empty body but is clearly a real app).
_APP_TAGS = {
    "script",
    "canvas",
    "svg",
    "img",
    "video",
    "audio",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "select",
    "textarea",
}
_MIN_VISIBLE_TEXT = 20  # chars of visible BODY text below which (w/o an app tag) = stub


class _ContentSignal(HTMLParser):
    """Detect a placeholder/stub entry: valid HTML that renders effectively blank
    (no interactive/app element and almost no visible body text)."""

    def __init__(self) -> None:
        super().__init__()
        self.has_app = False
        self.body_text = 0
        self._skip_depth = 0  # inside <script>/<style>
        self._head_depth = 0  # inside <head> (title/meta text doesn't render in the page)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style"):
            self._skip_depth += 1
        if t == "head":
            self._head_depth += 1
        if t in _APP_TAGS:
            self.has_app = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        if t == "head" and self._head_depth:
            self._head_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._head_depth:
            return
        self.body_text += len(data.strip())

    @property
    def is_stub(self) -> bool:
        return not self.has_app and self.body_text < _MIN_VISIBLE_TEXT


@dataclass
class VerifyResult:
    ok: bool
    entry: str
    problems: list[str] = field(default_factory=list)
    checked_refs: int = 0
    missing_refs: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return f"Deliverable verified: {self.entry} renders, {self.checked_refs} asset(s) resolve."
        return "Deliverable NOT runnable — " + "; ".join(self.problems)


# ES-module imports (static `import x from "y"` and dynamic `import("y")`).
_IMPORT_RE = re.compile(r"""import\s+(?:[^'"()]*?\sfrom\s+)?['"]([^'"]+)['"]|import\s*\(\s*['"]([^'"]+)['"]""")
# CSS first-party refs: @import "x" / @import url(x) / url(x) inside stylesheets.
_CSS_REF_RE = re.compile(r"""@import\s+(?:url\(\s*)?['"]?([^'")\s]+)|url\(\s*['"]?([^'")\s]+)""", re.I)
# Runtime first-party loads worth flagging: fetch('x'), new Worker('x'), XHR open(...,'x').
_FETCH_RE = re.compile(
    r"""\bfetch\s*\(\s*['"]([^'"]+)['"]|new\s+Worker\s*\(\s*['"]([^'"]+)['"]|\.open\s*\(\s*['"][A-Z]+['"]\s*,\s*['"]([^'"]+)['"]""",
    re.I,
)


def _ref_targets(text: str, pattern: re.Pattern) -> list[str]:
    return [next(g for g in m.groups() if g) for m in pattern.finditer(text or "")]


def _exists_exact_case(target: Path, root: Path) -> bool:
    """True iff ``target`` exists as a file with EXACT-CASE path components under
    ``root``. Uses ``os.path.normpath`` (which resolves ``..``/``.`` WITHOUT
    canonicalising case the way ``Path.resolve()`` does on Windows), then walks each
    component against the real directory entries — so a `Style.css`/`style.css`
    mismatch that passes on the Windows dev box (and 404s on case-sensitive Linux /
    Cloudflare hosting) is caught."""
    rootn = os.path.normpath(str(root.resolve()))
    tn = os.path.normpath(str(target))
    if tn != rootn and not tn.startswith(rootn + os.sep):
        return False
    rel = os.path.relpath(tn, rootn)
    cur = Path(rootn)
    for part in Path(rel).parts:
        if part in (".", ""):
            continue
        try:
            names = {e.name for e in cur.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        cur = cur / part
    return cur.is_file()


def verify_web_deliverable(root: str | Path, entry: str = "index.html") -> VerifyResult:
    """Verify a web deliverable is actually runnable.

    Checks the entry document exists and is non-empty, then that every first-party
    asset it references — scripts (incl. ES-module imports), stylesheets and their
    @import/url() targets, images/media, and fetch()/Worker() loads — resolves to a
    real, exact-case file under ``root`` (honouring <base href>). External URLs
    (http/https/data/blob) are not required to exist locally and are skipped.
    """
    root = Path(root)
    entry_path = root / entry
    if not entry_path.is_file():
        # Fall back to any *.html if the named entry is absent.
        htmls = sorted(root.glob("*.html"))
        if not htmls:
            return VerifyResult(ok=False, entry=entry, problems=[f"no entry document ({entry}) and no *.html found"])
        entry_path = htmls[0]
        entry = entry_path.name

    try:
        html = entry_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return VerifyResult(ok=False, entry=entry, problems=[f"entry unreadable: {e}"])

    if not html.strip():
        return VerifyResult(ok=False, entry=entry, problems=[f"{entry} is empty (0 meaningful bytes)"])

    collector = _RefCollector()
    signal = _ContentSignal()
    try:
        collector.feed(html)
    except Exception:  # noqa: BLE001 — malformed HTML still yields the refs parsed so far
        pass
    try:
        signal.feed(html)
    except Exception:  # noqa: BLE001
        pass

    problems: list[str] = []
    # A non-empty file that renders nothing (no app element, no visible body text)
    # is a placeholder/stub — it would open as a blank page. Catch it before "done".
    if signal.is_stub:
        problems.append(f"{entry} has no visible content or interactive app (placeholder/stub)")

    # Resolution base honours <base href> (browsers resolve all relative refs against it).
    base_dir = entry_path.parent
    if collector.base_href and not _is_external(collector.base_href):
        base_dir = entry_path.parent / collector.base_href.split("?", 1)[0].split("#", 1)[0].lstrip("/")

    missing: list[str] = []
    checked = 0
    seen: set[str] = set()
    root_res = root.resolve()

    def _check(ref: str, *, label: str, rel_to: Path) -> None:
        nonlocal checked
        if _is_external(ref):
            return
        clean = ref.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        if not clean or clean in seen:
            return
        seen.add(clean)
        checked += 1
        raw_target = rel_to / clean
        try:
            raw_target.resolve().relative_to(root_res)
        except ValueError:
            problems.append(f"{label} escapes the deliverable: {ref}")
            missing.append(ref)
            return
        if not _exists_exact_case(raw_target, root):
            problems.append(f"missing {label}: {ref}")
            missing.append(ref)

    # 1) Direct HTML refs (scripts, stylesheets, images, media).
    for ref in collector.refs:
        _check(ref, label="referenced asset", rel_to=base_dir)

    # 2) ES-module imports — inline module scripts + the first-party module files they
    # pull in (one level). This is the "modern app, blank screen" class (defect: an
    # `import {x} from "./src/game.js"` with no such file passed as runnable).
    module_texts = list(collector.inline_scripts)
    for src in collector.module_srcs:
        if _is_external(src):
            continue
        mp = base_dir / src.split("?", 1)[0].lstrip("/")
        try:
            module_texts.append(mp.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass  # the missing src itself is already flagged via collector.refs
    for text in module_texts:
        for spec in _ref_targets(text, _IMPORT_RE):
            if spec.startswith((".", "/")):  # only bare-relative first-party imports
                _check(spec, label="imported module", rel_to=base_dir)

    # 3) CSS @import / url() in inline styles + first-party linked stylesheets.
    css_texts = list(collector.inline_styles)
    css_bases = [base_dir] * len(collector.inline_styles)
    for href in collector.linked_css:
        if _is_external(href):
            continue
        cp = base_dir / href.split("?", 1)[0].lstrip("/")
        try:
            css_texts.append(cp.read_text(encoding="utf-8", errors="replace"))
            css_bases.append(cp.parent)  # CSS urls resolve relative to the stylesheet
        except OSError:
            pass
    for text, cbase in zip(css_texts, css_bases):
        for url in _ref_targets(text, _CSS_REF_RE):
            if not _is_external(url) and not url.startswith("#"):
                _check(url, label="CSS asset", rel_to=cbase)

    # 4) Runtime first-party loads: fetch()/Worker()/XHR to a relative STATIC FILE.
    # Conservative to avoid flagging API endpoints: skip absolute "/api/…" paths and
    # anything without a file extension; only a relative path to a real-looking asset
    # file (data.json, worker.js, level.png) is checked.
    for text in collector.inline_scripts:
        for url in _ref_targets(text, _FETCH_RE):
            clean = url.split("?", 1)[0].split("#", 1)[0]
            name = Path(clean).name
            if not _is_external(url) and not url.startswith("/") and "." in name and not name.startswith("."):
                _check(url, label="fetched asset", rel_to=base_dir)

    return VerifyResult(
        ok=not problems,
        entry=entry,
        problems=problems,
        checked_refs=checked,
        missing_refs=missing,
    )
