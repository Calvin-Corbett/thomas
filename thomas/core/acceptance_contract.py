"""The acceptance contract: what "done" means, fixed before the work starts.

Built from the three sources a model is prone to skip: the task's own words
(every "must"/"every"/"all" sentence), the data files the task names (every field
in them is a feature the deliverable has to honour - the turnaround-time miss),
and the paths and commands the task says must exist or run. Items are either
machine-checkable (checked here, in the delivery environment) or judgement calls
(left to a separate evaluator, and always named as unchecked in the reply).

Pure core module: no agent/server imports. Callers supply the workspace, the
observed tool events, the produced text and a command runner.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

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
# The Minecraft build (2026-09-05) read navigator.webdriver and the user agent
# for Headless/Playwright/Puppeteer and never activated its renderer under
# automation: a HUD over a void for every verifier, a world for a person.
_AUTOMATION_DETECT_RE = re.compile(
    r"navigator\.webdriver|HeadlessChrome|\bPlaywright\b|\bPuppeteer\b|\bwebdriver\b|\bHeadless\b",
)
_WEB_SOURCE_EXT = frozenset({".js", ".mjs", ".ts", ".html", ".htm"})
# A comment that names the words is not detection: the scan reads code only.
_WEB_COMMENT_RE = re.compile(r"/\*.*?\*/|<!--.*?-->|^\s*//[^\n]*|(?<=[;{}\s])//[^\n]*", re.S | re.M)


def _web_code_only(text: str) -> str:
    return _WEB_COMMENT_RE.sub(" ", text)

FINISH_INSTRUCTION = (
    "A reply is not a finish. When the work is complete, end your reply with two lines: "
    "`EVIDENCE: <the actual output you observed that shows it works>` and "
    "`VERIFY: <one shell command that exits 0 only if the task is complete>`. The VERIFY command "
    "is run in the workspace after you reply; a reply without it, or whose command fails, is not finished."
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
_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache", ".ruff_cache"}
)
_MAX_SOURCE_FILES = 600
_MAX_SOURCE_BYTES = 2_000_000
_MAX_FIELDS_PER_FILE = 80
_MAX_FIELDS_TOTAL = 200
_MAX_REQUIREMENTS = 24  # a listed feature set is one item per feature; 12 cut a game spec in half

_PATH_TOKEN_RE = re.compile(r"(?<![\w.])((?:/|\./|~/)?(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8})(?::\d+)?")
_BARE_DATA_FILE_RE = re.compile(r"(?<![\w/.-])([\w-]+\.(?:json|csv|ya?ml|toml))\b", re.I)
_BACKTICK_FILE_RE = re.compile(r"`([\w.-]+\.[A-Za-z0-9]{1,8})`")
_BACKTICK_RE = re.compile(r"`([^`\n]{3,240})`")
_RUNNER_VERB_RE = re.compile(
    r"^(?:python3?|pytest|node|npm|npx|pnpm|yarn|bun|deno|go|cargo|make|bash|sh|java|dotnet|ruby|php|mvn|gradle)\b"
)
_DENY_COMMAND_RE = re.compile(r"\b(?:rm|sudo|curl|wget|mkfs|dd|chmod|chown|kill|shutdown|reboot)\b|>|\|\s*sh\b")
_REQUIREMENT_RE = re.compile(
    r"\b(?:must|should|every|all|each|exactly|deterministic|required|ensure|only"
    r"|needs?|need to|has to|have to|wants?|requires?|at least|includes?|including)\b",
    re.I,
)
# A requirement is what the user ASKS for. Two builds were sent back over
# sentences nobody could meet: a bug report ("So the human controls do not
# drive the karts.") chosen for its "do not", and the user's own narration
# ("Driving works on all four circuits now, I played each one...") chosen for
# its "all", while "Fix the keyboard driving..." and "Prove they work." were
# not requirements at all. Mood decides: an imperative addressed to Thomas is
# a requirement, narration is not, and "do not" counts only when it opens one.
_NARRATION_RE = re.compile(
    r"^(?:I|I've|I'd|I'm|So|With|Then|Earlier|Meanwhile|Here's|Before|After|Now|Today|Yesterday|Last time)\b"
    r"|\bI (?:played|tried|tested|ran|saw|noticed|found|checked|opened|clicked|pressed|drove|used|did|got|had)\b"
    r"|\b(?:the screen|the page|the hud|the results?|the timer|the console|it) (?:says|said|shows|showed|reads|read|reported)\b",
    re.I,
)
_WANT_RE = re.compile(r"\b(?:need|needs|want|wants|must|should|require|requires|expect|expects)\b", re.I)
_IMPERATIVE_RE = re.compile(
    r"^(?:please\s+)?(?:do not|don't|never|always|fix|prove|show|make|add|build|keep|use|play|ensure|write|create"
    r"|implement|remove|change|report|tell|give|run|test|verify|check|drive|include|return|produce|generate|render"
    r"|handle|support|avoid|stop|start|open|read|update|rename|move|delete|convert|install|document|explain|list"
    r"|compare|measure|count|sort|filter|validate|refactor|rewrite|replace|let|put|set|save|export|print|draw"
    r"|display|send|call|wire|hook|record|log|emit|serve|load|fetch|parse|compute|calculate|treat|prefer|only)\b",
    re.I,
)
_LEAD_CLAUSE_RE = re.compile(
    r"^(?:if|when|unless|once|whenever|after|before|otherwise)\b[^,;:]*[,;:]\s*(?P<rest>.+)$", re.I
)
_CLAUSE_SPLIT_RE = re.compile(r"[;:]\s+")
_PAST_LEAD_RE = re.compile(
    r"^(?:when|after|once|as|while)\s+I\s+(?:\w+ed|saw|ran|got|went|tried|hit|played|did|was|had)\b", re.I
)


def _is_requirement_sentence(sentence: str) -> bool:
    text = sentence.strip()
    # An instruction wins first: "Before you finish, run the tests" opens like
    # narration and is not.
    if _IMPERATIVE_RE.match(text):
        return True
    lead = _LEAD_CLAUSE_RE.match(text)
    if lead:
        # "When I enter a world it is only the HUD..., nothing renders": the
        # condition clause lends none of its words; the clause after it is
        # the sentence that is judged.
        if _IMPERATIVE_RE.match(lead.group("rest")):
            return True
        text = lead.group("rest").strip()
        # "When I opened it, it only showed the HUD": a first-person past-tense
        # condition is a report of what happened; only a stated want survives it.
        if _PAST_LEAD_RE.match(sentence.strip()):
            return bool(_WANT_RE.search(text))
    if any(_IMPERATIVE_RE.match(clause.strip()) for clause in _CLAUSE_SPLIT_RE.split(text)[1:]):
        return True
    if _NARRATION_RE.search(text) and not _WANT_RE.search(text):
        return False
    return bool(_REQUIREMENT_RE.search(text))
# A sentence that LISTS its needs ("It needs A (x, y), B, and C.") is one
# requirement per entry: the Mario Kart request stated nine features in one
# 440-character sentence and the contract dropped the whole thing, so a
# one-track demo met every item that was left. Split at top-level commas and
# semicolons only -- a parenthesised aside keeps its inner commas.
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


def _resolve(token: str, workspace: Path) -> Path | None:
    raw = token.strip()
    if raw.startswith("~/"):
        return Path(os.path.expanduser(raw))
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    direct = workspace / raw
    if direct.exists():
        return direct
    name = Path(raw).name
    try:
        for depth_glob in ("*", "*/*", "*/*/*"):
            for found in workspace.glob(depth_glob):
                if found.name == name and found.is_file():
                    return found
    except OSError:
        return direct
    return direct


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
    """One statement per listed need; the lead ("It needs") is kept on each so a
    fragment still reads as a requirement on its own. A sentence that is not a
    list comes back unchanged."""
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


def build_contract(
    prompt_text: str,
    workspace: str | Path,
    *,
    learned: Sequence[dict[str, Any]] = (),
) -> list[ContractItem]:
    """The acceptance list for a task, derived before any work is done."""

    ws = Path(workspace)
    text = str(prompt_text or "")
    items: list[ContractItem] = []
    seen_paths: set[str] = set()
    data_files: list[tuple[str, Path]] = []

    tokens = [m.group(1) for m in _PATH_TOKEN_RE.finditer(text)]
    tokens += [m.group(1) for m in _BARE_DATA_FILE_RE.finditer(text) if "/" not in m.group(1)]
    tokens += [m.group(1) for m in _BACKTICK_FILE_RE.finditer(text)]
    for token in tokens:
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
        if resolved.is_dir():
            continue
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
        if not _RUNNER_VERB_RE.match(span) or _DENY_COMMAND_RE.search(span):
            continue
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
    for sentence in _sentences(text):
        if len(sentence) < 12 or not _is_requirement_sentence(sentence):
            continue
        for statement in _requirement_statements(sentence):
            if count >= _MAX_REQUIREMENTS or len(statement) > 300:
                continue
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
        item.checked, item.satisfied, item.detail = False, False, ""
        # A standing goal is a requirement, not a check learned from a miss.
        if item.kind not in MACHINE_KINDS and not (item.source == "goal" and item.kind == KIND_REQUIREMENT):
            item.kind = KIND_LEARNED
        item.source = item.source or "learned"
        items.append(item)
    return items


# ── evaluating ──────────────────────────────────────────────────────


def default_runner(command: str, cwd: Path, timeout: float) -> tuple[int, str]:
    """Run a contract command where the user would: in the workspace, with a clock."""

    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {int(timeout)}s"
    except OSError as exc:
        return 127, str(exc)
    return int(proc.returncode), (proc.stdout + proc.stderr)[-1500:]


def _source_files(workspace: Path, *, exclude: set[Path], since: float | None = None) -> list[Path]:
    out: list[Path] = []
    try:
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
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
    sources = _source_files(ws, exclude=data_paths)
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
                item.detail = f"exit {code}" + (f": {tail.strip()[-300:]}" if code != 0 and tail.strip() else "")
            elif _command_observed(item.target, tool_events):
                item.checked, item.satisfied, item.detail = True, True, "observed succeeding in tool events"
            else:
                item.checked, item.satisfied, item.detail = True, False, "never observed running successfully"
        elif item.kind == KIND_FINISH:
            item.checked = True
            if not item.target:
                item.satisfied, item.detail = False, "the reply declares no VERIFY: command"
            elif _DENY_COMMAND_RE.search(item.target):
                item.satisfied, item.detail = False, "the VERIFY: command is not allowed to run"
            elif run_commands:
                code, tail = run(item.target, ws, command_timeout)
                item.satisfied = code == 0
                item.detail = f"exit {code}" + (f": {tail.strip()[-300:]}" if code != 0 and tail.strip() else "")
            else:
                item.satisfied, item.detail = _command_observed(item.target, tool_events), "from tool events"
        elif item.kind == KIND_COMPILES:
            changed = [p for p in _source_files(ws, exclude=set(), since=started_at) if p.suffix == ".py"]
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
        elif item.kind == KIND_HONEST_PAGE:
            item.checked, item.satisfied, item.detail = True, True, "no changed web source detects automation"
            hits: list[str] = []
            for p in _source_files(ws, exclude=set(), since=started_at)[:200]:
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
                item.detail = ("; ".join(hits) + "; remove the detection: the page must behave the same for a person and a verifier")[:400]
        out.append(item)
    return out


def verify_command(response_text: str) -> str:
    """The ``VERIFY:`` command the reply declares, or '' when it declares none."""

    matches = _FINISH_VERIFY_RE.findall(str(response_text or ""))
    return matches[-1].strip() if matches else ""


def with_finish_items(items: Sequence[ContractItem], response_text: str) -> list[ContractItem]:
    """The reply's own finish declaration as a contract item: its VERIFY command is a
    check the harness runs (NOOA's typed TaskResult made executable). A reply that
    declares none is not a finish."""

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
    "verification_trailer",
]
