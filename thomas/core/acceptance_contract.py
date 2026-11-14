"""The acceptance contract: what "done" means, fixed before the work starts.

Built from the three sources a model is prone to skip: the task's own words (every "must"/"every"/"all" sentence), the
data files the task names (every field in them is a feature the deliverable has to honour - the turnaround-time miss),
and the paths and commands the task says must exist or run. Items are either machine-checkable (checked here, in the
delivery environment) or judgement calls (left to a separate evaluator, and always named as unchecked in the reply).
Pure core module: no agent/server imports. Callers supply the workspace, the observed tool events, the produced text
and a command runner."""

from __future__ import annotations

import csv
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from thomas.core.acceptance_mood import is_requirement_sentence as _is_requirement_sentence
from thomas.core.acceptance_mood import reported_only
from thomas.core.acceptance_notes import without_thomas_notes
from thomas.core.acceptance_paths import committed_at_head, ends_in_a_version, named_paths, without_disowned
from thomas.core.acceptance_paths import is_apple_bundle_path as _is_apple_bundle_path
from thomas.core.acceptance_paths import resolve_named_path as _resolve
from thomas.core.acceptance_walk import SourceScanIncomplete, entered_dirs
from thomas.core.contained_process import run_contained
from thomas.core.verify_command_policy import deny_command as _deny_command
from thomas.core.verify_command_policy import pytest_timeout_guidance

KIND_DATA_FIELD = "data_field"
KIND_OUTPUT_PATH = "output_path"
KIND_COMMAND = "command"
KIND_COMPILES = "compiles"
KIND_REQUIREMENT = "requirement"
KIND_LEARNED = "learned"
KIND_FINISH = "finish"  # the reply's own VERIFY command, run as a check
KIND_HONEST_PAGE = "honest_page"  # no changed source may behave differently for an automated browser
MACHINE_KINDS = frozenset(
    {KIND_DATA_FIELD, KIND_OUTPUT_PATH, KIND_COMMAND, KIND_COMPILES, KIND_FINISH, KIND_HONEST_PAGE}
)
# The Minecraft build (2026-09-05) read navigator.webdriver and the user agent for Headless/Playwright/Puppeteer
# and never activated its renderer under automation: a HUD over a void for every verifier, a world for a person.
_AUTOMATION_DETECT_RE = re.compile(
    r"navigator\.webdriver|HeadlessChrome|\bPlaywright\b|\bPuppeteer\b|\bwebdriver\b|\bHeadless\b",
)
_WEB_SOURCE_EXT = frozenset({".js", ".mjs", ".ts", ".html", ".htm"})
# A comment that names the words is not detection: the scan reads code only.
_WEB_COMMENT_RE = re.compile(r"/\*.*?\*/|<!--.*?-->|^\s*//[^\n]*|(?<=[;{}\s])//[^\n]*", re.S | re.M)


def _web_code_only(text: str) -> str:
    return _WEB_COMMENT_RE.sub(" ", text)


# VERIFY checks this work, not the whole project. On 2026-10-07 six Build teams at once ended with
# `VERIFY: python -m pytest`: "exits 0 only if the task is complete" read as "run everything", and the whole
# ~13k-test suite cannot finish inside the finish check's clock.
FINISH_INSTRUCTION = (
    "A reply is not a finish. When the work is complete, end your reply with two lines: "
    "`EVIDENCE: <the actual output you observed that shows it works>` and "
    "`VERIFY: <one shell command that checks this work and exits 0 when it passes>`. "
    "Make VERIFY prove this work quickly: name the tests that cover what this work changed, for example "
    "`python -m pytest tests/test_<name>.py`, or, for work no test covers, a script or a check of the file it made. "
    "The VERIFY command is run in the workspace after you reply, with a limit of a few minutes, so do not run "
    "the whole test suite. A reply without it, or whose command fails, is not finished."
)
_FINISH_VERIFY_RE = re.compile(r"^\s*`?VERIFY:`?\s*`?(.+?)`?\s*$", re.M)

FLAG = "THOMAS_VERIFICATION_CONTRACT"

