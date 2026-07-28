"""Engine-side verification — the RUN/TEST step of the reason→edit→verify loop.

The dispatched agent is edit-only (it has no shell), but the build is a LOOP,
not a one-shot edit. After the agent's edit pass the *engine* — ordinary Python
in this process — runs a REAL check over the files the run changed and reflects
its REAL exit code back into the same streamed transcript. Nothing here is ever
fabricated: the pass/fail shown is the genuine returncode of a genuine subprocess.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .bridge_config import emergency_stop_active
from .bridge_prompts import compose_fix_prompt
from .forge_event_stream import FORGE_EVENT_KEY
from .web_artifact_smoke import smoke_html_artifacts

# A small, self-contained verifier program: byte-compile each changed file and
# import each changed package module. A syntax error (py_compile) or an import
# error raises -> the subprocess exits non-zero -> the run is honestly a failure.
_VERIFY_SRC = (
    "import csv, html.parser, importlib, json, pathlib, shutil, subprocess, sys, py_compile, xml.etree.ElementTree as ET, zipfile\n"
    "files = json.loads(sys.argv[1])\n"
    "mods = json.loads(sys.argv[2])\n"
    "preflight_failures = json.loads(sys.argv[3])\n"
    "assert not preflight_failures, '; '.join(preflight_failures)\n"
    "for f in files:\n"
    "    p=pathlib.Path(f); raw=p.read_bytes(); ext=p.suffix.lower()\n"
    "    if ext=='.py': py_compile.compile(f,doraise=True); print('compiled '+f)\n"
    "    elif ext in {'.js','.mjs','.cjs'}:\n"
    "        node=shutil.which('node'); assert node,'node is required to verify JavaScript'; r=subprocess.run([node,'--check',f],capture_output=True,text=True); assert r.returncode==0,r.stdout+r.stderr; print('checked '+f)\n"
    "    elif ext in {'.html','.htm'}: text=raw.decode('utf-8'); parser=html.parser.HTMLParser(); parser.feed(text); assert '<' in text and '>' in text,'HTML has no elements'; print('parsed '+f)\n"
    "    elif ext=='.json': json.loads(raw.decode('utf-8')); print('parsed '+f)\n"
    "    elif ext=='.csv': rows=list(csv.reader(raw.decode('utf-8-sig').splitlines())); assert rows,'CSV is empty'; print('parsed '+f)\n"
    "    elif ext in {'.svg','.xml'}: ET.fromstring(raw); print('parsed '+f)\n"
    "    elif ext=='.css': text=raw.decode('utf-8'); assert text.count('{')==text.count('}'),'unbalanced CSS braces'; print('checked '+f)\n"
    "    elif ext=='.pdf': assert raw.startswith(b'%PDF-'),'invalid PDF header'; print('opened '+f)\n"
    "    elif ext in {'.docx','.xlsx','.pptx'}: assert zipfile.is_zipfile(p),'invalid Office document'; print('opened '+f)\n"
    "    elif ext=='.png': assert raw.startswith(b'\\x89PNG\\r\\n\\x1a\\n'),'invalid PNG'; print('opened '+f)\n"
    "    elif ext in {'.jpg','.jpeg'}: assert raw.startswith(b'\\xff\\xd8') and raw.endswith(b'\\xff\\xd9'),'invalid JPEG'; print('opened '+f)\n"
    "    else: raw.decode('utf-8'); print('read '+f)\n"
    "for m in mods:\n"
    "    importlib.import_module(m)\n"
    "    print('imported ' + m)\n"
    "print('STATIC_VERIFY_OK: ' + str(len(files)) + ' files checked, ' + str(len(mods)) + ' imported')\n"
)

_INLINE_SCRIPT_RE = re.compile(
    r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_SRC_RE = re.compile(r"\bsrc\s*=\s*(['\"])(?P<src>.*?)\1", re.IGNORECASE | re.DOTALL)
_THROW_RE = re.compile(r"\bthrow\s+(?:new\s+)?(?:Error|TypeError|RangeError|ReferenceError|SyntaxError|URIError)\b")
_REPAIR_TRUNCATION_SUFFIXES = {".css", ".html", ".htm", ".js", ".mjs", ".cjs"}
_REPAIR_TRUNCATION_MIN_BYTES = 1024
_REPAIR_TRUNCATION_RATIO = 0.25
_SMOKE_LINKED_ASSET_SUFFIXES = {".css", ".js", ".mjs", ".cjs"}
_SMOKE_DISCOVERY_MAX_HTML = 2000
_SMOKE_DISCOVERY_MAX_BYTES = 2 * 1024 * 1024


class _LocalAssetReferenceParser(HTMLParser):
    """Collect actual script/link URLs without matching comments or body prose."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        if tag.lower() == "script" and values.get("src"):
            self.references.append(values["src"])
        elif tag.lower() == "link" and values.get("href"):
            self.references.append(values["href"])


