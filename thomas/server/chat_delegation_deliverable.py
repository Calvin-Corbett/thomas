"""Deliverable-manifest helpers for the background-worker delegation path.

Extracted from ``chat_delegation`` to keep that module under the architecture
size budget. This is the cohesive "what did the worker actually produce, and is
the claim honest?" unit: workspace file snapshots, the file-claim regex/allowlist,
the result-summary builder, the conversation handoff block, and the per-attempt
``_resolve_created`` reconciliation used by both worker terminal exits.

These names are re-exported from ``chat_delegation`` so existing imports (and the
tests) continue to resolve unchanged.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _snapshot_workspace_files(work_dir: Path | None, *, limit: int = 24) -> list[str]:
    """List the deliverable files the worker actually wrote to its workspace.

    Sourced from DISK (not the worker's claims), so the result reported to chat
    names only files that really exist — closing the "card says done but the file
    isn't there" gap. Returns workspace-relative POSIX paths; directories and
    dot/hidden files are excluded.
    """
    if work_dir is None:
        return []
    base = Path(work_dir)
    if not base.exists() or not base.is_dir():
        return []
    files: list[str] = []
    try:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base)
            if any(part.startswith(".") for part in rel.parts):
                continue
            files.append(rel.as_posix())
            if len(files) >= limit:
                break
    except (OSError, RuntimeError, ValueError) as exc:
        # Best-effort: a snapshot failure must never sink an otherwise-good result.
        log.debug("workspace snapshot error in %s: %s", work_dir, exc)
        return files
    return files


def _workspace_mtimes(
    work_dir: Path | None,
    *,
    ignored_prefixes: tuple[str, ...] = (),
    ignored_parts: frozenset[str] = frozenset(),
) -> dict[str, tuple[int, int]]:
    """Map of workspace-relative file -> (mtime_ns, size), for detecting files created
    OR modified during a given attempt — so a legitimately RE-WRITTEN same-name file
    still counts as this attempt's deliverable, while an untouched orphan from a failed
    prior attempt is excluded (its mtime AND size are unchanged). Pairing mtime with
    size also catches a same-second rewrite on coarse-mtime filesystems (FAT / some
    network mounts) where the size changes but the second-resolution mtime does not."""
    out: dict[str, tuple[int, int]] = {}
    if work_dir is None:
        return out
    base = Path(work_dir)
    if not base.exists() or not base.is_dir():
        return out
    normalized_prefixes = tuple(str(prefix or "").replace("\\", "/").lstrip("/") for prefix in ignored_prefixes)

    def _ignored_rel(rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel:
            return False
        if any(part in ignored_parts for part in rel.split("/")):
            return True
        return any(rel.startswith(prefix) for prefix in normalized_prefixes if prefix)

    try:
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            try:
                rel_root = "" if root_path == base else root_path.relative_to(base).as_posix().rstrip("/") + "/"
            except ValueError:
                continue
            dirs[:] = [
                dirname
                for dirname in dirs
                if not dirname.startswith(".")
                and dirname not in ignored_parts
                and not _ignored_rel(rel_root + dirname + "/")
            ]
            for filename in files:
                if filename.startswith("."):
                    continue
                path = root_path / filename
                rel = path.relative_to(base)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                rel_posix = rel.as_posix()
                if _ignored_rel(rel_posix):
                    continue
                try:
                    st = path.stat()
                    out[rel_posix] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    continue
    except (OSError, RuntimeError, ValueError) as exc:
        log.debug("workspace mtimes walk error in %s: %s", work_dir, exc)
        return out
    return out


def _files_changed_since(work_dir: Path | None, baseline: dict[str, tuple[int, int]], *, limit: int = 24) -> list[str]:
    """Files created OR modified since the baseline (mtime, size) snapshot (sorted, capped)."""
    after = _workspace_mtimes(work_dir)
    return sorted(f for f, m in after.items() if baseline.get(f) != m)[:limit]


# Real file extensions recognized in a creation claim. An ALLOWLIST (not "any
# letter-led suffix") so dotted abbreviations and version labels — U.S., e.g., i.e.,
# I.R.S., v3.x, "the U.S. market", 2.B0, 4.b — never read as filenames. All entries
# are >=2 chars on purpose: single-letter extensions (c/r/h) would re-admit dotted
# initialisms like "I.R.S." (".R" = the R-language ext). Missing a rare .c file claim
# is a benign false-negative; hedging a valid answer is the costly direction we avoid.
_FILE_EXTENSIONS = (
    "json",
    "jsonl",
    "py",
    "pyi",
    "txt",
    "text",
    "md",
    "markdown",
    "rst",
    "html",
    "htm",
    "css",
    "scss",
    "sass",
    "js",
    "mjs",
    "cjs",
    "ts",
    "tsx",
    "jsx",
    "vue",
    "csv",
    "tsv",
    "pdf",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "xml",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "svg",
    "webp",
    "ico",
    "bmp",
    "sh",
    "bash",
    "bat",
    "ps1",
    "sql",
    "log",
    "zip",
    "tar",
    "gz",
    "tgz",
    "docx",
    "xlsx",
    "pptx",
    "doc",
    "xls",
    "ppt",
    "rtf",
    "odt",
    "env",
    "lock",
    "rs",
    "go",
    "java",
    "cpp",
    "cc",
    "hpp",
    "rb",
    "php",
    "swift",
    "kt",
    "kts",
    "scala",
    "ipynb",
    "lua",
    "dart",
)
_EXT_ALT = "|".join(_FILE_EXTENSIONS)

# Capitalized JS/TS framework names: ".js"/".ts" IS a real extension but these are NOT
# file claims. Matched case-insensitively on the whole dotted token, so a genuine
# lowercase 'app.js' / 'index.ts' deliverable still registers as a file claim.
_TECH_NAME_TOKENS = frozenset(
    {
        "node.js",
        "react.js",
        "vue.js",
        "next.js",
        "nuxt.js",
        "express.js",
        "nest.js",
        "three.js",
        "ember.js",
        "backbone.js",
        "d3.js",
        "chart.js",
        "discord.js",
        "angular.js",
        "knockout.js",
        "meteor.js",
        "socket.js",
        "next.ts",
        "node.ts",
    }
)

# A filename-shaped token: a stem CONTAINING a letter + an allowlisted extension.
_FILENAME_RE = re.compile(
    r"\b([A-Za-z0-9_\-]*[A-Za-z][A-Za-z0-9_\-]*\.(?:" + _EXT_ALT + r"))\b",
    re.I,
)
# A creation verb within 60 chars of either a real filename (captured) or an explicit
# file/folder/directory word.
_FILE_CLAIM_RE = re.compile(
    r"\b(?:creat|wrote|writ|saved|generat|built|made|added)\w*\b.{0,60}?"
    r"(?:(?P<fname>[A-Za-z0-9_\-]*[A-Za-z][A-Za-z0-9_\-]*\.(?:" + _EXT_ALT + r"))\b"
    r"|\bfiles?\b|\bfolders?\b|\bdirector)",
    re.I | re.S,
)


def _claimed_filenames(text: str) -> set[str]:
    """Basenames of real files the text names (allowlisted extension; tech-framework
    names excluded). Used by the cross-attempt on-disk fallback to accept only files
    whose name matches what the worker actually claimed — never an unrelated orphan."""
    return {m.group(1) for m in _FILENAME_RE.finditer(str(text or "")) if m.group(1).lower() not in _TECH_NAME_TOKENS}


def _claims_file_creation(text: str) -> bool:
    """True if the text asserts it created/wrote/saved a real FILE or folder. Catches a
    worker that CLAIMS a deliverable the workspace lacks (anti-hallucination) without
    flagging benign prose ('built version 2.0', 'works in Node.js', 'as in the U.S.',
    'saved 99.9% accuracy')."""
    for m in _FILE_CLAIM_RE.finditer(str(text or "")):
        fname = m.group("fname")
        if fname is None:  # matched a file/folder/directory word, not a filename
            return True
        if fname.lower() not in _TECH_NAME_TOKENS:
            return True
    return False


# Past-tense completion verbs for SIDE-EFFECTING actions (not file creation, which
# has its own on-disk guard). A worker that says it "sent" / "deployed" / "deleted"
# something is asserting an external outcome we have no on-disk way to verify — so
# unless the worker's tool actually succeeded, the claim must be hedged, not echoed
# as fact. This is the action-verb analogue of the file-claim guard, and the fix for
# "Email sent successfully" surfacing while Gmail was never connected.
_ACTION_CLAIM_RE = re.compile(
    r"\b(?:sent|delivered|emailed|messaged|texted|deleted|removed|deployed|shipped|"
    r"published|posted|installed|uninstalled|connected|disconnected|configured|"
    r"scheduled|booked|ordered|purchased|bought|cancell?ed|merged|pushed|committed|"
    r"upgraded|migrated|downloaded|uploaded|enabled|disabled|provisioned|"
    r"submitted|registered|subscribed|unsubscribed|"
    # money / payment / banking
    r"transferred|transfer|wired|paid|charged|refunded|withdrew|withdrawn|deposited|"
    r"processed|reserved|"
    # destructive / ops
    r"wiped|erased|purged|dropped|rebooted|restarted)\b",
    re.I,
)
# Irreversible / high-stakes outcomes: money, bookings, destructive ops, deploys. A
# confident false claim here is the most dangerous thing a delegating assistant can do
# ("Payment processed", "money transferred", "table reserved", "deleted the database").
# These are NEVER stated as fact from a generic tool success — the chat layer cannot
# confirm the side-effect occurred, so they are always surfaced as unconfirmed.
_HIGH_STAKES_RE = re.compile(
    r"\b(?:transferred?|wired?|paid|payment|charge[ds]?|refund(?:ed)?|withdr(?:ew|awn|aw)|"
    r"deposit(?:ed)?|reserv(?:ed|ation)|booked|ordered|purchased?|bought|invoiced?|"
    r"deleted?|removed|wiped?|erased?|purged?|dropped|deployed?|shipped|published?|"
    r"migrated?|rebooted?|restarted?|cancell?ed|processed)\b",
    re.I,
)
# Maps an action keyword present in the claim to tool-name fragments that would make a
# success claim credible. Used to reject "an unrelated read_file proves the email sent".
_ACTION_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "email": ("mail", "email", "smtp", "gmail", "send"),
    "sent": ("mail", "email", "send", "message", "sms", "text", "slack", "telegram"),
    "deploy": ("deploy", "ship", "release", "publish", "vercel", "netlify"),
    "post": ("post", "publish", "http", "tweet", "slack"),
    "commit": ("git", "commit", "push"),
    "push": ("git", "push"),
    "install": ("install", "pip", "npm", "package", "apt"),
    "schedule": ("schedule", "cron", "calendar"),
    "book": ("book", "reserv", "order", "calendar"),
    "reserv": ("book", "reserv", "calendar"),
    "transfer": ("transfer", "bank", "pay", "wallet", "stripe", "plaid"),
    "pay": ("pay", "stripe", "charge", "transfer", "bank", "wallet"),
    "charge": ("charge", "stripe", "pay", "bank"),
}
_FAILURE_LANGUAGE_RE = re.compile(
    r"\b(?:could ?n'?t|cannot|can't|can ?not|unable|failed|fail|error|errored|"
    r"not connected|no(?:t)? (?:able|configured|set ?up|wired)|wasn'?t able|"
    r"was not able|blocked|denied|timed out|no result|couldn'?t confirm|"
    r"not (?:independently )?verified|unverified|unconfirmed)\b",
    re.I,
)
# Verification/state OUTCOME claims (distinct from action verbs): "all tests pass",
# "build green", "no errors". Same risk as action claims — an unverified outcome
# asserted as fact ("All tests pass") is exactly the kind of thing that must be tied
# to a real tool exit code, not echoed from the model's say-so.
_OUTCOME_CLAIM_RE = re.compile(
    r"\b(?:all tests? pass(?:ed|es)?|tests? pass(?:ed|es)?|test suite pass\w*|"
    r"all green|build (?:succeed\w*|passed|green|is green)|compiles? (?:clean|fine|ok)|"
    r"no errors|0 (?:errors|failures)|passes? all|all checks? pass\w*|it works)\b",
    re.I,
)


def _claims_action_success(text: str) -> bool:
    """True if the worker asserts a completed SIDE-EFFECTING action (sent/deployed/
    deleted/…) OR an unverified verification outcome (tests pass / build green) — and
    is NOT already phrasing it as a failure/uncertainty."""
    s = str(text or "")
    if _FAILURE_LANGUAGE_RE.search(s):
        return False
    return bool(_ACTION_CLAIM_RE.search(s) or _OUTCOME_CLAIM_RE.search(s))


def _has_action_or_outcome_claim(text: str) -> bool:
    """Whether the text asserts a side-effecting action or verification outcome ANYWHERE
    — independent of co-occurring failure language. (A success claim that sits next to an
    unrelated sub-step failure, e.g. 'I sent the email but the logo failed to attach',
    must still be detected so the success half is hedged, not echoed as fact.)"""
    s = str(text or "")
    return bool(_ACTION_CLAIM_RE.search(s) or _OUTCOME_CLAIM_RE.search(s) or _HIGH_STAKES_RE.search(s))


def _claim_sentence(text: str) -> str:
    """The first sentence/line that carries an action/outcome/file claim — so the surfaced
    line quotes the CLAIM ('I transferred $5000'), not a trailing sign-off."""
    for part in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")):
        s = " ".join(part.split())
        if s and (
            _ACTION_CLAIM_RE.search(s)
            or _OUTCOME_CLAIM_RE.search(s)
            or _HIGH_STAKES_RE.search(s)
            or _claims_file_creation(s)
        ):
            return s
    return _worker_summary_line([text])


def _tool_corresponds(succeeded_tools: list[str] | None, text: str) -> bool:
    """Whether a SUCCEEDED tool plausibly corresponds to the claimed action — so an
    unrelated `read_file` success cannot certify 'I sent the email and deployed to prod'."""
    t = str(text or "").lower()
    names = " ".join(str(x).lower() for x in (succeeded_tools or []))
    if not names:
        return False
    for keyword, hints in _ACTION_TOOL_HINTS.items():
        if keyword in t and any(h in names for h in hints):
            return True
    return False


def _cap(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _worker_summary_line(result_text_parts: list[str] | None) -> str:
    """The worker's FINAL one-line summary (last non-empty line) — the single source
    of truth for what the worker says it produced. Shared by M2 (claim detection) and
    M3 (result hedge) so they always agree on what counts as a claim (and neither scans
    the full chain-of-thought, which over-matches on discarded 'I could create…' musings).
    None-safe."""
    raw = "".join(str(p) for p in (result_text_parts or []) if p is not None).strip()
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return " ".join((lines[-1] if lines else raw).split())


def _build_result_summary(
    result_text_parts: list[str],
    tools_used: list[str],
    created_files: list[str] | None = None,
    *,
    succeeded_tools: list[str] | None = None,
    failed_tools: list[str] | None = None,
) -> str:
    """Condense a background worker's actual output into a result line for chat.

    Evidence hierarchy (most trustworthy first): verified on-disk files; the worker's
    own honest failure wording; an unverified FILE claim (hedged); an unverified
    ACTION claim like "email sent" (hedged unless a tool actually succeeded); a benign
    informational answer (passed through); else a status derived from real tool
    outcomes. This is the user-facing finished-task result, so it must NEVER assert an
    unverified success: a claim is only stated as fact when backed by a created file
    or a confirmed tool result. ``succeeded_tools``/``failed_tools`` are the real
    tool-outcome signals (ok / not-ok) the worker observed; when absent (e.g. unit
    tests), action claims are conservatively hedged.
    """
    created_files = [f for f in (created_files or []) if f]
    succeeded_tools = [t for t in (succeeded_tools or []) if t]
    failed_tools = [t for t in (failed_tools or []) if t]
    # The worker's FINAL one-line summary (not its full chain-of-thought) — None-safe.
    worker_line = _worker_summary_line(result_text_parts)

    if created_files:
        shown = created_files[:8]
        files_str = ", ".join(shown)
        if len(created_files) > len(shown):
            files_str += f" (+{len(created_files) - len(shown)} more)"
        base = f"Created {files_str}."
        summary = f"{base} {worker_line}" if (worker_line and not all(n in worker_line for n in shown)) else base
        return _cap(summary, 400)

    # Detect SIDE-EFFECTING / outcome claims across the WHOLE worker answer, not just the
    # last line — so a success claim followed by a friendly sign-off ("I transferred
    # $5000.\nLet me know!") is not erased, and one sitting next to an unrelated sub-step
    # failure is still hedged. The action/outcome/high-stakes regexes are PAST-TENSE, so
    # they don't fire on discarded musings ("I could create a file…") the way a present-
    # tense file-claim scan would — file claims stay scoped to the final line below.
    full_text = " ".join(str(p) for p in (result_text_parts or []) if p is not None).strip()
    high_stakes = bool(_HIGH_STAKES_RE.search(full_text))

    if _has_action_or_outcome_claim(full_text):
        claim = _claim_sentence(full_text) or worker_line
        # A real tool failed -> never assert the success half as fact.
        if failed_tools:
            return _cap(
                f"A tool failed ({', '.join(failed_tools[:3])}) — could not confirm completion. Worker said: {claim}",
                440,
            )
        # Money / booking / destructive / deploy -> NEVER stated as fact from a generic
        # tool success; the chat layer cannot confirm the side-effect occurred.
        if high_stakes:
            return _cap(
                f"Worker claims: {claim} — NOT independently verified. Don't treat this as confirmed until you check.",
                460,
            )
        # Other actions: assert only when a CORRESPONDING tool actually succeeded.
        if succeeded_tools and _tool_corresponds(succeeded_tools, full_text):
            return _cap(claim, 360)
        return _cap(
            f"Worker reported: {claim} — not independently verified (no confirmed tool result for this action).",
            460,
        )

    if worker_line:
        # The worker already phrased a failure/uncertainty honestly -> pass it through.
        if _FAILURE_LANGUAGE_RE.search(worker_line):
            return _cap(worker_line, 300)
        # Unverified FILE-creation claim (final line) with an empty workspace -> hedge.
        if _claims_file_creation(worker_line):
            return _cap(f"Worker reported: {worker_line} — but no file was found in the workspace.", 400)
        # Benign informational answer -> pass through.
        return _cap(worker_line, 300)

    if failed_tools:
        return f"A tool failed ({', '.join(failed_tools[:3])}) — the task did not complete."
    if succeeded_tools:
        return f"Completed using: {', '.join(succeeded_tools[:5])}."
    if tools_used:
        # Tool(s) were invoked but no outcome was confirmed — do NOT assert "Done".
        return f"Ran {', '.join(tools_used[:5])}, but no result was confirmed."
    return "No actions were taken — nothing to report."


def executability_warning(work_dir: Path | None, created_files: list[str] | None) -> str:
    """Pre-flight check that a produced web app is actually runnable.

    Claude Code's signature discipline is "don't claim done on something you
    haven't seen run." Applied at the deliverable boundary: if this task produced
    an HTML app, verify the entry document is non-empty and every first-party asset
    it references exists. Returns a user-facing warning string when the app is not
    runnable (so the result reads "Created index.html ⚠ …may render blank: missing
    src/game.js" instead of a clean false "done"); empty string when there is no web
    deliverable, when it verifies clean, or on ANY verifier error — verification must
    never break the finalize path.
    """
    try:
        if work_dir is None:
            return ""
        files = [str(f) for f in (created_files or []) if str(f).strip()]
        htmls = [f for f in files if f.lower().endswith(".html")]
        if not htmls:
            return ""
        from thomas.server.deliverable_verify import verify_web_deliverable

        entry = next((f for f in htmls if Path(f).name.lower() == "index.html"), htmls[0])
        result = verify_web_deliverable(work_dir, entry=entry)
        if result.ok:
            return ""
        return " ⚠ Heads up: this app may not open correctly — " + "; ".join(result.problems[:3]) + "."
    except Exception:  # noqa: BLE001 — a verification fault must never break finalize
        return ""


_SKIP_MD_TO_PDF = {"readme.md", "license.md", "changelog.md", "contributing.md", "agents.md"}


def render_report_pdfs(work_dir: Path | None, created_files: list[str] | None) -> list[str]:
    """Render top-level Markdown report deliverables to readable PDFs.

    A user handed `report.md` sees raw `### headings` and `**bold**`; the readable
    artifact is a PDF. For every top-level report `.md` this task produced (skipping
    project boilerplate like README/LICENSE, and anything nested in a code project's
    subfolder), render a sibling `.pdf` and return the new workspace-relative paths to
    fold into the deliverable list. Best-effort: returns [] on any failure, never
    raises, and is BLOCKING (launches Chromium) — call OFF the event loop.
    """
    try:
        if work_dir is None:
            return []
        base = Path(work_dir)
        from thomas.server.deliverable_render import render_markdown_to_pdf

        new_pdfs: list[str] = []
        for rel in created_files or []:
            rel = str(rel or "").strip().replace("\\", "/")
            if not rel.lower().endswith(".md") or "/" in rel:  # top-level reports only
                continue
            if Path(rel).name.lower() in _SKIP_MD_TO_PDF:
                continue
            md_abs = base / rel
            pdf_abs = md_abs.with_suffix(".pdf")
            if pdf_abs.exists():  # the worker already produced a PDF — don't duplicate
                continue
            out = render_markdown_to_pdf(md_abs, pdf_abs)
            if out is not None and Path(out).is_file():
                new_pdfs.append(Path(out).name)
        return new_pdfs
    except Exception:  # noqa: BLE001 — rendering must never break finalize
        return []


def runtime_executability_warning(work_dir: Path | None, created_files: list[str] | None) -> str:
    """Headless smoke-load of a produced web app — the "open it and watch it run"
    check that catches JS crashes and blank renders the static check can't see.

    Gated by ``THOMAS_RUNTIME_VERIFY`` (off by default: it launches a browser, ~1-3s).
    Returns a warning when the app crashes on load or renders blank; empty string
    otherwise, when disabled, or on ANY error. This is BLOCKING (launches Chromium) —
    call it OFF the event loop (``await asyncio.to_thread(...)``).
    """
    try:
        import os

        if str(os.environ.get("THOMAS_RUNTIME_VERIFY", "")).strip().lower() not in ("1", "true", "yes", "on"):
            return ""
        if work_dir is None:
            return ""
        files = [str(f) for f in (created_files or []) if str(f).strip()]
        htmls = [f for f in files if f.lower().endswith(".html")]
        if not htmls:
            return ""
        from thomas.server.deliverable_runtime_verify import runtime_smoke_load

        entry = next((f for f in htmls if Path(f).name.lower() == "index.html"), htmls[0])
        r = runtime_smoke_load(work_dir, entry=entry)
        if r.ok or r.skipped:
            return ""
        return " ⚠ The app did not run cleanly when opened — " + (r.reason or "runtime check failed") + "."
    except Exception:  # noqa: BLE001 — runtime verification must never break finalize
        return ""


# Unambiguous follow-up phrases: these almost always reference an earlier turn and
# are not plausible as nouns inside a self-contained request.
_STRONG_FOLLOWUP_RE = re.compile(
    r"\b(make it|change it|update it|fix it|move it|resize it|do the same|the same|same as|"
    r"again|like (?:before|that|this|it)|as before|previous(?:ly)?|earlier|instead|"
    r"the one|the other)\b",
    re.IGNORECASE,
)
# Ambiguous verbs that ARE common nouns ("a continue button", "a redo function", "a
# tweak tool"): only count as follow-ups when they LEAD the prompt as a command, so a
# self-contained "build a continue button" doesn't falsely re-attach the handoff.
_LEADING_FOLLOWUP_RE = re.compile(
    r"^\s*(?:please\s+|now\s+|ok(?:ay)?,?\s+|can you\s+|could you\s+|go\s+)*"
    r"(continue|keep going|redo|tweak|adjust|revert)\b",
    re.IGNORECASE,
)
# A leading continuation adverb ("now"/"then"/"also"/"next") + a MODIFICATION verb is a
# follow-up that has no stated target ("now add a high score" — to WHAT?), so the worker
# needs the prior turn. This is distinct from a self-contained "add a dark mode toggle TO
# THE SITE" (no continuation adverb, target named). Fresh-build verbs (build/create/make/
# write) are deliberately EXCLUDED so "now build me a snake game" stays self-contained and
# the wrong-deliverable bleed cannot reopen.
_CONTINUATION_FOLLOWUP_RE = re.compile(
    r"^\s*(?:please\s+|ok(?:ay)?,?\s+|and\s+)*"
    r"(?:now|then|next|also|after(?:wards| that)?)\s+"
    r"(?:please\s+|can you\s+|could you\s+|go\s+|let'?s\s+)*"
    r"(add|include|remove|delete|append|change|increase|decrease|swap|replace|"
    r"put|move|resize|rename|drop|take out|adjust)\b",
    re.IGNORECASE,
)
# Bare pronouns are reliable ONLY in a very short prompt ("that one", "those"). In a
# longer request they are usually relative pronouns/determiners ("a script THAT sorts").
_BARE_REF_RE = re.compile(r"\b(it|that|this|these|those|them|the one)\b", re.IGNORECASE)
# Explicit reference to an item from a previously presented set/answer ("the second
# one but red", "give me another one") — cannot be built without the prior turn.
_LIST_REF_RE = re.compile(
    r"^\s*(?:please\s+|ok(?:ay)?,?\s+|and\s+|now\s+|can you\s+|could you\s+)*"
    r"(?:(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|next|last|other|previous)\s+one"
    r"|another\s+one|one\s+more|give\s+me\s+another|do\s+another|the\s+(?:other|previous|last|first|second)\b)",
    re.IGNORECASE,
)
# A bare attribute/visual EDIT with no new deliverable ("smaller", "make the text
# bigger", "use a different color") references the prior deliverable.
_EDIT_ATTR = (
    r"(?:smaller|bigger|larger|wider|narrower|taller|shorter|darker|lighter|brighter|bolder|"
    r"rounder|rounded|colou?r|font|size|spacing|margins?|paddings?|centered?|aligned?|"
    r"dark\s*mode|light\s*mode|background|opacity|contrast|theme)"
)
_BARE_EDIT_RE = re.compile(rf"^\s*(?:please\s+|now\s+|can you\s+|could you\s+)*{_EDIT_ATTR}\b", re.IGNORECASE)
_DEF_EDIT_RE = re.compile(
    rf"^\s*(?:please\s+|now\s+|can you\s+|could you\s+)*"
    rf"(?:make|set|change|turn|use|put|keep|paint|recolou?r)\s+"
    rf"(?:the|its?|that|this|a\s+different|another)\b[^.?!]*\b{_EDIT_ATTR}\b",
    re.IGNORECASE,
)
# A clearly self-contained NEW build ("make a quiz app that shows the same question
# twice") must NOT pull handoff even though it contains content words like "the same".
# Requires a build verb + "a/an" + a DELIVERABLE noun (within a few words).
_FRESH_BUILD_RE = re.compile(
    r"^\s*(?:please\s+|can you\s+|could you\s+|i(?:'?d| would)?\s+(?:like|want|need)\s+(?:you\s+to\s+)?)*"
    r"(?:make|build|create|write|generate|design|develop|code|implement|produce|draw|render|scaffold)\s+"
    r"(?:me\s+)?(?:a|an)\s+(?:\w+[\s-]+){0,3}"
    r"(?:app|application|game|page|website|site|webpage|web[\s-]*app|script|tool|dashboard|form|"
    r"component|widget|api|server|bot|landing[\s-]*page|report|document|spreadsheet|chart|graph|"
    r"diagram|slideshow|presentation|story|poem|essay|article|cli|extension|plugin|calculator|"
    r"timer|clock|quiz|survey|chatbot|portfolio|blog|store|shop|simulator|visuali[sz]er|tracker|"
    r"generator|editor|viewer|player|browser|terminal|notebook|wiki|forum|gallery|map)\b",
    re.IGNORECASE,
)


def prompt_needs_handoff(prompt: str) -> bool:
    """Whether the recent-conversation handoff should be attached to a worker task.

    The handoff exists to resolve *references* ("make it blue" — blue what?). But a
    SELF-CONTAINED request ("Build me a Pong web game") needs no prior context, and
    feeding it competing prior task-requests makes the worker build the WRONG thing:
    a "Build me a Pong game" task produced an earlier turn's starfield because the
    handoff carried that request verbatim (adversarial review 2026-06-17). So only
    attach the handoff when the prompt actually leans on earlier dialogue. A false
    negative (a real follow-up gets no context) is far cheaper than building the wrong
    deliverable — the worker then just builds the literal ask.
    """
    text = str(prompt or "").strip()
    if not text:
        return False
    # A clearly self-contained NEW build is self-contained even if it contains content
    # words ("the same", "again") — guard BEFORE the reference checks so the wrong-build
    # bleed cannot reopen. (List-references are a genuine follow-up, never suppressed.)
    if _FRESH_BUILD_RE.match(text) and not _LIST_REF_RE.match(text):
        return False
    if (
        _STRONG_FOLLOWUP_RE.search(text)
        or _LEADING_FOLLOWUP_RE.match(text)
        or _CONTINUATION_FOLLOWUP_RE.match(text)
        or _LIST_REF_RE.match(text)
        or _DEF_EDIT_RE.match(text)
        or _BARE_EDIT_RE.match(text)
    ):
        return True
    # A short, mostly-pronoun prompt ("that one", "those") is a reference; a long
    # descriptive request that merely contains "that"/"it" is self-contained.
    return len(text.split()) <= 5 and bool(_BARE_REF_RE.search(text))


def quality_tier_clause(effort: str, autonomy_level: int = 4) -> str:
    """Build-quality instruction for the worker, derived from the effort tier the user
    picked in the composer (Brisk/Diligent/Exhaustive -> cheap/optimal/max).

    QUICK suppresses the off-task scaffolding (tests, build scripts, quality-gate files)
    that bloats a simple deliverable and made a one-file game take minutes; THOROUGH
    allows supporting files. This is what ties the build-quality selector to actual
    worker behavior, not just iteration count. (2026-06-17.)

    Uses the RAW normalized level, not ``effective_effort``: the autonomy coupling
    promotes Brisk->Diligent at L4 for *pass count*, but the user's explicit "Quick"
    choice should still keep the build lean regardless of how autonomous Thomas is.
    """
    from thomas.core.token_economy import normalize_token_economy_level

    _ = autonomy_level  # build-leanness is intentionally decoupled from autonomy
    level = normalize_token_economy_level(effort)
    if level == "cheap":
        return (
            "BUILD QUALITY = QUICK. Produce ONLY the single deliverable the user asked for, "
            "as directly as possible — ideally one file. Do NOT create tests, build scripts, "
            "quality-gate files, CI config, linters, or any project scaffolding. Ship the "
            "smallest correct thing that fulfils the request."
        )
    if level == "max":
        return (
            "BUILD QUALITY = THOROUGH. Produce a polished, robust deliverable. You MAY add "
            "supporting files (tests, a short README, helper modules) when they materially "
            "improve the result — but do not invent unrelated tooling or gates."
        )
    return (
        "BUILD QUALITY = STANDARD. Produce a complete, working deliverable focused on exactly "
        "what the user asked for. Do not add build tooling, quality-gate scripts, or test "
        "harnesses unless the user explicitly requested them."
    )


def _handoff_block(recent_messages: list[dict[str, Any]] | None, *, limit: int = 6) -> str:
    """Curate the last few conversation turns into a context block for the worker.

    A worker spawned mid-conversation otherwise sees only the literal task string and
    can build the wrong thing (e.g. "make it blue" with no referent). This forwards
    just enough recent dialogue to resolve references, clearly marked as background.
    Gate with ``prompt_needs_handoff`` so a self-contained request is NOT polluted with
    prior task-requests it might build instead.
    """
    msgs = [m for m in (recent_messages or []) if isinstance(m, dict)]
    turns: list[str] = []
    for m in msgs[-limit:]:
        role = str(m.get("role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        content = " ".join(str(m.get("content") or "").split())
        if not content:
            continue
        who = "User" if role == "user" else "Thomas"
        if len(content) > 400:
            content = content[:397] + "..."
        turns.append(f"{who}: {content}")
    if not turns:
        return ""
    return (
        "For context, here is the recent conversation between the user and Thomas that "
        "led to this task. Use it ONLY to resolve references (what 'it'/'that' means); "
        "build exactly what the task asks, and do not reply to the user conversationally.\n"
        "--- recent conversation ---\n" + "\n".join(turns) + "\n--- end conversation ---"
    )


class _WorkerRetry(RuntimeError):
    """Internal signal: a worker attempt failed in a way max-autonomy may retry."""


class _WorkerFatal(RuntimeError):
    """Internal signal: a worker attempt failed in a way that is NOT worth retrying
    (deterministic denial / interruption) — fail immediately, don't burn the budget."""


def _resolve_created(
    work_dir: Path | None,
    attempt_baseline: dict[str, tuple[int, int]],
    result_text_parts: list[str],
    tools_used: list[str],
) -> list[str]:
    """The files THIS attempt produced, used by both terminal exits (done event and
    stream-end) so they never diverge.

    Primary signal is the mtime/size diff since the attempt baseline. If that is empty
    but the worker claims a file, fall back to on-disk files whose basename MATCHES the
    claim — so a real deliverable written by a prior L4 attempt is still reported, while
    an unrelated orphan from a failed attempt is NOT passed off as this result (which
    would defeat the anti-hallucination guard). When nothing matches and no tools ran,
    the claim is a hallucinated completion -> raise _WorkerRetry (L4 retry / honest fail).
    """
    created = _files_changed_since(work_dir, attempt_baseline)
    if created:
        return created
    worker_line = _worker_summary_line(result_text_parts)
    if not _claims_file_creation(worker_line):
        return created
    claimed = _claimed_filenames(worker_line)
    on_disk = _snapshot_workspace_files(work_dir)
    matched = [f for f in on_disk if Path(f).name in claimed] if claimed else []
    if matched:
        return matched
    if not tools_used:
        raise _WorkerRetry("claimed to create files but none were found in the workspace")
    return created


def _artifacts_from_created(created_files: list[str] | None) -> list[dict[str, Any]]:
    """Structured artifact records for the files this task produced — what the chat
    UI needs to render an open / reveal / download affordance instead of a bare text
    path. Attached to the execution's proof so ``proof.artifacts`` is no longer always
    empty (the gap behind "Created hello.txt with nothing to click")."""
    arts: list[dict[str, Any]] = []
    for rel in created_files or []:
        rel = str(rel or "").strip()
        if not rel:
            continue
        ext = Path(rel).suffix.lstrip(".").lower()
        arts.append(
            {
                "path": rel,
                "name": Path(rel).name,
                "type": ext or "file",
                "actions": ["open", "download"],
            }
        )
    return arts