_DATA_EXT = (".json", ".csv", ".yaml", ".yml", ".toml")
_SOURCE_EXT = (
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".mjs",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".sh",
    ".sql",
    ".kt",
    ".swift",
    ".scala",
    ".html",
    ".vue",
    ".svelte",
)
# A stall guard, not a speed limit: a tree the skip lists have never met cannot hang a pass. A walk stopped here
# holds the run rather than pass it, so the speed comes from the skip lists, never from this clock.
_WALK_BUDGET_SECONDS = 60.0
_MAX_SOURCE_FILES = 600
_MAX_SOURCE_BYTES = 2_000_000
_MAX_FIELDS_PER_FILE = 80
_MAX_FIELDS_TOTAL = 200

_BACKTICK_RE = re.compile(r"`([^`\n]{3,240})`")
_RUNNER_VERB_RE = re.compile(
    r"^(?:python3?|pytest|node|npm|npx|pnpm|yarn|bun|deno|go|cargo|make|bash|sh|java|dotnet|ruby|php|mvn|gradle)\b"
)


# Bare `python`/`python3` resolves to sys.executable: the finish check's runner is a
# plain subprocess (below), not the cage, so it inherits this process's own PATH.
_LEADING_PYTHON_RE = re.compile(r'^(\s*)python3?(?=[\s"\'`]|$)')


def _resolve_interpreter(command: str) -> str:
    match = _LEADING_PYTHON_RE.match(command)
    if not match or not sys.executable:
        return command
    exe = subprocess.list2cmdline([sys.executable]) if os.name == "nt" else shlex.quote(sys.executable)
    return match.group(1) + exe + command[match.end() :]


# A sentence that LISTS its needs ("It needs A (x, y), B, and C.") is one requirement per entry: the Mario Kart request
# stated nine features in one sentence and the contract dropped the whole thing, so a one-track demo met every item
# left. Split at top-level commas and semicolons only -- a parenthesised aside keeps its inner commas.
_LIST_LEAD_RE = re.compile(
    r"^(?P<lead>(?:it|this|the \w+|that|which|you|thomas|we)?\s*(?:needs?|need to|has to|have to|requires?"
    r"|must (?:have|include|support)|should (?:have|include|support)|includes?|including)\b:?"
    # "I want all of this real and working: A, B, C" -- a want that introduces
    # its list with a colon (the Minecraft steer) is one requirement per entry.
    r"|(?:I|we)\s+(?:want|need|require|expect)\b[^:;.]{0,60}:)\s*",
    re.I,
)
_MIN_FRAGMENT_CHARS = 8
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{2,}$")
_UNUSED_FIELD_RE = re.compile(r"UNUSED_FIELD:\s*([\w.-]+)\s*:\s*(\w+)\s*-\s*(.+)", re.I)

Runner = Callable[[str, Path, float], tuple[int, str]]


def contract_enabled() -> bool:
    """On by default; ``THOMAS_VERIFICATION_CONTRACT=0`` restores the old behaviour."""
    raw = str(os.environ.get(FLAG, "")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass
class ContractItem:
    item_id: str
    kind: str
    description: str
    source: str = ""  # prompt | <data file name> | learned
    target: str = ""  # the field, path or command under check
    checked: bool = False  # a machine or evaluator verdict exists
    satisfied: bool = False
    detail: str = ""

    @property
    def machine(self) -> bool:
        return self.kind in MACHINE_KINDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractItem:
        return cls(
            item_id=str(data.get("item_id") or ""),
            kind=str(data.get("kind") or ""),
            description=str(data.get("description") or ""),
            source=str(data.get("source") or ""),
            target=str(data.get("target") or ""),
            checked=bool(data.get("checked", False)),
            satisfied=bool(data.get("satisfied", False)),
            detail=str(data.get("detail") or ""),
        )


@dataclass(frozen=True)
class ContractVerdict:
    met: bool  # every checked item is satisfied
    unmet: tuple[str, ...]  # item ids that were checked and failed
    unchecked: tuple[str, ...]  # item ids nobody has verified

    def to_payload(self) -> dict[str, Any]:
        return {"met": self.met, "unmet": list(self.unmet), "unchecked": list(self.unchecked)}


# ── building ────────────────────────────────────────────────────────


def _data_fields(path: Path) -> list[str]:
    """Identifier-shaped keys (snake/camel case, 3+ chars, not codes like NAN) in a data file.
    String-valued keys are labels (type, name, valid_date) and are skipped; numbers, booleans and
    containers are the features the data supports."""
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: Any) -> None:
        k = str(key)
        if k.startswith("_") or k.isupper() or not _IDENTIFIER_RE.match(k) or k in seen:
            return
        seen.add(k)
        keys.append(k)

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6 or len(keys) >= _MAX_FIELDS_PER_FILE:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if not isinstance(v, str):
                    add(k)
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node[:20]:
                walk(v, depth + 1)

    try:
        suffix = path.suffix.lower()
        if path.stat().st_size > _MAX_SOURCE_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".json":
            walk(json.loads(text))
        elif suffix == ".csv":
            for header in next(csv.reader(text.splitlines()[:1] or [""]), []):
                add(header.strip())
        elif suffix == ".toml":
            import tomllib

            walk(tomllib.loads(text))
        elif suffix in (".yaml", ".yml"):
            for line in text.splitlines():
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
                if m:
                    add(m.group(1))
    except (OSError, ValueError, StopIteration, ImportError):
        return []
    return keys


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", str(text or ""))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z`/])|\n", flat) if s.strip()]


