# thomas/tools/git_conflicts.py
"""
Feature 12 — Git Conflict Auto-Resolver (v5)

This version aims for what developers (aka "consumers") actually love:
- **Trust**: dry_run previews you can audit (diff + decision reasons + confidence).
- **Safety**: automatic backups + atomic writes + staging only when truly conflict-free.
- **Smarts that stay boring**: optional but *safe* structured merge for JSON when edits are disjoint.
- **Leverage Git's memory**: if `rerere` is enabled, we apply recorded resolutions first.

Tools (per spec):
- git.conflict_summary (no params)
- git.resolve_conflicts (strategy, file, dry_run)

Interface stays exactly the same. Extra value is delivered via additional output keys.
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import tomllib  # py3.11+ (read-only TOML parsing)
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

# ---------------------------------------------------------------------------
# Soft imports
# ---------------------------------------------------------------------------

try:
    from thomas.tools.shell import exec as shell_exec  # type: ignore
except Exception as e:  # pragma: no cover
    shell_exec = None  # type: ignore
    _SHELL_IMPORT_ERROR = e
else:
    _SHELL_IMPORT_ERROR = None

try:
    from thomas.tools import filesystem as tfs  # type: ignore
except Exception:
    tfs = None  # type: ignore


def _ensure_shell() -> None:
    if shell_exec is None:
        raise RuntimeError(
            "thomas.tools.shell.exec could not be imported. "
            f"Original error: {_SHELL_IMPORT_ERROR}"
        )


# ---------------------------------------------------------------------------
# Shell/Git helpers (tolerant to multiple exec shapes)
# ---------------------------------------------------------------------------

def _shell(cmd: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute a command using thomas.tools.shell.exec.

    Tolerates:
    - shell_exec(cmd_list)
    - shell_exec(cmd_list, cwd=...)
    - shell_exec({"cmd": [...], "cwd": ...})

    Normalizes to dict with: stdout, stderr, code, ok (plus any extra returned keys).
    """
    _ensure_shell()
    res: Any = None

    try:
        if cwd is not None:
            res = shell_exec(cmd, cwd=cwd)  # type: ignore
        else:
            res = shell_exec(cmd)  # type: ignore
    except TypeError:
        payload = {"cmd": cmd}
        if cwd is not None:
            payload["cwd"] = cwd
        res = shell_exec(payload)  # type: ignore

    if isinstance(res, dict):
        stdout = res.get("stdout", "")
        stderr = res.get("stderr", "")
        code = res.get("code", res.get("returncode", 0))
        ok = res.get("ok", int(code) == 0)
        return {"stdout": stdout or "", "stderr": stderr or "", "code": int(code), "ok": bool(ok), **res}

    return {"stdout": str(res) if res is not None else "", "stderr": "", "code": 0, "ok": True}


def _run_git(args: List[str], cwd: Optional[str]) -> Dict[str, Any]:
    res = _shell(["git", *args], cwd=cwd)
    code = res.get("code", res.get("returncode", 0))
    ok = res.get("ok", code == 0)
    if not ok:
        raise RuntimeError(
            "git command failed: git "
            + " ".join(args)
            + f"\ncode={code}\nstdout={res.get('stdout','')}\nstderr={res.get('stderr','')}"
        )
    return res


def _try_git(args: List[str], cwd: Optional[str]) -> Dict[str, Any]:
    """
    Like _run_git, but never raises. Consumers love "best effort" with warnings.
    """
    res = _shell(["git", *args], cwd=cwd)
    code = res.get("code", res.get("returncode", 0))
    ok = res.get("ok", code == 0)
    res["ok"] = bool(ok)
    res["code"] = int(code)
    return res


def _git_root() -> str:
    res = _run_git(["rev-parse", "--show-toplevel"], cwd=None)
    root = (res.get("stdout") or "").strip()
    if not root:
        raise RuntimeError("Not a git repository (git rev-parse returned empty).")
    return root


# ---------------------------------------------------------------------------
# File IO (best-effort encoding + binary detection + atomic write)
# ---------------------------------------------------------------------------

@dataclass
class _ReadResult:
    text: str
    encoding: str
    had_decode_errors: bool
    is_binary: bool
    raw: bytes


def _read_bytes(path: str) -> bytes:
    if tfs is not None and hasattr(tfs, "read_bytes"):
        return tfs.read_bytes(path)  # type: ignore
    with open(path, "rb") as f:
        return f.read()