def _mask_js_strings_and_comments(source: str) -> str:
    """Mask JS literals/comments while retaining newlines and brace positions.

    The Code verifier is intentionally not a JavaScript runtime.  Executing an
    arbitrary generated app merely to inspect it would grant the app the local
    user's permissions.  This small lexical pass instead supports one narrow,
    fail-closed boot check: an unconditional top-level ``throw new Error``.  It
    ignores throw-looking text in strings/comments and throws inside functions or
    control blocks, which keeps the check useful without pretending to prove full
    browser behavior.
    """
    out = list(source)
    state = "code"
    quote = ""
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char in {"'", '"', "`"}:
                state, quote, out[index] = "string", char, " "
            elif char == "/" and nxt == "/":
                state, out[index], out[index + 1] = "line_comment", " ", " "
                index += 1
            elif char == "/" and nxt == "*":
                state, out[index], out[index + 1] = "block_comment", " ", " "
                index += 1
        elif state == "string":
            if char != "\n":
                out[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                state = "code"
        elif state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                out[index] = " "
        else:
            if char != "\n":
                out[index] = " "
            if char == "*" and nxt == "/":
                out[index + 1] = " "
                index += 1
                state = "code"
        index += 1
    return "".join(out)


def _has_obvious_top_level_throw(source: str) -> bool:
    """Return true only for an obvious error throw at JavaScript brace depth 0."""
    masked = _mask_js_strings_and_comments(source)
    depth = 0
    for line in masked.splitlines(keepends=True):
        for match in _THROW_RE.finditer(line):
            before = line[: match.start()]
            if depth == 0 and not before.strip():
                return True
        for char in line:
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
    return False


def _javascript_syntax_error(source: str) -> str:
    """Return a one-line parse error for JavaScript that cannot even be read.

    A syntax error is the loudest possible failure and the easiest to miss from
    the outside: the browser refuses the whole script, nothing runs, and the page
    is simply blank. Thomas shipped a 29KB game whose entire body was one script
    with `const a={},b={},...,wave:1,...}` -- object-literal syntax spliced into a
    const declaration list. It reported success. Nothing had ever tried to parse
    what it wrote.

    ``node --check`` parses WITHOUT executing, so this keeps the module's rule
    that no generated JavaScript runs in Thomas's process. If node is missing the
    check is skipped rather than guessed at -- a wrong "your game is broken" is
    worse than no opinion.
    """
    if not str(source or "").strip():
        return ""
    node = shutil.which("node")
    if not node:
        return ""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(source)
            tmp = Path(handle.name)
        proc = subprocess.run(
            [node, "--check", str(tmp)],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        if tmp is not None:
            with suppress(OSError):
                tmp.unlink()
    if proc.returncode == 0:
        return ""
    # Carry the offending SOURCE back, not just the message. node reports a line
    # number, and for an inline script that number counts from the start of the
    # extracted block -- so it does not match any line of the HTML file the
    # reader will open. Worse, a parser blames where it gave up rather than
    # where the mistake is: blocktown-84.html is blamed at line 539, a template
    # literal that parses perfectly on its own, while the real fault sits
    # earlier. A repair attempt sent to a coordinate that points nowhere edits
    # correct code and never converges, which is how the duplicate-script bug
    # burned 25 passes.
    #
    # The quoted line is greppable and unambiguous no matter how it is numbered.
    stderr_lines = (proc.stderr or "").splitlines()
    message = next((ln.strip() for ln in stderr_lines if "Error:" in ln), "JavaScript could not be parsed")
    source_line = ""
    for index, line in enumerate(stderr_lines):
        # The frame node prints is: path:lineno / the source / a caret row.
        if re.match(r"^.*:\d+$", line.strip()) and index + 2 < len(stderr_lines):
            if "^" in stderr_lines[index + 2]:
                source_line = stderr_lines[index + 1].strip()
                break
    if source_line:
        return f"{message[:160]} -- parser stopped at: {source_line[:120]} (the mistake may be earlier)"
    return message[:200]


_ORPHAN_CHECK_SUFFIXES = {".js", ".mjs", ".cjs", ".css"}
_ORPHAN_SCAN_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".json", ".css"}
_ORPHAN_SCAN_MAX_FILES = 2000
_ORPHAN_SCAN_MAX_BYTES = 2 * 1024 * 1024


def _orphaned_web_assets(cwd: str | Path, files: list[str]) -> list[str]:
    """Find a web asset this run wrote that nothing in the project loads.

    Thomas was asked to give a game a third-person camera. It wrote
    trey-depth-renderer.js -- 8.5KB of genuine perspective projection, horizon,
    depth sorting and zombie sprites -- and never added a script tag for it. The
    page still had exactly one inline script and looked identical. Every check
    passed, because every check asks "does this parse", and dead code parses
    perfectly.

    Deliberately conservative: a file counts as reachable if its NAME appears
    anywhere in any project source -- a script tag, an import, a dynamic
    import(), a Worker, a manifest entry, a bundler config. Only a file nothing
    mentions at all is reported, so a build step or an unusual loader is not
    called a mistake.
    """
    root = Path(cwd).resolve()
    candidates = [
        path
        for path in ((root / name).resolve() for name in files)
        if path.suffix.lower() in _ORPHAN_CHECK_SUFFIXES and path.is_file() and path.is_relative_to(root)
    ]
    if not candidates:
        return []

    haystack: list[str] = []
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= _ORPHAN_SCAN_MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in _ORPHAN_SCAN_SUFFIXES:
            continue
        # RELATIVE parts. Testing the absolute path meant that for any project
        # living under ~/.thomas -- which is where Thomas keeps every project he
        # makes -- ".thomas" matched as an ANCESTOR of every file, so the whole
        # haystack was skipped and this check reported that nothing loads
        # anything. Always, for everyone.
        #
        # That is not a quiet failure. Told his script was unreferenced, Thomas
        # added a script tag; told again, he added a second one; the page then
        # ran the file twice and died on "Identifier 'canvas' has already been
        # declared", and he burned 25 passes on it. The duplicate-include check
        # added alongside this catches that wreckage -- this is the cause of it.
        if any(part in {".git", "node_modules", ".thomas"} for part in path.relative_to(root).parts):
            continue
        if path.resolve() in {c for c in candidates}:
            continue  # a file mentioning only itself is still an orphan
        try:
            if path.stat().st_size > _ORPHAN_SCAN_MAX_BYTES:
                continue
            haystack.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        scanned += 1
    blob = "\n".join(haystack)

    failures: list[str] = []
    for path in candidates:
        if path.name not in blob:
            failures.append(
                f"{path.name} was written but nothing loads it -- no script tag, import or reference "
                f"anywhere in the project, so none of it runs"
            )
    return failures


def _duplicate_script_includes(cwd: str | Path, files: list[str]) -> list[str]:
    """Find a page that loads the same local script more than once.

    Thomas was asked for a starfield and wrote a clean one, then included
    `starfield.js` twice -- once with `defer` in the head and once at the end of
    the body. The file ran twice, so its first `const` was declared twice, and
    the page died on `Identifier 'canvas' has already been declared`.

    Both files were individually perfect. `node --check` passes each of them,
    because neither is wrong; only the pair is. The browser found it, but the
    message names the SCRIPT while the fault is in the HTML, and Thomas spent
    its whole repair budget rewriting the JavaScript -- 61 checks, six issues,
    no convergence -- because the error pointed at the wrong file.

    A page loading the same local script twice is never intentional, so this is
    reported without hedging, and the message names the page and the duplicate
    so a repair attempt starts in the right file. Remote sources are ignored: a
    CDN listed twice is someone else's problem and may be a deliberate fallback.
    """

    root = Path(cwd).resolve()
    pages = [
        path
        for path in ((root / name).resolve() for name in files)
        if path.suffix.lower() in {".html", ".htm"} and path.is_file() and path.is_relative_to(root)
    ]
    failures: list[str] = []
    for page in pages:
        try:
            if page.stat().st_size > _SMOKE_DISCOVERY_MAX_BYTES:
                continue
            source = page.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        parser = _LocalAssetReferenceParser()
        try:
            parser.feed(source)
        except (ValueError, TypeError):
            continue
        seen: dict[str, int] = {}
        for raw_reference in parser.references:
            parsed = urlsplit(raw_reference)
            if parsed.scheme or parsed.netloc or raw_reference.startswith("//"):
                continue
            reference = unquote(parsed.path).replace("\\", "/")
            if not reference or Path(reference).suffix.lower() not in {".js", ".mjs", ".cjs"}:
                continue
            target = (root / reference.lstrip("/")) if reference.startswith("/") else (page.parent / reference)
            try:
                resolved = str(target.resolve())
            except OSError:
                continue
            seen[resolved] = seen.get(resolved, 0) + 1
        label = str(page.relative_to(root)).replace("\\", "/")
        for resolved, count in seen.items():
            if count < 2:
                continue
            name = Path(resolved).name
            failures.append(
                # States what is certainly true (it runs twice) and what follows
                # only IF the file declares one (a SyntaxError). The first
                # version asserted the error outright, which happened to hold
                # for starfield.js and would not for a file of function
                # declarations or an IIFE -- claiming a consequence more
                # specific than the evidence supports, in a message whose whole
                # job is to send a repair to the right place.
                f"{label} loads {name} {count} times, so it runs {count} times: its side effects repeat, "
                f"and any top-level const, let or class in it is declared twice, which is a SyntaxError. "
                f"Remove the duplicate script tag in {label}"
            )
    return failures


def _artifact_preflight_failures(cwd: str | Path, files: list[str]) -> list[str]:
    """Find safe, deterministic web boot failures before the verifier subprocess.

    Inline scripts and existing local ``src`` dependencies of changed HTML are
    inspected, as are changed JavaScript files.  No generated JavaScript is
    executed in Thomas's process; findings are passed into ``_VERIFY_SRC`` so the
    real verifier subprocess exits nonzero and the streamed returncode is honest.
    """
    root = Path(cwd).resolve()
    failures: list[str] = _orphaned_web_assets(root, files)
    # Include the pages that OWN a changed asset, not only changed pages. A run
    # that edits just the renderer leaves a duplicate include in the page it
    # belongs to unreported, which is the shape the original failure took: the
    # page was written once and then only the script was touched afterwards.
    failures.extend(_duplicate_script_includes(root, sorted({*files, *_browser_smoke_files(root, files)})))
    checked: set[Path] = set()

    def inspect_script(path: Path, label: str) -> None:
        resolved = path.resolve()
        if resolved in checked or not resolved.is_file() or not resolved.is_relative_to(root):
            return
        checked.add(resolved)
        try:
            source = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return
        if _has_obvious_top_level_throw(source):
            failures.append(f"obvious JavaScript boot failure in {label}: top-level throw")
        parse_error = _javascript_syntax_error(source)
        if parse_error:
            failures.append(f"{label} does not parse, so nothing on the page runs: {parse_error}")

    for name in files:
        path = (root / name).resolve()
        suffix = path.suffix.lower()
        if suffix in {".js", ".mjs", ".cjs"}:
            inspect_script(path, name)
            continue
        if suffix not in {".html", ".htm"} or not path.is_file() or not path.is_relative_to(root):
            continue
        try:
            html = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for number, match in enumerate(_INLINE_SCRIPT_RE.finditer(html), start=1):
            src_match = _SCRIPT_SRC_RE.search(match.group("attrs") or "")
            if src_match:
                src = src_match.group("src").strip().split("?", 1)[0].split("#", 1)[0]
                if src and "://" not in src and not src.startswith("//"):
                    linked = (root / src.lstrip("/")) if src.startswith("/") else (path.parent / src)
                    inspect_script(linked, f"{name} -> {src}")
            else:
                body = match.group("body") or ""
                if _has_obvious_top_level_throw(body):
                    failures.append(
                        f"obvious JavaScript boot failure in {name} inline script {number}: top-level throw"
                    )
                parse_error = _javascript_syntax_error(body)
                if parse_error:
                    failures.append(
                        f"{name} inline script {number} does not parse, so the page is blank: {parse_error}"
                    )
    return failures


def _browser_smoke_files(cwd: str | Path, changed_files: list[str]) -> list[str]:
    """Include HTML entrypoints that load a changed local CSS/JS asset."""

    root = Path(cwd).resolve()
    changed_paths = [(root / name).resolve() for name in changed_files]
    html_paths = {
        path
        for path in changed_paths
        if path.suffix.lower() in {".html", ".htm"} and path.is_file() and path.is_relative_to(root)
    }
    assets = [
        path
        for path in changed_paths
        if path.suffix.lower() in _SMOKE_LINKED_ASSET_SUFFIXES and path.is_file() and path.is_relative_to(root)
    ]
    claimed: set[Path] = set()
    if assets:
        candidates = sorted({*root.rglob("*.html"), *root.rglob("*.htm")})
        for candidate in candidates[:_SMOKE_DISCOVERY_MAX_HTML]:
            try:
                if candidate.stat().st_size > _SMOKE_DISCOVERY_MAX_BYTES:
                    continue
                source = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            parser = _LocalAssetReferenceParser()
            try:
                parser.feed(source)
            except (ValueError, TypeError):
                continue
            linked: set[Path] = set()
            for raw_reference in parser.references:
                parsed = urlsplit(raw_reference)
                if parsed.scheme or parsed.netloc or raw_reference.startswith("//"):
                    continue
                reference = unquote(parsed.path).replace("\\", "/")
                if not reference:
                    continue
                target = (root / reference.lstrip("/")) if reference.startswith("/") else (candidate.parent / reference)
                try:
                    resolved = target.resolve()
                except OSError:
                    continue
                if resolved.is_relative_to(root):
                    linked.add(resolved)
            if any(asset in linked for asset in assets):
                html_paths.add(candidate.resolve())
                claimed |= {asset for asset in assets if asset in linked}
        # Only widen the search for assets no page was found to reference. An
        # asset with a real owner is already covered precisely, and searching
        # for its name as text would drag in any page that merely mentions it.
        html_paths |= _owners_by_mention(root, [a for a in assets if a not in claimed], html_paths)
    return sorted(str(path.relative_to(root)).replace("\\", "/") for path in html_paths)


def _owners_by_mention(root: Path, assets: list[Path], already: set[Path]) -> set[Path]:
    """Find pages that load a changed asset in a way no tag parser can see.

    The parser above reads markup, so it only finds assets referenced by a
    literal `<script src>` or `<link href>`. Anything built at runtime --
    `createElement('script')`, a computed path, a dynamic `import()` -- is
    invisible to it, and "no owner found" is indistinguishable from "this asset
    has no owner": the change ships with no browser check at all. Thomas hit
    exactly this. He split a game's renderer into its own file and loaded it
    dynamically, so every later edit to that renderer was verified by nothing.

    A plain substring search for the filename finds those, and the bias is
    deliberately asymmetric: matching a page that merely names the file in a
    comment costs one extra browser run, while missing one costs a false green.
    One hop through JavaScript is included, because a page usually loads a
    module that loads the renderer rather than reaching it directly.

    Callers pass only the assets no page was found to reference. Text matching
    is the last resort, not a supplement -- an asset with a real owner is
    already covered precisely, and widening there would pull in every page that
    happens to name it in a comment.
    """

    wanted = set(assets)
    if not wanted:
        return set()
    names = {path.name for path in wanted}
    scripts = sorted(p for p in root.rglob("*.js") if p.is_file() and p.resolve() not in wanted)
    pages = sorted({*root.rglob("*.html"), *root.rglob("*.htm")})

    def mentions(path: Path, needles: set[str]) -> bool:
        try:
            if path.stat().st_size > _SMOKE_DISCOVERY_MAX_BYTES:
                return False
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        return any(name in source for name in needles)

    # A script that names the asset is treated as carrying it, so the page that
    # loads THAT script is the one worth running.
    names |= {p.name for p in scripts[:_SMOKE_DISCOVERY_MAX_HTML] if mentions(p, names)}
    return {p.resolve() for p in pages[:_SMOKE_DISCOVERY_MAX_HTML] if mentions(p, names)} - already


def _is_test_file(path: str) -> bool:
    """True for a pytest-shaped path (``tests/`` dir or ``test_*`` / ``*_test.py``)."""
    p = str(path).replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py") or "/tests/" in p or p.startswith("tests/")


def _importable_module_for(cwd: str | Path, path: str) -> str:
    """Dotted module name for ``path`` IFF it lives in a real package under ``cwd``.

    Only nested package modules (a top dir containing ``__init__.py``) are
    importable safely from the worktree; top-level scripts and non-identifier
    paths return ``""`` and are byte-compiled only (not executed).
    """
    p = str(path).replace("\\", "/")
    if not p.endswith(".py"):
        return ""
    segs = p[:-3].split("/")
    if segs and segs[-1] == "__init__":
        segs = segs[:-1]
    if len(segs) < 2 or not all(s.isidentifier() for s in segs):
        return ""
    if not (Path(cwd) / segs[0] / "__init__.py").exists():
        return ""
    return ".".join(segs)


def verify_python_changes(
    cwd: str | Path,
    changed_files: list[str],
    emit: Callable[[dict[str, Any]], None],
    *,
    timeout: int = 120,
    run_check: Any = None,
) -> tuple[bool, int, str]:
    """Run a REAL verification subprocess over the changed python files.

    Emits the check as a forge ``tool`` call and its result as a forge
    ``tool_result`` carrying the REAL exit code. Returns ``(ok, returncode, summary)``.

    * changed test files -> run them with ``pytest`` (executes the tests).
    * else -> byte-compile every changed ``.py`` and import the changed package
      modules (executes them) in ONE subprocess with ONE real exit code.

    ``run_check(cmd, cwd, timeout) -> (rc, out)`` is injectable for tests.
    Defensive: a check that cannot even be launched surfaces honestly as a failed
    tool result, never crashes the stream.
    """
    import subprocess
    import sys

    files = [str(f) for f in (changed_files or []) if (Path(cwd) / str(f)).is_file()]
    if not files:
        return False, 1, "changed paths could not be verified as files"

    tests = [f for f in files if _is_test_file(f)]
    if tests:
        cmd = [sys.executable, "-m", "pytest", *tests, "-q"]
        label = "pytest " + " ".join(tests)
    else:
        modules = [m for m in (_importable_module_for(cwd, f) for f in files) if m]
        preflight_failures = _artifact_preflight_failures(cwd, files)
        cmd = [
            sys.executable,
            "-c",
            _VERIFY_SRC,
            json.dumps(files),
            json.dumps(modules),
            json.dumps(preflight_failures),
        ]
        label = "static checks: syntax + parse + open (" + ", ".join(files) + ")"

    emit({FORGE_EVENT_KEY: "tool", "name": "run", "text": label[:200]})
    try:
        if run_check is not None:
            rc, out = run_check(cmd, str(cwd), timeout)
        else:
            proc = subprocess.run(  # noqa: S603 - cmd is python + repo-relative files we computed
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError) as exc:
        emit({FORGE_EVENT_KEY: "tool_result", "text": f"verification could not run: {exc}", "is_error": True})
        return False, 1, f"verification could not run: {exc}"

    ok = rc == 0
    body = str(out or "").strip()
    detail = f"exit {rc}" + (("\n" + body) if body else "")
    emit({FORGE_EVENT_KEY: "tool_result", "text": detail[:500], "is_error": not ok})
    smoke_files = _browser_smoke_files(cwd, files) if ok else []
    if smoke_files:
        emit(
            {
                FORGE_EVENT_KEY: "tool",
                "name": "run",
                "text": "offline real-browser smoke for changed HTML or linked web assets",
            }
        )
        smoke = smoke_html_artifacts(cwd, smoke_files, timeout=min(timeout, 30))
        smoke_detail = (
            "BROWSER_SMOKE_OK: " if smoke.ok and smoke.attempted else "BROWSER_SMOKE_SKIPPED: "
        ) + smoke.summary
        if smoke.attempted and not smoke.ok:
            smoke_detail = "BROWSER_SMOKE_FAILED: " + smoke.summary
        emit(
            {
                FORGE_EVENT_KEY: "tool_result",
                "text": smoke_detail[:1500],
                "is_error": bool(smoke.attempted and not smoke.ok),
            }
        )
        if smoke.attempted and not smoke.ok:
            return False, 1, smoke_detail
        detail += "\n" + smoke_detail
    return ok, rc, detail[-1500:]


def _snapshot_repair_files(cwd: str | Path, changed_files: list[str]) -> dict[Path, bytes]:
    """Capture existing web sources before a repair that may touch clean owners too."""

    root = Path(cwd).resolve()
    snapshot: dict[Path, bytes] = {}
    candidates = {(root / name).resolve() for name in changed_files}
    candidates.update(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _REPAIR_TRUNCATION_SUFFIXES
    )
    for path in sorted(candidates):
        if path.suffix.lower() not in _REPAIR_TRUNCATION_SUFFIXES or not path.is_relative_to(root):
            continue
        try:
            snapshot[path] = path.read_bytes()
        except OSError:
            continue
    return snapshot


def _restore_catastrophic_repair_truncations(snapshot: dict[Path, bytes]) -> tuple[list[str], list[str]]:
    """Restore web sources a fix pass unexpectedly reduced to a tiny stub."""

    restored: list[str] = []
    failed: list[str] = []
    for path, before in snapshot.items():
        if len(before) < _REPAIR_TRUNCATION_MIN_BYTES:
            continue
        try:
            after_size = path.stat().st_size
        except OSError:
            after_size = 0
        if after_size >= len(before) * _REPAIR_TRUNCATION_RATIO:
            continue
        try:
            path.write_bytes(before)
        except OSError:
            failed.append(path.name)
            continue
        restored.append(path.name)
    return restored, failed


def _verify_and_iterate(
    cwd: str | Path,
    snap_before: dict[str, str],
    emit: Callable[[dict[str, Any]], None],
    run_pass: Callable[[str], tuple[int, str]],
    goal: str,
    *,
    verifier: Any = None,
    max_fix_iters: int = 2,
) -> int:
    """Verify THIS run's changes; on failure, feed the failure back for bounded fixes.

    ``run_pass(prompt) -> (rc, out)`` runs one more edit pass through the SAME CLI.
    Returns the final returncode: ``0`` when verification ultimately passes (or
    there was nothing to verify), else the non-zero exit of the failing check or
    the failing fix pass. Never raises — a fix pass that errors surfaces honestly.
    """
    from thomas.forge.anvil import forge_code_git

    verify = verifier or verify_python_changes
    changed = forge_code_git.delta_since(cwd, snap_before)
    if not changed:
        return 0  # nothing this run touched -> caller surfaces the no-op honestly

    ok, rc, summary = verify(cwd, changed, emit)
    iters = 0
    limit = max(0, int(max_fix_iters))
    while not ok and iters < limit:
        # A fix pass re-invokes the agent, so the kill switch gates it too: if an
        # operator drops the STOP file mid-build, stop iterating and surface the
        # last real failure rather than spawning another build.
        if emergency_stop_active():
            emit({FORGE_EVENT_KEY: "error", "text": "emergency stop active — halting fix loop"})
            return rc or 1
        iters += 1
        emit({FORGE_EVENT_KEY: "meta", "text": f"verification failed (exit {rc}); fix pass {iters}/{limit}"})
        repair_snapshot = _snapshot_repair_files(cwd, changed)
        fix_error: Exception | None = None
        frc = 0
        try:
            frc, _out = run_pass(compose_fix_prompt(goal, summary))
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            fix_error = exc
        restored, restore_failed = _restore_catastrophic_repair_truncations(repair_snapshot)
        if restored or restore_failed:
            detail = ", ".join(restored)
            if restore_failed:
                detail += ("; " if detail else "") + "restore failed for " + ", ".join(restore_failed)
            emit(
                {
                    FORGE_EVENT_KEY: "error",
                    "text": "verification repair was stopped after destructive truncation: " + detail,
                }
            )
            return rc or 1
        if fix_error is not None:
            emit({FORGE_EVENT_KEY: "error", "text": f"fix pass could not run: {fix_error}"})
            return rc or 1
        if frc != 0:
            return frc
        changed = forge_code_git.delta_since(cwd, snap_before)
        if not changed:
            return 0
        ok, rc, summary = verify(cwd, changed, emit)
    return 0 if ok else (rc or 1)