def _top_level_split(text: str) -> list[str]:
    """Split at commas and semicolons that sit outside brackets and backticks."""
    parts: list[str] = []
    depth = 0
    in_code = False
    current: list[str] = []
    for ch in text:
        if ch == "`":
            in_code = not in_code
        elif not in_code and ch in "([{":
            depth += 1
        elif not in_code and ch in ")]}":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0 and not in_code:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _requirement_statements(sentence: str) -> list[str]:
    """One statement per listed need; the lead ("It needs") is kept on each so a fragment still reads as a requirement on
    its own. A sentence that is not a list comes back unchanged."""
    lead_match = _LIST_LEAD_RE.match(sentence)
    parts = _top_level_split(sentence)
    if lead_match is None or len(parts) < 3:
        return [sentence]
    lead = lead_match.group("lead").strip()
    rest = sentence[lead_match.end() :]
    statements: list[str] = []
    for raw in _top_level_split(rest):
        fragment = re.sub(r"^(?:and|or|plus|as well as)\s+", "", raw.strip(), flags=re.I).strip(" .")
        # A one-word entry names a feature ("crafting") when the list was
        # introduced with a colon; elsewhere a lone word is a stray.
        named_list = lead.endswith(":")
        if len(fragment) < (5 if named_list else _MIN_FRAGMENT_CHARS) or (len(fragment.split()) < 2 and not named_list):
            continue
        statements.append(f"{lead} {fragment}.")
    return statements or [sentence]


def _read_again(item: ContractItem, prompt_text: str, ws: Path) -> bool:
    """True when today's reading of the request decides a learned output check instead of the check itself.

    Every missed item is kept as a learned check and joins every later contract. A file the request still mentions is
    one this reading has already judged: were it an output, the request's own item would stand in the learned row's
    place. So a learned output the request mentions was a misreading since corrected (2026-09-27: other projects' files
    from Thomas's notes, a file the task deleted), and so is a file in the last commit. A learned output the request
    never mentions still stands, so a later request cannot quietly lose an earlier deliverable.
    """
    path = item.item_id.removeprefix("output:")
    return path in prompt_text or committed_at_head(Path(item.target) if item.target else ws / path, ws)


def requirement_statements(prompt_text: str) -> list[str]:
    """Read each whole requirement from the request, excluding Thomas's appended notes."""
    text = without_thomas_notes(str(prompt_text or ""))
    return [
        statement
        for sentence in _sentences(text)
        if len(sentence) >= 12 and _is_requirement_sentence(sentence)
        for statement in _requirement_statements(sentence)
    ]