def _write_bytes_atomic(path: str, data: bytes) -> None:
    """
    Atomic write: write to temp file in same directory, then os.replace.
    """
    dir_ = os.path.dirname(path) or "."
    base = os.path.basename(path)
    tmp = os.path.join(dir_, f".{base}.thomas_tmp_{uuid.uuid4().hex}")
    if tfs is not None and hasattr(tfs, "write_bytes"):
        tfs.write_bytes(tmp, data)  # type: ignore
    else:
        with open(tmp, "wb") as f:
            f.write(data)
    os.replace(tmp, path)


def _read_text_best_effort(path: str) -> _ReadResult:
    data = _read_bytes(path)
    if b"\x00" in data:
        return _ReadResult(text="", encoding="binary", had_decode_errors=True, is_binary=True, raw=data)

    for enc in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return _ReadResult(text=data.decode(enc), encoding=enc, had_decode_errors=False, is_binary=False, raw=data)
        except UnicodeDecodeError:
            continue

    return _ReadResult(text=data.decode("utf-8", errors="replace"), encoding="utf-8", had_decode_errors=True, is_binary=False, raw=data)


def _encode_text(text: str, encoding: str) -> bytes:
    enc = encoding if encoding in ("utf-8", "utf-8-sig", "utf-16", "latin-1") else "utf-8"
    return text.encode(enc, errors="replace")


def _detect_newline_style(raw: bytes) -> str:
    # If CRLF appears anywhere, we assume CRLF style
    return "\r\n" if b"\r\n" in raw else "\n"


# ---------------------------------------------------------------------------
# Backups (reversible writes)
# ---------------------------------------------------------------------------

def _new_run_id() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    return f"{ts}_{uuid.uuid4().hex[:10]}"


def _backup_dir(repo_root: str, run_id: str) -> str:
    return os.path.join(repo_root, ".thomas", "git_conflict_resolver", "backups", run_id)


