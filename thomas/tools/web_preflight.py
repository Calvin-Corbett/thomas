"""Deterministic web preflight — does this page actually boot?

These checks were written inside ``thomas/forge/anvil/build_verify.py``, so only
the Forge/Code path could run them. The marketplace Exhaustive pipeline verified
its ``ui`` family with a structural files-exist check and nothing else: the task
type whose whole purpose is building a UI was the one with no web verification
at all.

The obvious fix — import the Forge helpers from the marketplace verifier — is
rejected by the import gate, because ``_architecture.py`` declares
``marketplace`` may depend on core/tools/plugins/server and NOT on ``forge``.
CLAUDE.md also asks that existing cross-layer imports be inverted rather than
joined by new ones. Both layers already depend on ``tools``, so ``tools`` is the
home, and both call in rather than one reaching across.

Nothing here runs generated JavaScript in Thomas's process. ``node --check``
parses without executing; everything else is lexical or reads bytes. That rule
is the reason these checks are worth trusting, and it is why the module imports
only the standard library — no project module, so no layer can be dragged in
behind it.

What each check exists for is documented on the function; every one of them was
written after a real build shipped broken and every existing check passed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_SCRIPT_RE = re.compile(
    r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)
SCRIPT_SRC_RE = re.compile(r"\bsrc\s*=\s*(['\"])(?P<src>.*?)\1", re.IGNORECASE | re.DOTALL)
THROW_RE = re.compile(r"\bthrow\s+(?:new\s+)?(?:Error|TypeError|RangeError|ReferenceError|SyntaxError|URIError)\b")
SMOKE_LINKED_ASSET_SUFFIXES = {".css", ".js", ".mjs", ".cjs"}
SMOKE_DISCOVERY_MAX_HTML = 2000
SMOKE_DISCOVERY_MAX_BYTES = 2 * 1024 * 1024

ORPHAN_CHECK_SUFFIXES = {".js", ".mjs", ".cjs", ".css"}
ORPHAN_SCAN_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".json", ".css"}
ORPHAN_SCAN_MAX_FILES = 2000
ORPHAN_SCAN_MAX_BYTES = 2 * 1024 * 1024

# A caller with a changed-file list passes it. A caller holding only a finished
# workspace -- the marketplace verifier -- has no such list, so it asks for one.
WORKSPACE_WEB_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".cjs", ".css"}
WORKSPACE_SCAN_MAX_FILES = 500


class LocalAssetReferenceParser(HTMLParser):
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


def mask_js_strings_and_comments(source: str) -> str:
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


def has_obvious_top_level_throw(source: str) -> bool:
    """Return true only for an obvious error throw at JavaScript brace depth 0."""
    masked = mask_js_strings_and_comments(source)
    depth = 0
    for line in masked.splitlines(keepends=True):
        for match in THROW_RE.finditer(line):
            before = line[: match.start()]
            if depth == 0 and not before.strip():
                return True
        for char in line:
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
    return False


def javascript_syntax_error(source: str) -> str:
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


def orphaned_web_assets(cwd: str | Path, files: list[str]) -> list[str]:
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
        if path.suffix.lower() in ORPHAN_CHECK_SUFFIXES and path.is_file() and path.is_relative_to(root)
    ]
    if not candidates:
        return []

    haystack: list[tuple[Path, str]] = []
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= ORPHAN_SCAN_MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in ORPHAN_SCAN_SUFFIXES:
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
        # Candidate files stay IN the haystack, paired with their own path.
        #
        # They used to be skipped outright, with the comment "a file mentioning
        # only itself is still an orphan" -- a true statement that the code
        # over-delivered on. `candidates` is exactly the web assets this run
        # wrote, so skipping all of them meant the only evidence that could make
        # a candidate reachable came from files the run did NOT touch. For any
        # two assets written in the same pass where one imports the other, the
        # reference was structurally invisible, and the imported file could only
        # ever be reported as an orphan -- however correct the code was.
        #
        # The self-reference exclusion it was reaching for is kept below, by
        # comparing paths at match time rather than by removing the text.
        try:
            if path.stat().st_size > ORPHAN_SCAN_MAX_BYTES:
                continue
            haystack.append((path.resolve(), path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        scanned += 1

    failures: list[str] = []
    for path in candidates:
        # Any OTHER file mentioning this name makes it reachable; a file that
        # only mentions itself does not.
        if any(other != path and path.name in text for other, text in haystack):
            continue
        if True:
            # "takes effect", because this checks stylesheets too and a
            # stylesheet does not run. A message that misdescribes the file it
            # is about invites the reader to decide it does not really apply --
            # and an orphaned CSS file is just as dead as an orphaned script.
            failures.append(
                f"{path.name} was written but nothing loads it -- no script tag, link, import or "
                f"reference anywhere in the project, so none of it takes effect"
            )
    return failures


def duplicate_script_includes(cwd: str | Path, files: list[str]) -> list[str]:
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
            if page.stat().st_size > SMOKE_DISCOVERY_MAX_BYTES:
                continue
            source = page.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        parser = LocalAssetReferenceParser()
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


def artifact_preflight_failures(cwd: str | Path, files: list[str]) -> list[str]:
    """Find safe, deterministic web boot failures before the verifier subprocess.

    Inline scripts and existing local ``src`` dependencies of changed HTML are
    inspected, as are changed JavaScript files.  No generated JavaScript is
    executed in Thomas's process; findings are passed into the Forge verifier
    subprocess so it exits nonzero and the streamed returncode is honest, and
    are reported directly by the marketplace ``ui`` checker.
    """
    root = Path(cwd).resolve()
    failures: list[str] = orphaned_web_assets(root, files)
    # Include the pages that OWN a changed asset, not only changed pages. A run
    # that edits just the renderer leaves a duplicate include in the page it
    # belongs to unreported, which is the shape the original failure took: the
    # page was written once and then only the script was touched afterwards.
    failures.extend(duplicate_script_includes(root, sorted({*files, *browser_smoke_files(root, files)})))
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
        if has_obvious_top_level_throw(source):
            failures.append(f"obvious JavaScript boot failure in {label}: top-level throw")
        parse_error = javascript_syntax_error(source)
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
        for number, match in enumerate(INLINE_SCRIPT_RE.finditer(html), start=1):
            src_match = SCRIPT_SRC_RE.search(match.group("attrs") or "")
            if src_match:
                src = src_match.group("src").strip().split("?", 1)[0].split("#", 1)[0]
                if src and "://" not in src and not src.startswith("//"):
                    linked = (root / src.lstrip("/")) if src.startswith("/") else (path.parent / src)
                    inspect_script(linked, f"{name} -> {src}")
            else:
                body = match.group("body") or ""
                if has_obvious_top_level_throw(body):
                    failures.append(
                        f"obvious JavaScript boot failure in {name} inline script {number}: top-level throw"
                    )
                parse_error = javascript_syntax_error(body)
                if parse_error:
                    failures.append(
                        f"{name} inline script {number} does not parse, so the page is blank: {parse_error}"
                    )
    return failures


def browser_smoke_files(cwd: str | Path, changed_files: list[str]) -> list[str]:
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
        if path.suffix.lower() in SMOKE_LINKED_ASSET_SUFFIXES and path.is_file() and path.is_relative_to(root)
    ]
    claimed: set[Path] = set()
    if assets:
        candidates = sorted({*root.rglob("*.html"), *root.rglob("*.htm")})
        for candidate in candidates[:SMOKE_DISCOVERY_MAX_HTML]:
            try:
                if candidate.stat().st_size > SMOKE_DISCOVERY_MAX_BYTES:
                    continue
                source = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            parser = LocalAssetReferenceParser()
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
        html_paths |= owners_by_mention(root, [a for a in assets if a not in claimed], html_paths)
    return sorted(str(path.relative_to(root)).replace("\\", "/") for path in html_paths)


def owners_by_mention(root: Path, assets: list[Path], already: set[Path]) -> set[Path]:
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
            if path.stat().st_size > SMOKE_DISCOVERY_MAX_BYTES:
                return False
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        return any(name in source for name in needles)

    # A script that names the asset is treated as carrying it, so the page that
    # loads THAT script is the one worth running.
    names |= {p.name for p in scripts[:SMOKE_DISCOVERY_MAX_HTML] if mentions(p, names)}
    return {p.resolve() for p in pages[:SMOKE_DISCOVERY_MAX_HTML] if mentions(p, names)} - already


def workspace_web_files(cwd: str | Path) -> list[str]:
    """Relative paths of the web files in a finished workspace.

    The Forge path knows exactly which files a run changed, because it diffs the
    worktree. The marketplace Exhaustive pipeline does not -- it is handed a
    finished workspace directory and nothing else -- so it asks here for the set
    to preflight instead of inventing its own walk. Hidden directories and
    ``node_modules`` are skipped, and the walk is capped, so a vendored tree
    cannot turn one verification into thousands of ``node --check`` runs.
    """

    root = Path(cwd).resolve()
    if not root.is_dir():
        return []
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= WORKSPACE_SCAN_MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in WORKSPACE_WEB_SUFFIXES:
            continue
        # RELATIVE parts, for the reason recorded in orphaned_web_assets: Thomas
        # keeps every workspace under ~/.thomas, so an absolute-path test makes
        # ".thomas" an ancestor of everything and silently skips the whole tree.
        if any(part.startswith(".") or part == "node_modules" for part in path.relative_to(root).parts):
            continue
        found.append(path.relative_to(root).as_posix())
    return found