def build_contract(
    prompt_text: str,
    workspace: str | Path,
    *,
    learned: Sequence[dict[str, Any]] = (),
    owned_output: str | None = None,
) -> list[ContractItem]:
    """Derive requirements; a trusted assignment scopes only machine output checks. ``owned_output`` is the caller's
    validated relative file, never model prose. Other named files remain semantic/context requirements for the
    assigned work."""
    ws = Path(workspace)
    text = without_thomas_notes(str(prompt_text or ""))
    items: list[ContractItem] = []
    seen_paths: set[str] = set()
    data_files: list[tuple[str, Path]] = []
    for token in named_paths(without_disowned(text), ws):
        if _is_apple_bundle_path(token):
            continue
        if token in seen_paths:
            continue
        seen_paths.add(token)
        resolved = _resolve(token, ws)
        if resolved is None:
            continue
        if resolved.is_file():
            if resolved.suffix.lower() in _DATA_EXT and Path(token).name not in {n for n, _ in data_files}:
                data_files.append((Path(token).name, resolved))
            continue
        if ends_in_a_version(token, _SOURCE_EXT + _DATA_EXT):
            continue  # no such file, and ".7b" in "org/video-ms-1.7b" is a model size, not an extension
        if resolved.is_dir() or committed_at_head(resolved, ws):
            continue  # a committed file the task refers to; missing now only if the task removed it
        items.append(
            ContractItem(
                item_id=f"output:{token}",
                kind=KIND_OUTPUT_PATH,
                description=f"`{token}` exists and is non-empty when the work is done (the task names it as an output).",
                source="prompt",
                target=str(resolved),
            )
        )
    total_fields = 0
    for name, path in data_files:
        for key in _data_fields(path):
            if total_fields >= _MAX_FIELDS_TOTAL:
                break
            total_fields += 1
            items.append(
                ContractItem(
                    item_id=f"field:{name}:{key}",
                    kind=KIND_DATA_FIELD,
                    description=(
                        f"Field `{key}` in `{name}`: decide whether the task needs it. If the deliverable should "
                        f"honour it, the code must consume it; if not, state `UNUSED_FIELD: {name}:{key} - <why>` "
                        "in your reply. Never add code merely to reference a field."
                    ),
                    source=name,
                    target=key,
                )
            )
    for m in _BACKTICK_RE.finditer(text):
        span = m.group(1).strip()
        if not _RUNNER_VERB_RE.match(span) or _deny_command(span):
            continue
        if reported_only(text, m.start(), m.end()):
            continue  # "`cmd` prints ... on dev today": what the request saw the command do, not a check
        if any(it.target == span for it in items):
            continue
        items.append(
            ContractItem(
                item_id=f"command:{span[:60]}",
                kind=KIND_COMMAND,
                description=f"`{span}` runs and exits 0 in the delivery environment.",
                source="prompt",
                target=span,
            )
        )
    items.append(
        ContractItem(
            item_id="compiles",
            kind=KIND_COMPILES,
            description="Every source file changed during the work still parses.",
            source="workspace",
        )
    )
    items.append(
        ContractItem(
            item_id="honest_page",
            kind=KIND_HONEST_PAGE,
            description=(
                "No source file changed during the work detects an automated browser (navigator.webdriver, "
                "Headless/Playwright/Puppeteer in the user agent) or behaves differently under one: a page that "
                "hides from verification cannot be verified."
            ),
            source="workspace",
        )
    )
    count = 0
    for statement in requirement_statements(prompt_text):
        if any(statement in it.description for it in items):
            continue
        count += 1
        items.append(
            ContractItem(
                item_id=f"req:{count}",
                kind=KIND_REQUIREMENT,
                description=statement,
                source="prompt",
                target=statement,
            )
        )
    for row in learned:
        item = ContractItem.from_dict(row)
        if not item.description or any(it.item_id == item.item_id for it in items):
            continue
        if item.kind == KIND_OUTPUT_PATH and _read_again(item, str(prompt_text or ""), ws):
            continue
        item.checked, item.satisfied, item.detail = False, False, ""
        # A standing goal is a requirement, not a check learned from a miss.
        if item.kind not in MACHINE_KINDS and not (item.source == "goal" and item.kind == KIND_REQUIREMENT):
            item.kind = KIND_LEARNED
        item.source = item.source or "learned"
        items.append(item)
    if owned_output is not None:
        # A private builder cannot create sibling outputs. Require its exact
        # assigned file even if it existed before work or prose omitted its path.
        items = [item for item in items if item.kind != KIND_OUTPUT_PATH]
        items.insert(
            0,
            ContractItem(
                item_id=f"output:{owned_output}",
                kind=KIND_OUTPUT_PATH,
                description=f"`{owned_output}` exists and is non-empty when the assigned work is done.",
                source="assignment",
                target=str(ws / owned_output),
            ),
        )
    return items


# ── evaluating ──────────────────────────────────────────────────────