def _backup_file(repo_root: str, run_id: str, rel_path: str, raw_bytes: bytes) -> str:
    dest = os.path.join(_backup_dir(repo_root, run_id), rel_path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    _write_bytes_atomic(dest, raw_bytes)
    return dest


# ---------------------------------------------------------------------------
# Conflict parsing + heuristics
# ---------------------------------------------------------------------------

CONFLICT_START = "<<<<<<<"
CONFLICT_MID = "======="
CONFLICT_END = ">>>>>>>"

_WS_RE = re.compile(r"\s+", re.MULTILINE)

_BLOCK_OPEN = ("/*", "<!--")
_BLOCK_CLOSE = ("*/", "-->")

_EXT_LINE_COMMENTS: Dict[str, Tuple[str, ...]] = {
    ".py": ("#",),
    ".sh": ("#",),
    ".bash": ("#",),
    ".zsh": ("#",),
    ".yml": ("#",),
    ".yaml": ("#",),
    ".toml": ("#",),
    ".ini": (";", "#"),
    ".cfg": (";", "#"),
    ".js": ("//",),
    ".ts": ("//",),
    ".jsx": ("//",),
    ".tsx": ("//",),
    ".java": ("//",),
    ".c": ("//",),
    ".cc": ("//",),
    ".cpp": ("//",),
    ".h": ("//",),
    ".hpp": ("//",),
    ".cs": ("//",),
    ".go": ("//",),
    ".rs": ("//",),
    ".sql": ("--",),
    ".html": ("<!--",),
    ".xml": ("<!--",),
    ".md": ("<!--", "#"),
    ".json": ("//", "#"),  # jsonc-ish; real json has no comments but keeps heuristic conservative
}

_FALLBACK_LINE_PREFIXES = ("#", "//", "--", ";", "*")


def _strip_all_ws(s: str) -> str:
    return _WS_RE.sub("", s or "")


def _is_effectively_empty(s: str) -> bool:
    return (s or "").strip() == ""


def _line_comment_prefixes_for_path(path: str) -> Tuple[str, ...]:
    ext = os.path.splitext(path)[1].lower()
    return _EXT_LINE_COMMENTS.get(ext, _FALLBACK_LINE_PREFIXES)


def _is_line_comment(line: str, prefixes: Tuple[str, ...]) -> bool:
    st = (line or "").lstrip()
    return any(st.startswith(p) for p in prefixes)


def _is_comment_only_block(block: str, prefixes: Tuple[str, ...]) -> bool:
    for ln in (block or "").splitlines():
        st = ln.strip()
        if not st:
            continue
        if any(st.startswith(p) for p in prefixes):
            continue
        if any(st.startswith(p) for p in _BLOCK_OPEN):
            continue
        return False
    return True


@dataclass
class Conflict:
    ours: str
    theirs: str
    start_line: int
    end_line: int  # inclusive
    head_marker: str
    tail_marker: str


def _parse_conflicts_with_recovery(text: str) -> Tuple[List[Conflict], List[str]]:
    """
    Parses all conflict blocks while attempting recovery on malformed ones.
    """
    lines = text.splitlines(keepends=True)
    conflicts: List[Conflict] = []

    i = 0
    n = len(lines)

    while i < n:
        if not lines[i].startswith(CONFLICT_START):
            i += 1
            continue

        head_marker = lines[i].rstrip("\r\n")
        start_line = i
        mid = None
        end = None

        j = i + 1
        while j < n:
            if mid is None and lines[j].startswith(CONFLICT_MID):
                mid = j
            elif lines[j].startswith(CONFLICT_END):
                end = j
                break
            j += 1

        if end is None:
            conflicts.append(Conflict(ours="", theirs="", start_line=start_line, end_line=n - 1, head_marker=head_marker, tail_marker=""))
            break

        if mid is None or mid > end:
            ours = ""
            theirs = ""
        else:
            ours = "".join(lines[i + 1 : mid])
            theirs = "".join(lines[mid + 1 : end])

        tail_marker = lines[end].rstrip("\r\n")
        conflicts.append(Conflict(ours=ours, theirs=theirs, start_line=start_line, end_line=end, head_marker=head_marker, tail_marker=tail_marker))
        i = end + 1

    return conflicts, lines


def _has_conflict_markers(text: str) -> bool:
    return (CONFLICT_START in text) and (CONFLICT_MID in text) and (CONFLICT_END in text)


def _fallback_conflict_count(text: str) -> int:
    return text.count(CONFLICT_START)


def _nearest_nonempty_line(lines: List[str], start: int, direction: int) -> Optional[str]:
    i = start
    while 0 <= i < len(lines):
        s = lines[i].strip("\r\n")
        if s.strip() != "":
            return s
        i += direction
    return None


def _in_block_comment_before(lines: List[str], line_index: int, cap: int = 20000) -> bool:
    in_block = False
    limit = min(line_index, cap)
    for i in range(limit):
        ln = lines[i]
        for close in _BLOCK_CLOSE:
            if close in ln:
                in_block = False
        for open_ in _BLOCK_OPEN:
            if open_ in ln:
                closes_same = any((close in ln) and (ln.index(close) > ln.index(open_)) for close in _BLOCK_CLOSE if close in ln)
                if not closes_same:
                    in_block = True
    return in_block


def _is_conflict_in_comment_context(lines: List[str], c: Conflict, prefixes: Tuple[str, ...]) -> bool:
    if _in_block_comment_before(lines, c.start_line):
        return True
    prev_line = _nearest_nonempty_line(lines, c.start_line - 1, -1)
    next_line = _nearest_nonempty_line(lines, c.end_line + 1, +1)
    if prev_line is not None and next_line is not None:
        if _is_line_comment(prev_line, prefixes) and _is_line_comment(next_line, prefixes):
            return True
    if _is_comment_only_block(c.ours, prefixes) or _is_comment_only_block(c.theirs, prefixes):
        return True
    return False


# ---------------------------------------------------------------------------
# Structured JSON 3-way merge (safe, disjoint-only)
# ---------------------------------------------------------------------------

_MISSING = object()
JSONType = Union[dict, list, str, int, float, bool, None]


def _git_show_index_stage(repo_root: str, stage: int, rel_path: str) -> Optional[str]:
    """
    Returns file content for an unmerged index stage:
      1=base, 2=ours, 3=theirs
    """
    spec = f":{stage}:{rel_path}"
    res = _try_git(["show", spec], cwd=repo_root)
    if not res.get("ok"):
        return None
    return (res.get("stdout") or "")


def _json_normalize(s: str) -> Any:
    return json.loads(s)


def _json_merge3(base: Any, ours: Any, theirs: Any, path: Tuple[str, ...] = ()) -> Tuple[Any, List[Tuple[str, ...]]]:
    """
    Returns (merged_value, conflict_paths). Conflict paths are tuples of key segments.
    Rules (safe disjoint merge):
    - If ours == theirs -> take ours
    - If ours == base -> take theirs
    - If theirs == base -> take ours
    - Dicts: merge keys recursively; conflicts if both changed same key differently.
    - Lists: only merge if rules above apply; otherwise conflict (lists are order-sensitive).
    - Scalars: conflict if both differ from base and differ from each other.
    """
    if ours == theirs:
        return ours, []
    if ours == base:
        return theirs, []
    if theirs == base:
        return ours, []

    # dict merge
    if isinstance(base, dict) or isinstance(ours, dict) or isinstance(theirs, dict):
        b = base if isinstance(base, dict) else {}
        o = ours if isinstance(ours, dict) else {}
        t = theirs if isinstance(theirs, dict) else {}
        merged: Dict[str, Any] = {}

        conflicts: List[Tuple[str, ...]] = []

        # preserve base key order first, then ours-only, then theirs-only
        seen = set()
        key_order: List[str] = list(b.keys()) + [k for k in o.keys() if k not in b] + [k for k in t.keys() if k not in b and k not in o]

        for k in key_order:
            if k in seen:
                continue
            seen.add(k)
            bv = b.get(k, _MISSING)
            ov = o.get(k, _MISSING)
            tv = t.get(k, _MISSING)

            # handle missing cases
            if ov is _MISSING and tv is _MISSING:
                continue
            if ov is _MISSING and bv is _MISSING:
                # added only in theirs
                merged[k] = tv
                continue
            if tv is _MISSING and bv is _MISSING:
                merged[k] = ov
                continue

            # normalize missing to actual None? keep sentinel logic
            if bv is _MISSING:
                # key added in base? no; but exists in at least one side
                if ov is _MISSING:
                    merged[k] = tv
                    continue
                if tv is _MISSING:
                    merged[k] = ov
                    continue
                # both added
                if ov == tv:
                    merged[k] = ov
                else:
                    conflicts.append(path + (k,))
                continue

            # bv exists
            if ov is _MISSING:
                ov_eff = _MISSING
            else:
                ov_eff = ov
            if tv is _MISSING:
                tv_eff = _MISSING
            else:
                tv_eff = tv

            # deletions
            if ov_eff is _MISSING and tv_eff is _MISSING:
                # both deleted
                continue
            if ov_eff is _MISSING:
                # ours deleted
                if tv_eff == bv:
                    # theirs unchanged -> delete
                    continue
                # conflict: ours deleted, theirs changed
                conflicts.append(path + (k,))
                continue
            if tv_eff is _MISSING:
                if ov_eff == bv:
                    continue
                conflicts.append(path + (k,))
                continue

            merged_v, cpaths = _json_merge3(bv, ov_eff, tv_eff, path + (k,))
            if cpaths:
                conflicts.extend(cpaths)
            else:
                merged[k] = merged_v

        return merged, conflicts

    # list merge: only if one side equals base or both equal; otherwise conflict
    if isinstance(base, list) or isinstance(ours, list) or isinstance(theirs, list):
        return base, [path]  # conflict at this path

    # scalar conflict
    return base, [path]


def _json_structured_merge(repo_root: str, rel_path: str) -> Tuple[Optional[str], List[Tuple[str, ...]], str]:
    """
    Attempts a structured JSON 3-way merge using the index stages.
    Returns (merged_text_or_None, conflicts, reason)
    """
    base_s = _git_show_index_stage(repo_root, 1, rel_path)
    ours_s = _git_show_index_stage(repo_root, 2, rel_path)
    theirs_s = _git_show_index_stage(repo_root, 3, rel_path)
    if base_s is None or ours_s is None or theirs_s is None:
        return None, [], "no_index_stages"

    try:
        base = _json_normalize(base_s)
        ours = _json_normalize(ours_s)
        theirs = _json_normalize(theirs_s)
    except Exception:
        return None, [], "json_parse_failed"

    merged, conflicts = _json_merge3(base, ours, theirs, ())
    if conflicts:
        return None, conflicts, "structured_conflicts"

    # Preserve "style": if ours is minified, keep minified; else pretty.
    ours_minified = ("\n" not in ours_s) and ("\r" not in ours_s)
    if ours_minified:
        out = json.dumps(merged, separators=(",", ":"), ensure_ascii=False)
    else:
        out = json.dumps(merged, indent=2, ensure_ascii=False)
    return out, [], "structured_merged"


# ---------------------------------------------------------------------------
# Auto resolution heuristics (spec + safe extensions)
# ---------------------------------------------------------------------------

def _semantic_equal_json(ours: str, theirs: str) -> bool:
    try:
        return json.loads(ours) == json.loads(theirs)
    except Exception:
        return False


def _semantic_equal_toml(ours: str, theirs: str) -> bool:
    if tomllib is None:
        return False
    try:
        return tomllib.loads(ours) == tomllib.loads(theirs)
    except Exception:
        return False


def _semantic_equal(ours: str, theirs: str, rel_path: str) -> bool:
    ext = os.path.splitext(rel_path)[1].lower()
    if ext == ".json":
        return _semantic_equal_json(ours, theirs)
    if ext == ".toml":
        return _semantic_equal_toml(ours, theirs)
    return False


def _confidence_for_reason(reason: str) -> float:
    return {
        "ours_empty_take_theirs": 0.98,
        "theirs_empty_take_ours": 0.98,
        "identical_deduplicate": 0.99,
        "semantic_identical_deduplicate": 0.95,
        "comment_context_take_ours": 0.90,
        "whitespace_only_take_ours": 0.92,
        "structured_json_merged": 0.93,
        "already_clean_stage": 0.90,
        "needs_manual": 0.0,
        "forced_ours": 0.90,
        "forced_theirs": 0.90,
        "manual": 0.0,
    }.get(reason, 0.5)


def _decide_auto_resolution(ours: str, theirs: str, in_comment_ctx: bool, rel_path: str) -> Tuple[Optional[str], str]:
    if _is_effectively_empty(ours) and not _is_effectively_empty(theirs):
        return theirs, "ours_empty_take_theirs"
    if _is_effectively_empty(theirs) and not _is_effectively_empty(ours):
        return ours, "theirs_empty_take_ours"

    if ours == theirs:
        return ours, "identical_deduplicate"

    if _semantic_equal(ours, theirs, rel_path=rel_path):
        return ours, "semantic_identical_deduplicate"

    if in_comment_ctx:
        return ours, "comment_context_take_ours"

    if _strip_all_ws(ours) == _strip_all_ws(theirs):
        return ours, "whitespace_only_take_ours"

    return None, "needs_manual"


@dataclass
class Decision:
    conflict_index: int
    chosen_side: Optional[str]  # "ours" | "theirs" | None
    reason: str
    confidence: float
    start_line: Optional[int]
    end_line: Optional[int]


def _apply_marker_based_resolution(
    text: str,
    strategy: str,
    rel_path: str,
) -> Tuple[str, int, int, List[Dict[str, str]], List[Decision]]:
    conflicts, lines = _parse_conflicts_with_recovery(text)
    if not conflicts:
        return text, 0, 0, [], []

    prefixes = _line_comment_prefixes_for_path(rel_path)

    out: List[str] = []
    cursor = 0
    unresolved: List[Dict[str, str]] = []
    decisions: List[Decision] = []
    unresolved_count = 0

    for idx, c in enumerate(conflicts):
        out.extend(lines[cursor : c.start_line])

        chosen: Optional[str] = None
        reason = ""

        if strategy == "ours":
            chosen = c.ours
            reason = "forced_ours"
        elif strategy == "theirs":
            chosen = c.theirs
            reason = "forced_theirs"
        elif strategy == "auto":
            in_comment_ctx = _is_conflict_in_comment_context(lines, c, prefixes)
            chosen, reason = _decide_auto_resolution(c.ours, c.theirs, in_comment_ctx=in_comment_ctx, rel_path=rel_path)
        elif strategy == "manual":
            chosen = None
            reason = "manual"
        else:
            chosen = None
            reason = "needs_manual"

        if chosen is None:
            out.extend(lines[c.start_line : c.end_line + 1])
            unresolved_count += 1
            unresolved.append({"ours": c.ours, "theirs": c.theirs})
            chosen_side = None
        else:
            out.append(chosen)
            chosen_side = "ours" if chosen == c.ours else ("theirs" if chosen == c.theirs else "ours")

        decisions.append(
            Decision(
                conflict_index=idx,
                chosen_side=chosen_side,
                reason=reason,
                confidence=_confidence_for_reason(reason),
                start_line=c.start_line,
                end_line=c.end_line,
            )
        )

        cursor = c.end_line + 1

    out.extend(lines[cursor:])
    return "".join(out), len(conflicts), unresolved_count, unresolved, decisions


# ---------------------------------------------------------------------------
# Diff preview + report builder (dry_run)
# ---------------------------------------------------------------------------

def _unified_diff(old: str, new: str, rel_path: str, max_lines: int = 2000) -> Tuple[str, bool]:
    if old == new:
        return "", False
    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(True),
            new.splitlines(True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )
    truncated = False
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines]
        truncated = True
    text = "\n".join(diff_lines)
    if truncated:
        text += f"\n\n... diff truncated to {max_lines} lines ...\n"
    return text, truncated