def default_runner(command: str, cwd: Path, timeout: float) -> tuple[int, str]:
    """Run a contract command where the user would: in the workspace, with a clock. The python mapping is shared with
    KIND_COMMAND items too -- this runner cannot tell which kind called it, and both hit the same missing-python PATH
    failure. The clock holds everything the command starts: on 2026-10-07 four Build runs held at their finish for
    about 3 hours, because the old timeout killed only cmd.exe and the venv's python launcher and the interpreter under
    it kept the output pipes open until the whole suite was done."""
    resolved = _resolve_interpreter(command)
    try:
        code, out, err = run_contained(resolved, cwd=str(cwd), timeout=timeout)
    except OSError as exc:
        return 127, str(exc)
    if code is None:
        return 124, f"timed out after {int(timeout)}s"
    return int(code), (out + err)[-1500:]


def _source_files(workspace: Path, *, exclude: set[Path], since: float | None = None) -> list[Path]:
    """The first ``_MAX_SOURCE_FILES`` source files under *workspace* (changed since *since*, when given). A walk
    still going after ``_WALK_BUDGET_SECONDS`` raises ``SourceScanIncomplete`` carrying the files it had found."""
    out: list[Path] = []
    deadline = time.monotonic() + _WALK_BUDGET_SECONDS
    try:
        for depth, (root, dirs, files) in enumerate(os.walk(workspace)):
            dirs[:] = entered_dirs(dirs, top=workspace if depth == 0 else None)
            for name in files:
                if time.monotonic() >= deadline:
                    limit = f"the source walk stopped at its {_WALK_BUDGET_SECONDS:g} s limit in {root}"
                    raise SourceScanIncomplete(f"{limit} before it read every folder", found=out)
                p = Path(root) / name
                if p.suffix.lower() not in _SOURCE_EXT or p in exclude:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size > _MAX_SOURCE_BYTES or (since is not None and st.st_mtime < since):
                    continue
                out.append(p)
                if len(out) >= _MAX_SOURCE_FILES:
                    return out
    except OSError:
        pass
    return out


def _walk_or_gap(workspace: Path, *, exclude: set[Path], since: float | None = None) -> tuple[list[Path], str]:
    """The walk's files and "", or for a walk cut short the files it read and why. What those files show decides as
    usual; a check they cannot settle is not met with that reason, so the run is held instead of let through."""
    try:
        return _source_files(workspace, exclude=exclude, since=since), ""
    except SourceScanIncomplete as exc:
        return exc.found, f"not verified: {exc}"


def _field_consumed(key: str, sources: Iterable[Path], cache: dict[Path, str]) -> Path | None:
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])")
    for path in sources:
        text = cache.get(path)
        if text is None:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            cache[path] = text
        if pattern.search(text):
            return path
    return None


def declared_unused(response_text: str) -> dict[tuple[str, str], str]:
    """``UNUSED_FIELD: file:key - why`` lines in the reply: a stated decision, not a claim of work."""
    return {
        (m.group(1).strip(), m.group(2).strip()): m.group(3).strip()
        for m in _UNUSED_FIELD_RE.finditer(str(response_text or ""))
    }


def _command_observed(span: str, tool_events: Sequence[dict[str, Any]]) -> bool:
    needle = re.sub(r"\s+", " ", span).strip()
    for evt in tool_events:
        if not bool(evt.get("ok", False)):
            continue
        haystack = re.sub(r"\s+", " ", str(evt.get("command") or evt.get("name") or ""))
        if needle and needle in haystack:
            return True
    return False


def _run_detail(command: str, code: int, tail: str) -> str:
    """The exit code and the output's tail; a pytest run that ran out of time also says what to run instead."""
    detail = f"exit {code}" + (f": {tail.strip()[-300:]}" if code != 0 and tail.strip() else "")
    guidance = pytest_timeout_guidance(command) if code == 124 else ""
    return f"{detail}; {guidance}" if guidance else detail