def _truncate(s: str, limit: int = 600) -> str:
    if s is None:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit] + "\n... (truncated) ...\n"


def _build_markdown_report(file_previews: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("# Git conflict resolver preview")
    lines.append("")
    for fp in file_previews:
        lines.append(f"## {fp['file']}")
        lines.append("")
        lines.append(f"- total_conflicts: {fp.get('total_conflicts')}")
        lines.append(f"- auto_resolved: {fp.get('auto_resolved')}")
        lines.append(f"- unresolved: {fp.get('unresolved')}")
        lines.append(f"- fully_resolved: {fp.get('fully_resolved')}")
        lines.append(f"- would_write: {fp.get('would_write')}")
        lines.append(f"- would_stage: {fp.get('would_stage')}")
        if fp.get("notes"):
            lines.append(f"- notes: {fp['notes']}")
        lines.append("")
        decs = fp.get("decisions", [])
        if decs:
            lines.append("| idx | reason | chosen | confidence |")
            lines.append("|---:|---|---|---:|")
            for d in decs:
                lines.append(f"| {d['conflict_index']} | {d['reason']} | {d.get('chosen') or ''} | {d.get('confidence',0):.2f} |")
            lines.append("")
        diff_txt = fp.get("diff") or ""
        if diff_txt:
            lines.append("```diff")
            lines.append(_truncate(diff_txt, 8000))
            lines.append("```")
            lines.append("")
    return "\n".join(lines)


def _normalize_relpath(p: str) -> str:
    return os.path.normcase(p.replace("\\", "/"))


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def conflict_summary() -> Dict[str, Any]:
    """
    Tool: git.conflict_summary
    No params.
    """
    root = _git_root()
    res = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=root)
    files = [ln.strip() for ln in (res.get("stdout") or "").splitlines() if ln.strip()]

    out_files: List[Dict[str, Any]] = []
    total_conflicts = 0

    for rel in files:
        abs_path = os.path.join(root, rel)
        try:
            rr = _read_text_best_effort(abs_path)
            if rr.is_binary:
                cnt = 0
                sample = None
            else:
                conflicts, _ = _parse_conflicts_with_recovery(rr.text)
                cnt = len(conflicts)
                if cnt == 0 and _has_conflict_markers(rr.text):
                    cnt = _fallback_conflict_count(rr.text)
                sample = None
                if conflicts:
                    sample = {"ours": _truncate(conflicts[0].ours, 200), "theirs": _truncate(conflicts[0].theirs, 200)}
        except Exception:
            cnt = 0
            sample = None

        entry = {"file": rel, "conflict_count": cnt}
        if sample is not None:
            entry["sample_conflict"] = sample
        out_files.append(entry)
        total_conflicts += cnt

    return {"total_files": len(files), "total_conflicts": total_conflicts, "conflicted_files": out_files}


def resolve_conflicts(
    strategy: str = "auto",
    file: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Tool: git.resolve_conflicts
    Parameters:
      - strategy: auto | ours | theirs | manual
      - file: optional single file path
      - dry_run: if true, no writes / no staging
    """
    strategy = (strategy or "auto").strip().lower()
    if strategy not in ("auto", "ours", "theirs", "manual"):
        raise ValueError("strategy must be one of: auto | ours | theirs | manual")

    root = _git_root()
    run_id = _new_run_id()
    warnings: List[str] = []

    res = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=root)
    conflicted = [ln.strip() for ln in (res.get("stdout") or "").splitlines() if ln.strip()]

    # Optional single-file targeting (abs or rel)
    if file:
        f_in = file.strip()
        if os.path.isabs(f_in):
            try:
                f_rel = os.path.relpath(f_in, root)
            except Exception:
                f_rel = f_in
        else:
            f_rel = f_in
        target_norm = _normalize_relpath(f_rel)
        conflicted = [p for p in conflicted if _normalize_relpath(p) == target_norm]

    # Backups map (only in non-dry-run) so we can rollback.
    backups: Dict[str, str] = {}

    # Consumers love that we leverage git rerere if enabled
    rerere_applied = False
    if (not dry_run) and conflicted:
        cfg = _try_git(["config", "--bool", "rerere.enabled"], cwd=root)
        enabled = (cfg.get("stdout") or "").strip().lower() == "true"
        if enabled:
            # Backup conflicted files before rerere touches anything
            for rel in conflicted:
                abs_path = os.path.join(root, rel)
                try:
                    rr = _read_text_best_effort(abs_path)
                    if not rr.is_binary:
                        backups.setdefault(rel, _backup_file(root, run_id, rel, rr.raw))
                except Exception:
                    # backup failures are warnings, not fatal
                    warnings.append(f"backup_failed_before_rerere: {rel}")
            rr_res = _try_git(["rerere"], cwd=root)
            if not rr_res.get("ok"):
                warnings.append("git_rerere_failed")
            else:
                rerere_applied = True

    resolved_files: List[str] = []
    needs_manual: List[Dict[str, Any]] = []
    staged_any = False
    file_previews: List[Dict[str, Any]] = []

    # Re-read current conflicted files list (rerere may have cleaned content, but index still unmerged)
    res2 = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=root)
    conflicted_now = [ln.strip() for ln in (res2.get("stdout") or "").splitlines() if ln.strip()]
    if file:
        conflicted_now = conflicted  # already filtered above

    for rel in conflicted_now:
        abs_path = os.path.join(root, rel)

        try:
            rr = _read_text_best_effort(abs_path)
        except Exception as e:
            needs_manual.append({"file": rel, "conflict_count": 0, "conflicts": [], "error": f"read_failed: {e}"})
            continue

        if rr.is_binary:
            needs_manual.append({"file": rel, "conflict_count": 0, "conflicts": [], "error": "binary_file"})
            continue

        original = rr.text
        newline = _detect_newline_style(rr.raw)

        # If rerere already removed markers (or user did), stage it (consumer-friendly)
        if not _has_conflict_markers(original):
            if dry_run:
                file_previews.append(
                    {
                        "file": rel,
                        "encoding": rr.encoding,
                        "decode_warnings": bool(rr.had_decode_errors),
                        "total_conflicts": 0,
                        "auto_resolved": 0,
                        "unresolved": 0,
                        "fully_resolved": True,
                        "would_write": False,
                        "would_stage": True,
                        "diff_truncated": False,
                        "diff": "",
                        "decisions": [{"conflict_index": 0, "reason": "already_clean_stage", "chosen": None, "confidence": _confidence_for_reason("already_clean_stage")}],
                        "notes": "file has no conflict markers; will stage as resolved",
                    }
                )
            else:
                _run_git(["add", rel], cwd=root)
                resolved_files.append(rel)
                staged_any = True
            continue

        if strategy == "manual":
            conflicts, _ = _parse_conflicts_with_recovery(original)
            if conflicts:
                needs_manual.append({"file": rel, "conflict_count": len(conflicts), "conflicts": [{"ours": c.ours, "theirs": c.theirs} for c in conflicts]})
            if dry_run:
                file_previews.append(
                    {
                        "file": rel,
                        "encoding": rr.encoding,
                        "decode_warnings": bool(rr.had_decode_errors),
                        "total_conflicts": len(conflicts),
                        "auto_resolved": 0,
                        "unresolved": len(conflicts),
                        "fully_resolved": False,
                        "would_write": False,
                        "would_stage": False,
                        "diff_truncated": False,
                        "diff": "",
                        "decisions": [{"conflict_index": i, "reason": "manual", "chosen": None, "confidence": 0.0} for i in range(len(conflicts))],
                    }
                )
            continue

        notes = ""
        # Outside-the-box, but safe: attempt structured JSON merge first (auto only)
        merged_json_text: Optional[str] = None
        structured_conflicts: List[Tuple[str, ...]] = []
        if strategy == "auto" and os.path.splitext(rel)[1].lower() == ".json":
            merged_json_text, structured_conflicts, sreason = _json_structured_merge(root, rel)
            if merged_json_text is not None:
                notes = "structured JSON 3-way merge applied (disjoint-only)"
            elif sreason == "structured_conflicts":
                notes = f"structured JSON merge found conflicts at paths: {['/'.join(p) or '<root>' for p in structured_conflicts][:10]}"
            elif sreason not in ("no_index_stages",):
                notes = f"structured JSON merge skipped: {sreason}"

        if merged_json_text is not None:
            # We have a full-file resolved text, bypass marker-based parsing
            new_text = merged_json_text.replace("\n", newline) + (newline if merged_json_text and not merged_json_text.endswith("\n") else "")
            total_conflicts = _fallback_conflict_count(original)  # best-effort count for reporting
            unresolved_count = 0
            unresolved_conflicts: List[Dict[str, str]] = []
            decisions = [Decision(conflict_index=0, chosen_side="ours", reason="structured_json_merged", confidence=_confidence_for_reason("structured_json_merged"), start_line=None, end_line=None)]
        else:
            new_text, total_conflicts, unresolved_count, unresolved_conflicts, decisions = _apply_marker_based_resolution(
                original, strategy=strategy, rel_path=rel
            )

        fully_resolved = (unresolved_count == 0) and not _has_conflict_markers(new_text)
        changed = new_text != original

        if unresolved_count > 0:
            needs_manual.append(
                {
                    "file": rel,
                    "conflict_count": unresolved_count,
                    "conflicts": unresolved_conflicts,
                    # extra niceties (optional)
                    "notes": notes,
                    "structured_conflict_paths": [["/".join(p) or "<root>"] for p in structured_conflicts[:20]] if structured_conflicts else [],
                }
            )

        if dry_run:
            diff_text, truncated = _unified_diff(original, new_text, rel_path=rel, max_lines=2000)
            file_previews.append(
                {
                    "file": rel,
                    "encoding": rr.encoding,
                    "decode_warnings": bool(rr.had_decode_errors),
                    "total_conflicts": total_conflicts,
                    "auto_resolved": int(total_conflicts - unresolved_count),
                    "unresolved": int(unresolved_count),
                    "fully_resolved": bool(fully_resolved),
                    "would_write": bool(changed),
                    "would_stage": bool(fully_resolved and total_conflicts > 0),
                    "diff_truncated": bool(truncated),
                    "diff": diff_text,
                    "notes": notes,
                    "decisions": [
                        {
                            "conflict_index": d.conflict_index,
                            "reason": d.reason,
                            "chosen": d.chosen_side,
                            "confidence": float(d.confidence),
                        }
                        for d in decisions
                    ],
                }
            )
            continue

        # Not dry_run: write + stage safely
        if changed and total_conflicts > 0:
            # Backup original before write (if not already backed up pre-rerere)
            backups.setdefault(rel, _backup_file(root, run_id, rel, rr.raw))
            _write_bytes_atomic(abs_path, _encode_text(new_text, rr.encoding))

        if fully_resolved and total_conflicts > 0:
            resolved_files.append(rel)
            _run_git(["add", rel], cwd=root)
            staged_any = True

    result: Dict[str, Any] = {
        "resolved": resolved_files,
        "needs_manual": needs_manual,
        "staged": bool(staged_any and not dry_run),
    }

    if dry_run:
        result["dry_run_preview"] = {"files": file_previews, "report_markdown": _build_markdown_report(file_previews)}
    else:
        if backups:
            result["backup_run_id"] = run_id
            result["backup_dir"] = _backup_dir(root, run_id)
            result["backed_up_files"] = [{"file": k, "backup_path": v} for k, v in backups.items()]
            result["rollback_instructions"] = (
                "To rollback: copy backup file over the working file and run `git add <file>` again. "
                "Backups are stored under .thomas/git_conflict_resolver/backups/<run_id>/..."
            )

    if rerere_applied:
        result["rerere_applied"] = True
    if warnings:
        result["warnings"] = warnings

    return result


# ---------------------------------------------------------------------------
# Tool specs / wiring
# ---------------------------------------------------------------------------

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "git.resolve_conflicts",
        "category": "git",
        "description": "Resolve git merge conflicts using auto heuristics or forced ours/theirs.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "description": "auto | ours | theirs | manual. Default: auto", "default": "auto"},
                "file": {"type": "string", "description": "Specific file path to resolve. Optional — all conflicted files if omitted."},
                "dry_run": {"type": "boolean", "description": "If true, show proposed resolutions without applying. Default: false", "default": False},
            },
            "additionalProperties": False,
        },
        "handler": resolve_conflicts,
    },
    {
        "name": "git.conflict_summary",
        "category": "git",
        "description": "Report how many conflicts exist and in which files.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": conflict_summary,
    },
]

TOOLS = TOOL_SPECS


def get_tools() -> List[Dict[str, Any]]:
    return TOOL_SPECS


def register(registry: Any) -> None:
    if hasattr(registry, "register"):
        for spec in TOOL_SPECS:
            registry.register(spec)
        return
    if hasattr(registry, "add_tool"):
        for spec in TOOL_SPECS:
            registry.add_tool(spec["name"], spec["handler"], spec)
        return
    if hasattr(registry, "tools") and isinstance(registry.tools, list):
        registry.tools.extend(TOOL_SPECS)
        return
    raise TypeError("Unsupported registry type; cannot register tools automatically.")


__all__ = [
    "resolve_conflicts",
    "conflict_summary",
    "TOOL_SPECS",
    "TOOLS",
    "get_tools",
    "register",
]