def evaluate_contract(
    items: Sequence[ContractItem],
    *,
    workspace: str | Path,
    tool_events: Sequence[dict[str, Any]] = (),
    response_text: str = "",
    started_at: float | None = None,
    run_commands: bool = False,
    runner: Runner | None = None,
    command_timeout: float = 180.0,
) -> list[ContractItem]:
    """Recompute every machine item from the delivery environment. Judgement items
    are returned untouched (still unchecked) - the evaluator, not this function, owns them."""
    ws = Path(workspace)
    run = runner or default_runner
    data_paths = {ws / it.source for it in items if it.kind == KIND_DATA_FIELD}
    sources, sources_gap = _walk_or_gap(ws, exclude=data_paths)
    cache: dict[Path, str] = {}
    unused = declared_unused(response_text)
    out: list[ContractItem] = []
    for it in items:
        item = ContractItem.from_dict(it.to_dict())
        if item.kind == KIND_DATA_FIELD:
            hit = _field_consumed(item.target, sources, cache)
            item.checked = True
            if hit is not None:
                item.satisfied, item.detail = True, f"referenced in {hit.name}"
            elif (item.source, item.target) in unused:
                item.satisfied, item.detail = True, "declared unused: " + unused[(item.source, item.target)][:200]
            elif sources_gap:  # a partial walk cannot show the field is used nowhere
                item.satisfied, item.detail = False, sources_gap
            else:
                item.satisfied, item.detail = (
                    False,
                    f"`{item.target}` appears in no source file and no UNUSED_FIELD line",
                )
        elif item.kind == KIND_OUTPUT_PATH:
            p = Path(item.target)
            item.checked = True
            try:
                ok = p.is_file() and bool(p.read_bytes()[:256].strip())
            except OSError:
                ok = False
            item.satisfied, item.detail = ok, ("present" if ok else "missing or empty")
        elif item.kind == KIND_COMMAND:
            if run_commands:
                code, tail = run(item.target, ws, command_timeout)
                item.checked, item.satisfied = True, code == 0
                item.detail = _run_detail(item.target, code, tail)
            elif _command_observed(item.target, tool_events):
                item.checked, item.satisfied, item.detail = True, True, "observed succeeding in tool events"
            else:
                item.checked, item.satisfied, item.detail = True, False, "never observed running successfully"
        elif item.kind == KIND_FINISH:
            item.checked = True
            if not item.target:
                item.satisfied, item.detail = False, "the reply declares no VERIFY: command"
            elif _deny_command(item.target):
                item.satisfied, item.detail = False, "the VERIFY: command is not allowed to run"
            elif run_commands:
                code, tail = run(item.target, ws, command_timeout)
                item.satisfied = code == 0
                item.detail = _run_detail(item.target, code, tail)
            else:
                item.satisfied, item.detail = _command_observed(item.target, tool_events), "from tool events"
        elif item.kind == KIND_COMPILES:
            walked, gap = _walk_or_gap(ws, exclude=set(), since=started_at)
            changed = [p for p in walked if p.suffix == ".py"]
            failures: list[str] = []
            for p in changed[:200]:
                try:
                    compile(p.read_text(encoding="utf-8", errors="replace"), str(p), "exec")
                except (SyntaxError, ValueError) as exc:
                    failures.append(f"{p.name}: {exc}")
                except OSError:
                    continue
            item.checked, item.satisfied = True, not failures
            item.detail = "; ".join(failures)[:400] if failures else f"{len(changed)} changed python file(s) parse"
            if gap and not failures:
                item.satisfied, item.detail = False, gap
        elif item.kind == KIND_HONEST_PAGE:
            item.checked, item.satisfied, item.detail = True, True, "no changed web source detects automation"
            hits: list[str] = []
            walked, gap = _walk_or_gap(ws, exclude=set(), since=started_at)
            for p in walked[:200]:
                if p.suffix.lower() not in _WEB_SOURCE_EXT:
                    continue
                try:
                    code = _web_code_only(p.read_text(encoding="utf-8", errors="replace"))
                    found = sorted({m.group(0) for m in _AUTOMATION_DETECT_RE.finditer(code)})
                except OSError:
                    continue
                if found:
                    hits.append(f"{p.name} detects automated browsers ({', '.join(found)})")
            if hits:
                item.satisfied = False
                item.detail = (
                    "; ".join(hits)
                    + "; remove the detection: the page must behave the same for a person and a verifier"
                )[:400]
            elif gap:
                item.satisfied, item.detail = False, gap
        out.append(item)
    return out


def verify_command(response_text: str) -> str:
    """The ``VERIFY:`` command the reply declares, or '' when it declares none."""
    matches = _FINISH_VERIFY_RE.findall(str(response_text or ""))
    return matches[-1].strip() if matches else ""


def with_finish_items(items: Sequence[ContractItem], response_text: str) -> list[ContractItem]:
    """The reply's own finish declaration as a contract item: its VERIFY command is a check the harness runs (NOOA's
    typed TaskResult made executable). A reply that declares none is not a finish."""
    out = [it for it in items if it.kind != KIND_FINISH]
    command = verify_command(response_text)
    out.append(
        ContractItem(
            item_id="finish:verify",
            kind=KIND_FINISH,
            description="The reply ends with `VERIFY: <command>` and that command exits 0 in the workspace.",
            source="reply",
            target=command,
        )
    )
    return out


def needs_finish(items: Sequence[ContractItem]) -> bool:
    """A finish declaration is demanded only when the task named something checkable
    (an output, a data file, a command) - never for a turn that is judgement alone."""
    return any(it.kind in {KIND_DATA_FIELD, KIND_OUTPUT_PATH, KIND_COMMAND} for it in items)


def is_trivial(items: Sequence[ContractItem]) -> bool:
    """True when the task named nothing to hold it to (only the workspace's own
    checks remain: the parse check and the honest-page check)."""
    return all(it.kind in {KIND_COMPILES, KIND_HONEST_PAGE} for it in items)


def contract_verdict(items: Sequence[ContractItem]) -> ContractVerdict:
    unmet = tuple(it.item_id for it in items if it.checked and not it.satisfied)
    unchecked = tuple(it.item_id for it in items if not it.checked)
    return ContractVerdict(met=not unmet, unmet=unmet, unchecked=unchecked)


# ── text for the model and the reader ───────────────────────────────


def contract_prompt_block(items: Sequence[ContractItem], *, require_finish: bool = False) -> str:
    """Put in front of the model before work: the list it will be held to."""
    if not items:
        return ""
    lines = [
        "--- Acceptance Contract ---",
        "You are done only when every item below holds. The machine-checked items are verified from the",
        "workspace after you finish; words in your reply do not satisfy them. Grading is strict and automated.",
    ]
    for it in items:
        tag = "check" if it.machine else "judge"
        lines.append(f"- [{tag}] {it.description}")
    if require_finish:
        lines.append(FINISH_INSTRUCTION)
    lines.append("--- End Acceptance Contract ---")
    return "\n".join(lines)


def remediation_prompt(items: Sequence[ContractItem]) -> str:
    unmet = [it for it in items if it.checked and not it.satisfied]
    if not unmet:
        return ""
    lines = ["Acceptance contract not met. Continue working now and fix these before finalizing:"]
    for it in unmet:
        lines.append(f"- {it.description} (observed: {it.detail or 'unmet'})")
    lines.append("Finish only after every item above holds in the workspace.")
    return "\n".join(lines)


def verification_trailer(items: Sequence[ContractItem]) -> str:
    """What was checked, what failed, what nobody checked - appended to the reply."""
    if not items:
        return ""
    verdict = contract_verdict(items)
    checked = [it for it in items if it.checked]
    passed = sum(1 for it in checked if it.satisfied)
    lines = [f"Verification: {passed}/{len(checked)} checks passed."]
    for it in items:
        if it.checked and not it.satisfied:
            lines.append(f"- FAILED: {it.description} ({it.detail})")
    if verdict.unchecked:
        lines.append("Unchecked (no evidence either way):")
        for it in items:
            if not it.checked:
                lines.append(f"- {it.description}")
    return "\n".join(lines)


def items_to_dicts(items: Sequence[ContractItem]) -> list[dict[str, Any]]:
    return [it.to_dict() for it in items]


def items_from_dicts(rows: Sequence[dict[str, Any]] | None) -> list[ContractItem]:
    return [ContractItem.from_dict(r) for r in (rows or []) if isinstance(r, dict)]


def now() -> float:
    return time.time()


__all__ = [
    "ContractItem",
    "ContractVerdict",
    "KIND_COMMAND",
    "KIND_COMPILES",
    "KIND_HONEST_PAGE",
    "KIND_DATA_FIELD",
    "KIND_LEARNED",
    "KIND_OUTPUT_PATH",
    "KIND_REQUIREMENT",
    "MACHINE_KINDS",
    "FLAG",
    "build_contract",
    "contract_enabled",
    "contract_prompt_block",
    "contract_verdict",
    "declared_unused",
    "default_runner",
    "evaluate_contract",
    "items_from_dicts",
    "items_to_dicts",
    "now",
    "remediation_prompt",
    "requirement_statements",
    "verification_trailer",
]
