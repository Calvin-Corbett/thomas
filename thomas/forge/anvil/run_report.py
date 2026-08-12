"""Structured post-run report builder for Code runs (CAP-141).

Assembles a five-section report dict from a run's REAL recorded data — the
forge-event transcript (``forge_event_stream`` JSON lines), the git-truth
changed-file list, and the recorded outcome — never from invented content:

* ``attempts``            — each edit pass (initial + engine fix passes): goal,
                            outcome, key actions, exit state.
* ``validations``         — each engine check the run actually executed
                            (``tool``/``run`` + its ``tool_result``): command,
                            pass/fail, evidence snippet.
* ``open_risks``          — honest gaps the run data itself shows: failing or
                            missing verification, surfaced errors, refusals,
                            files changed without a matching validation.
* ``attention_pointers``  — ranked file/artifact references a reviewer should
                            look at first (failure sites, then changed files).
* ``rubric_mapping``      — run outcome mapped onto the completion criteria the
                            run was given (goal text + any acceptance bullets).

A degenerate run (empty transcript, no changes) produces an honest minimal
report: empty sections plus a single "no activity recorded" risk — nothing is
ever fabricated to fill a section.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FIX_PASS_RE = re.compile(
    r"verification failed \(exit (?P<exit>-?\d+)\); fix pass (?P<i>\d+)/(?P<n>\d+)",
    re.IGNORECASE,
)
_FILE_LINE_RE = re.compile(r"(?P<ref>[\w][\w./\\-]*\.[A-Za-z]\w{0,7}:\d+)")
_CRITERION_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<text>\S.{3,})$")
# The engine's own skip marker (BROWSER_SMOKE_SKIPPED, and any future sibling).
# Matched on the marker rather than the word "skipped", which appears in
# unrelated evidence such as "1 files checked, 1 skipped".
_SKIPPED_EVIDENCE = re.compile(r"[A-Z][A-Z_]*_SKIPPED\b")
# The harness's own stand-in sentences for an error event that carried NO text.
# forge_event_stream falls back to "claude reported an error" when the CLI's
# is_error result had an empty message, and dispatch_agent_loop does the same
# with "agent loop reported an error" -- both are the translator's bookkeeping,
# not anything the run did or said. A risk row must trace to the run: measured
# on the 2026-08-05 audit, an explain-only run's card carried exactly two "open
# risks" and both were manufactured from one such injected no-op error (the
# stand-in sentence itself, plus the exit code that arrived with it). Matched
# whole, not as substrings, so an error whose real message merely CONTAINS one
# of these phrases is still surfaced.
_HARNESS_FALLBACK_ERROR_TEXTS = frozenset(
    {
        "claude reported an error",
        "agent loop reported an error",
    }
)

_SNIPPET_CHARS = 240
_MAX_ACTIONS_PER_ATTEMPT = 8
_MAX_RISKS = 12
_MAX_POINTERS = 10
_MAX_CRITERIA = 12


def parse_forge_events(transcript: str) -> list[dict[str, Any]]:
    """Parse the forge-event JSON lines out of a stored run transcript.

    Non-event lines (CLI echo, prose) are skipped; token-progressive ``say``
    deltas are skipped too — the complete text they duplicate is what matters
    for a post-run report. Defensive: a malformed line is skipped, never raised on.
    """
    events: list[dict[str, Any]] = []
    for raw in str(transcript or "").split("\n"):
        line = raw.strip()
        if not line or line[0] != "{":
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict) or not obj.get("fc"):
            continue
        if obj.get("delta") is True:
            continue
        events.append(obj)
    return events


def _flat(text: Any) -> str:
    """One-line text with NOTHING dropped — the whole recorded string."""

    return " ".join(str(text or "").split())


def _snippet(text: Any, limit: int = _SNIPPET_CHARS) -> str:
    """A DISPLAY-length excerpt. Never ask it a question about the run.

    ``_snippet`` is how every section fits into a card, and it is lossy by
    design. Deciding a fact from its output means deciding the fact from
    whatever happened to land inside the first ``limit`` characters — see
    ``_build_validations`` for the measured case where that invented a risk.
    """

    return _flat(text)[:limit]


def _segment_attempts(
    events: list[dict[str, Any]],
) -> tuple[list[list[dict[str, Any]]], list[re.Match[str]]]:
    """Split the event stream into per-pass segments at engine fix-pass markers."""
    segments: list[list[dict[str, Any]]] = [[]]
    markers: list[re.Match[str]] = []
    for event in events:
        match = _FIX_PASS_RE.search(str(event.get("text") or "")) if event.get("fc") == "meta" else None
        if match is not None:
            markers.append(match)
            segments.append([])
        else:
            segments[-1].append(event)
    return segments, markers


def _attempt_actions(segment: list[dict[str, Any]]) -> list[str]:
    """Key agent actions in one pass — its named tool activity, minus engine checks.

    Reads BOTH ``tool`` and ``tool_result``, and that is the whole point.

    This previously matched only ``fc == "tool"`` with a name other than ``run``,
    which cannot happen: measured across 105 agent turns, ``key_actions`` was
    non-empty ZERO times, while its siblings ``goal``, ``outcome`` and
    ``exit_state`` were populated 100% of the time. In the real stream every
    ``tool`` CALL is the engine's own ``run`` check; the agent's work arrives as
    NAMED ``tool_result`` events. Four runs, and the correspondence is exact::

        run             tool calls    tool_result   named   unnamed
        to-do           2 (all run)             6       4         2
        habits          2 (all run)             6       4         2
        call of duty    4 (all run)            62      58         4
        study planner   2 (all run)            27      25         2

    Unnamed results match ``run`` calls one-for-one every time, so "named" is a
    clean discriminator: ``fs.write_file``, ``diff.create``, ``code.search`` are
    the agent; the unnamed ones are check output. The Call of Duty run wrote
    three files and created three diffs and still reported no key actions.

    The unit fixture in tests/test_run_report.py emits
    ``{"fc":"tool","name":"Edit"}`` — a shape the engine never produces — so it
    passed throughout. Accepting either kind keeps that fixture meaningful and
    makes real runs populate; tests/test_the_report_says_what_thomas_did.py pins
    the real shape.

    KNOWN LIMITATION, not fixed here. The label is ``name: text``, and for
    ``fs.write_file`` that reads well (``Wrote 10807 chars to ...tasks.html``)
    but for ``fs.read_file`` the event's text is the FILE CONTENT, so the label
    becomes a line-numbered source fragment::

        fs.read_file: 250 white-space: nowrap; 251 border: 0; 252 } 253 </style>

    Accurate but not a summary. Left alone because the readable alternative is a
    per-tool formatter that guesses which part of each payload is the subject,
    and guessing there would trade an ugly true label for a tidy wrong one.
    Nothing renders this field today; whoever does should format per tool name.
    """

    actions: list[str] = []
    for event in segment:
        if str(event.get("fc") or "") not in ("tool", "tool_result"):
            continue
        name = str(event.get("name") or "").strip()
        # Unnamed => engine check output. `run` => the engine check call itself.
        if not name or name == "run":
            continue
        label = _snippet(f"{name}: {event.get('text') or ''}".rstrip(": "), 120)
        if not actions or actions[-1] != label:
            actions.append(label)
    if len(actions) > _MAX_ACTIONS_PER_ATTEMPT:
        overflow = len(actions) - (_MAX_ACTIONS_PER_ATTEMPT - 1)
        actions = actions[: _MAX_ACTIONS_PER_ATTEMPT - 1] + [f"(+{overflow} more actions)"]
    return actions


def _build_attempts(
    events: list[dict[str, Any]],
    *,
    goal: str,
    outcome: str,
    returncode: int | None,
    reason: str,
) -> list[dict[str, Any]]:
    if not events:
        return []
    segments, markers = _segment_attempts(events)
    attempts: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if index == 0:
            attempt_goal = _snippet(goal, 200) or "initial edit pass"
        else:
            marker = markers[index - 1]
            attempt_goal = f"repair verification failure (exit {marker.group('exit')}) — fix pass {marker.group('i')}/{marker.group('n')}"
        errors = [_snippet(e.get("text")) for e in segment if e.get("fc") == "error"]
        if is_last:
            attempt_outcome = outcome or ("completed" if returncode == 0 else "failed")
            exit_state = f"exit {returncode}" + (f" — {_snippet(reason, 160)}" if reason else "")
        else:
            next_marker = markers[index]
            attempt_outcome = "verification failed"
            exit_state = (
                f"engine check failed (exit {next_marker.group('exit')}); handed to fix pass {next_marker.group('i')}"
            )
        attempts.append(
            {
                "pass": index + 1,
                "goal": attempt_goal,
                "outcome": attempt_outcome,
                "key_actions": _attempt_actions(segment),
                "errors": errors[:3],
                "exit_state": exit_state,
            }
        )
    return attempts


def _build_validations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each engine check actually run: the ``run`` tool call paired with its result.

    KNOWN GAP, MEASURED, NOT FIXED — a check here describes the files as they
    were WHEN IT RAN, and the report presents it as though it describes what was
    delivered. Those differ whenever a run edits after its last check and is then
    cut off before re-checking.

    Measured end to end on conversation ``fc_20260730T161200_256915`` (the study
    planner, 2026-07-30). Its report's headline validation is::

        BROWSER_SMOKE_FAILED: index.html: Uncaught TypeError:
        Cannot read properties of null (reading 'value')

    Running that exact smoke — ``smoke_html_artifacts`` — against the run's real
    ``project_root`` gives ``ok=True``, ``errors=[]``, four times out of four,
    deterministically. The folder holds only the three delivered files, so this
    is not a leftover-asset difference; the reconstruction and the real folder
    agree with each other and disagree with the report. The transcript order is
    STATIC_VERIFY_OK, then BROWSER_SMOKE_FAILED, then "Pass budget exhausted
    after 10 passes while work was still active". Edits therefore landed after
    the last recorded check and were never re-verified.

    The reader is sent to hunt a null ``.value`` that no longer exists, while the
    defect the current smoke does report — three of four sidebar sections never
    switch, because script.js queries ``.section`` and the markup says
    ``class="panel"`` — is absent from the report entirely.

    Not fixed here because doing it honestly needs something this function cannot
    see: whether any file changed between the last check and the end of the run.
    The events carry no edit-vs-check ordering to compare. The two candidate
    fixes are re-verifying once before the report is written, or recording an
    edit watermark per validation so a stale one can be marked as such. Both are
    pipeline changes rather than a change to this assembly, and guessing here
    would replace a wrong claim with a differently wrong one.

    ``evidence_full`` is the check's WHOLE recorded output; ``evidence`` is the
    240-character excerpt the card shows. Both, because a fact about the run was
    being decided from the excerpt.

    The static verifier prints one ``compiled <file>`` line per file it checked
    and then a ``STATIC_VERIFY_OK: N files checked`` summary, and
    ``_build_open_risks`` reads that output to decide which changed files a
    passing check covered. It read ``evidence``, so a file whose line fell past
    character 240 was reported as never validated — by a report whose own next
    field named it as checked. Driven through the REAL verifier
    (``verify_python_changes``) on real files, same code, same exit 0, varying
    only how many files changed::

        changed files   verifier result   report's open risks
        3               exit 0, all ok    (none)
        9               exit 0, all ok    "files changed without a matching
                                           passing validation:
                                           src/module_number_07.py,
                                           src/module_number_08.py"

    Both of those files are in the check's recorded result
    (``compiled src/module_number_07.py``), 349 characters of which the report
    kept 240.

    KNOWN RESIDUE, measured, upstream. ``build_verify`` records the static result
    as ``detail[:500]``, so past roughly 15 changed paths the names stop reaching
    this function at all and no fix here can recover them. Measured with 10-char
    filenames: at 20 changed files the recorder still holds every name and only
    this module dropped them; at 30 it has lost 4 of its own, and the trailing
    ``STATIC_VERIFY_OK`` summary with them. Closing that means widening the
    recorder or having each check record the files it covered, which is a
    pipeline change, not an assembly one.
    """
    validations: list[dict[str, Any]] = []
    pending: str | None = None
    for event in events:
        kind = event.get("fc")
        if kind == "tool":
            # No `_flat` twin for the command: `build_verify` already emits it as
            # `label[:200]`, so this snippet drops nothing the run recorded.
            pending = _snippet(event.get("text"), 200) if str(event.get("name") or "") == "run" else None
        elif kind == "tool_result" and pending is not None:
            validations.append(
                {
                    "kind": "engine_check",
                    "command": pending,
                    "passed": event.get("is_error") is not True,
                    "evidence": _snippet(event.get("text")),
                    "evidence_full": _flat(event.get("text")),
                }
            )
            pending = None
    return validations


def _build_open_risks(
    events: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    *,
    changed_files: list[str],
    returncode: int | None,
    ok: bool,
    outcome: str,
    reason: str,
    foreign_writes: list[str] | None = None,
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if not events:
        risks.append({"risk": "no run activity was recorded", "detail": "the transcript contains no forge events"})
    if returncode is None:
        risks.append({"risk": "process exit could not be confirmed", "detail": _snippet(reason)})
    elif returncode != 0 and outcome not in ("conversation", "stopped"):
        # On a build, a dirty exit is real information and stays a risk. On the
        # other two outcomes it is the harness's own bookkeeping: the Claude CLI
        # exits 1 even when the answer landed (the runtime route calls the exit
        # code "the weakest evidence there is" and outranks it with the
        # confirmed reply), and a stopped run's exit code is the kill signal --
        # the person's decision, already recorded as "stopped by you". Measured
        # 2026-08-05: an explain-only run's card listed "run exited non-zero
        # (1)" as an open risk of an answer that was correct and complete. The
        # exit code is not hidden -- it stays in the recorded reason and in the
        # attempts' exit_state -- it just stops being filed as the run's defect.
        risks.append({"risk": f"run exited non-zero ({returncode})", "detail": _snippet(reason)})
    if validations and validations[-1]["passed"] is not True:
        risks.append(
            {
                "risk": "final verification failed",
                "detail": _snippet(f"{validations[-1]['command']} -> {validations[-1]['evidence']}"),
            }
        )
    if changed_files and not validations:
        risks.append(
            {
                "risk": "changed files were never validated",
                "detail": f"{len(changed_files)} file(s) changed but no engine check ran",
            }
        )
    # A check the engine SKIPPED is not a check that covered anything.
    #
    # `passed` is the absence of an error (`event.get("is_error") is not True`),
    # and a skipped browser smoke sets no error -- so it arrives here flagged
    # passed, and its evidence line still NAMES the page
    # (`BROWSER_SMOKE_SKIPPED: wordfreq.html: ...`). That put the filename into
    # `passing_text`, which silenced the very risk below that exists to say the
    # file was never covered by a passing check.
    #
    # Same shape as the transcript-mention bug in `_unopened_page_risks`: a
    # string that merely CONTAINS the filename was taken as proof something
    # examined it.
    #
    # Reads `evidence_full`, the check's WHOLE output, not `evidence`, the
    # 240-character excerpt the card shows. This decides a fact about the run --
    # "nothing validated this file" -- and it was deciding it from a display
    # excerpt, so a run with enough changed files accused its own passing check
    # of having skipped the ones whose lines fell off the end. Nine changed
    # files, exit 0, every one of them `compiled` in the recorded result, and the
    # report flagged the last two. See `_build_validations` for the measurement.
    #
    # Its two neighbours were already immune and that is what dates this one:
    # `_unopened_page_risks` and `_decorative_navigation_risks` both read the raw
    # `events` alongside the validations, and the first says why in as many words
    # -- "only one of those is guaranteed to survive truncation".
    passing_text = " ".join(
        f"{v['command']} {v.get('evidence_full') or v['evidence']}"
        for v in validations
        if v["passed"] and not _was_skipped(v)
    )
    uncovered = [f for f in changed_files if f.split("/")[-1] not in passing_text]
    if validations and uncovered:
        shown = ", ".join(uncovered[:5]) + (f" (+{len(uncovered) - 5} more)" if len(uncovered) > 5 else "")
        risks.append(
            {
                "risk": "files changed without a matching passing validation",
                "detail": shown,
            }
        )
    if not ok and "could not complete the requested action" in str(reason or "").lower():
        risks.append({"risk": "the agent reported it could not complete the action", "detail": _snippet(reason)})
    for event in events:
        if event.get("fc") != "error" or len(risks) >= _MAX_RISKS:
            continue
        # An error event whose whole text is a translator stand-in sentence
        # (see _HARNESS_FALLBACK_ERROR_TEXTS) carries nothing the run did, so
        # it cannot honestly be a row in a list of the run's risks. An error in
        # the run's own words -- any other text -- is still surfaced.
        if _flat(event.get("text")) in _HARNESS_FALLBACK_ERROR_TEXTS:
            continue
        risks.append({"risk": "error surfaced during the run", "detail": _snippet(event.get("text"))})
    if outcome == "noop" and not changed_files:
        risks.append({"risk": "run made no changes", "detail": "exit 0 but git shows no project delta"})
    risks.extend(_unopened_page_risks(events, validations, changed_files))
    risks.extend(_decorative_navigation_risks(validations, events))
    if foreign_writes:
        shown = ", ".join(foreign_writes[:3]) + (f" (+{len(foreign_writes) - 3} more)" if len(foreign_writes) > 3 else "")
        # Says "shows up in this run's changes", not "overwritten here", because
        # the second is a claim about authorship this data cannot support.
        # `changed_files` is the git diff of a SHARED folder, not a record of what
        # this run wrote, so any uncommitted file left by another task lands in it
        # untouched.
        #
        # Measured: five conversations share `Code task 2026-07-30 1145`. The
        # Godot FPS run held that folder from 17:05 to 17:17 UTC while two other
        # tasks wrote alpha.txt (17:09:44) and gamma.txt (17:15:45) into it. The
        # FPS report listed all three and said it had overwritten them; their
        # mtimes are still those of the tasks that made them, and the FPS run
        # never touched them. Concurrency is not exotic here — Thomas allows
        # eight simultaneous Code runs and these were two of them.
        #
        # The risk itself is worth keeping and fires correctly: work from another
        # task really is mixed into this run's file list, which is the thing worth
        # knowing. Only the claim about who wrote it was more than the data knew.
        risks.append(
            {
                "risk": "this run's changes include work from another code task",
                "detail": (
                    f"{shown} — created by a different task in this shared project, "
                    "and showing up in this run's changes; this run may not have written them"
                ),
            }
        )
    return risks[:_MAX_RISKS]


def _decorative_navigation_risks(
    validations: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Promote "the navigation is decoration" from a note on a pass to a risk.

    The browser smoke clicks the navigation controls it finds and compares the
    page before and after. When NONE of them change anything it says so, in a
    trailing note:

        browser boot clean; boot only; note: clicked 3 navigation control(s)
        and the page never changed; the navigation may be decoration

    -- and returns ok, so the check is recorded as passing and the sentence that
    matters rides along inside evidence nobody expands. That is the exact shape
    of the owner's Nova calculator: five nav destinations that looked finished
    and did nothing. (The smoke could not have caught Nova at the time -- it did
    not click anything then. It can now, and the finding was landing nowhere.)

    Deliberately a risk and not a failure. A page whose navigation is not wired
    yet is a normal midpoint of a build, and failing the run would make the
    repair loop chase a half-finished feature instead of the goal. A risk is
    visible on the card and steers the loop without stopping it.

    Only the "none of them did anything" phrasing is promoted. The smoke also
    reports "1 of 5 navigation control(s) changed nothing", which is the normal
    reading for whichever destination is already active -- flagging that would
    fire on every correct page and train people to ignore the line.
    """

    evidence = " ".join(
        [
            *(str(item.get("evidence") or "") for item in validations),
            *(str(item.get("text") or "") for item in events),
        ]
    )
    if "the navigation may be decoration" not in evidence:
        return []
    return [
        {
            "risk": "the navigation may be decoration",
            "detail": (
                "the browser check clicked every navigation control on the page and "
                "nothing changed — the destinations may not be wired up"
            ),
        }
    ]


def _unopened_page_risks(
    events: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    changed_files: list[str],
) -> list[dict[str, Any]]:
    """Flag a changed page that was never actually opened in a browser.

    A check that does not run reads exactly like a check that passed: the report
    said "0 open risks" while the strongest evidence available -- loading the
    page in a real browser -- had been skipped, because Chrome was missing or
    because nothing was found to own a changed asset. Every other risk here
    describes something that went wrong; this one describes something that never
    happened, which is the harder kind to notice and the reason a run can look
    green and still hand back a page nobody has seen.

    Scoped to changed HTML so it stays a fact rather than a guess. A project's
    Node scripts are not pages, and flagging them would train people to ignore
    this line, which is worse than not printing it.
    """

    pages = [name for name in changed_files if str(name).lower().endswith((".html", ".htm"))]
    if not pages:
        return []
    # ONLY strings that carry a browser-smoke marker, never the agent's own words.
    #
    # This used to join every validation evidence string with every event's
    # `text` -- which includes the agent's narration -- and then ask whether the
    # page's basename appeared anywhere in the result. But `fs.write_file`
    # always says "Wrote 4120 chars to C:/proj/orphan.html", so a page the smoke
    # never opened was treated as opened purely because the agent had mentioned
    # writing it. Every page an agent creates is mentioned that way, so this risk
    # could effectively never fire for the pages it exists to catch.
    #
    # Measured against a control -- same validations and changed files, varying
    # only the transcript: naming orphan.html suppressed the risk, not naming it
    # raised it. Full table in CHANGELOG.md; guard in
    # tests/test_the_agent_cannot_silence_the_unopened_page_risk.py. It also
    # re-broke what the comment below describes as fixed: one opened page
    # vouching for the others.
    #
    # Events stay in scope rather than being dropped, because build_verify emits
    # the smoke line BOTH as a `tool_result` event and appended to the check's
    # detail, and only one of those is guaranteed to survive truncation. The
    # marker test is what separates a smoke line from prose -- the agent has no
    # reason to ever type "BROWSER_SMOKE".
    evidence = " ".join(
        text
        for text in (
            *(str(item.get("evidence") or "") for item in validations),
            *(str(item.get("text") or "") for item in events),
        )
        if "BROWSER_SMOKE" in text
    )
    # A check that FAILED is the opposite of a check that never happened. Only
    # `BROWSER_SMOKE_OK` was treated as "opened", and a failing run says
    # `BROWSER_SMOKE_FAILED`, so it fell through to the silence branch: the
    # report printed "no browser check ran for this change" directly beneath the
    # failing browser check that had just examined that exact page. Observed on
    # a real run against `report.html`.
    #
    # It matters beyond tidiness. This risk exists to say "nobody looked", the
    # repair loop reads these risks, and telling it to go open a page that was
    # already opened points it away from the defect the opening found.
    #
    # Per PAGE rather than per run, because the old global check let one opened
    # page vouch for every other changed page: a run that opened `index.html`
    # and never touched `orphan.html` reported no risk at all.
    unopened = [name for name in pages if not _page_was_opened(evidence, name)]
    if not unopened:
        return []
    shown = ", ".join(unopened[:3]) + (f" (+{len(unopened) - 3} more)" if len(unopened) > 3 else "")
    skipped = "BROWSER_SMOKE_SKIPPED" in evidence
    return [
        {
            "risk": "a changed page was never opened in a browser",
            "detail": (
                f"{shown} — the browser check was skipped, so nothing here shows the page loads or draws"
                if skipped
                else f"{shown} — no browser check ran for this change"
            ),
        }
    ]


def _was_skipped(validation: dict[str, Any]) -> bool:
    """Did the engine SKIP this check rather than run it?

    Matched on the engine's own marker rather than the word "skipped", which
    turns up in unrelated evidence such as "1 files checked, 1 skipped". Same
    test the Code UI uses, so the two surfaces cannot drift.
    """

    return bool(_SKIPPED_EVIDENCE.search(str(validation.get("evidence") or "")))


def _page_was_opened(evidence: str, page: str) -> bool:
    """Did a browser check actually report on THIS page, pass or fail?

    The smoke names every page it opened in its own evidence line
    (``BROWSER_SMOKE_OK: index.html: ...``), so the page's own basename next to
    a smoke marker is the signal. Matched on a boundary rather than as a bare
    substring, or `game.html` would be considered opened by a line about
    `mygame.html`.
    """

    if "BROWSER_SMOKE_OK" not in evidence and "BROWSER_SMOKE_FAILED" not in evidence:
        return False
    base = str(page).replace("\\", "/").rsplit("/", 1)[-1]
    if not base:
        return False
    return re.search(rf"(?<![\w.-]){re.escape(base)}(?![\w-])", evidence) is not None


def _normalised_path(name: Any) -> str:
    """One spelling for a repo-relative path, so the two lists can be compared."""

    return str(name or "").replace("\\", "/").lstrip("/")


def _build_attention_pointers(
    events: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    changed_files: list[str],
    *,
    foreign_writes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Ranked reviewer starting points: failure sites first, then changed files.

    ``changed_files`` is the git delta of a SHARED project folder, not a record of
    what this run wrote. Thomas allows several simultaneous Code runs, so another
    task's uncommitted file landing in this delta is ordinary --
    ``forge_code_store.files_written_by_another_task`` exists precisely to spot it,
    and ``_build_open_risks`` already reports those as foreign.

    This section did not, so one report said both things about the same file: a
    risk warning that this run may not have written it, and a pointer captioned
    "changed in this run". Files this run really did change are also listed first
    now, so another task's leftovers cannot push the run's own work off the end of
    a capped list.
    """
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(target: str, why: str) -> None:
        if target and target not in seen:
            seen.add(target)
            ordered.append((target, why))

    failure_text = " ".join(
        [f"{v['command']} {v['evidence']}" for v in validations if not v["passed"]]
        + [str(e.get("text") or "") for e in events if e.get("fc") == "error"]
    )
    for match in _FILE_LINE_RE.finditer(failure_text):
        add(match.group("ref"), "referenced by a failing check or error")
    for validation in validations:
        if not validation["passed"]:
            add(validation["command"], "failing engine check")
    foreign = {_normalised_path(name) for name in (foreign_writes or []) if str(name or "").strip()}
    for file in changed_files:
        if _normalised_path(file) not in foreign:
            add(file, "changed in this run")
    for file in changed_files:
        if _normalised_path(file) in foreign:
            add(
                file,
                "in this run's changed-file list, but created by a different code task "
                "in this shared project — this run may not have written it",
            )
    return [
        {"target": target, "why": why, "rank": rank}
        for rank, (target, why) in enumerate(ordered[:_MAX_POINTERS], start=1)
    ]


def _extract_criteria(goal: str, definition: str) -> list[str]:
    criteria: list[str] = []
    for line in f"{goal}\n{definition}".split("\n"):
        match = _CRITERION_RE.match(line)
        if match:
            criteria.append(_snippet(match.group("text"), 200))
    return criteria[:_MAX_CRITERIA]


def _build_rubric_mapping(
    goal: str,
    definition: str,
    validations: list[dict[str, Any]],
    *,
    ok: bool,
    outcome: str,
    reason: str,
) -> list[dict[str, Any]]:
    goal_text = _snippet(goal, 200)
    if not goal_text:
        return []
    # Skipped checks are counted and named separately rather than folded into
    # "passed". The Code UI already does this
    # (unified_code_results.js: `wasSkipped`), but the rubric evidence is a
    # different surface and was still reporting "2 passed, 0 failed" for a run
    # where one of the two never ran.
    skipped = sum(1 for v in validations if v["passed"] and _was_skipped(v))
    passed = sum(1 for v in validations if v["passed"]) - skipped
    failed = len(validations) - passed - skipped
    counts = f"engine checks: {passed} passed, {failed} failed" + (
        f", {skipped} skipped" if skipped else ""
    )
    evidence = _snippet(
        f"outcome={outcome or ('completed' if ok else 'failed')}; {reason}; {counts}",
        _SNIPPET_CHARS,
    )
    # This row measures the RUN, not the goal, so it says so.
    #
    # It used to read `complete the requested goal: <the goal, in full> => met`
    # while the only thing establishing "met" was a zero exit code and a git
    # delta. Restating the whole ask and stamping it met is a claim that every
    # requirement in it was satisfied; nothing had examined any of them. The
    # comment below on the prose branch already spelled this out -- "finishing is
    # not the same as satisfying" -- and the sub-criteria under this row are
    # honestly `unverified` for exactly that reason. The top row was the one
    # place still overclaiming.
    #
    # The goal text is not lost: it is the user's own message directly above in
    # the transcript, and it stays in the criterion rows underneath.
    mapping = [
        {
            "criterion": "the run finished without error",
            "status": "met" if ok else "not_met",
            "evidence": _snippet(f"{evidence}; goal: {goal_text}", _SNIPPET_CHARS),
        }
    ]
    criteria = _extract_criteria(goal, definition)
    for criterion in criteria:
        # Sub-criteria are never individually re-verified by the engine, so they
        # are honestly reported as unverified rather than inferred as met.
        mapping.append(
            {
                "criterion": criterion,
                "status": "unverified",
                "evidence": "not individually verified by an engine check; see overall outcome",
            }
        )
    if not criteria:
        # _extract_criteria only matches BULLET lines. A goal typed as prose --
        # which is how people actually type them -- produced no sub-criteria at
        # all, so the whole rubric was the single "met" above, and its criterion
        # text is the goal restated in full. Read by a person, "complete the
        # requested goal: ... Start, Pause and Reset buttons that all work =>
        # met" says those buttons were checked. Nothing checked them.
        #
        # The failure is reachability, not wording: with no bullets the
        # "unverified" status could not be produced AT ALL, so a rubric with
        # nothing unverified was guaranteed rather than earned. That is the
        # same shape as an empty result being read as a clean one.
        #
        # No requirement is invented from the prose -- splitting a sentence into
        # criteria would put words in the goal's mouth and be wrong in a new
        # way. This states only what is true: nothing here was checked one by
        # one, and finishing is not the same as satisfying.
        mapping.append(
            {
                "criterion": "the specific requirements stated in this goal",
                "status": "unverified",
                # Says nothing about WHICH way the line above went. An earlier
                # wording asserted that it "reports the run finished and its
                # engine checks passed", which is a canned claim rather than a
                # reading of this run -- on a failed run (seen live: a rejected
                # model id, exit 1, not_met above it) the sentence was simply
                # false. A fix for overclaiming must not ship its own.
                "evidence": (
                    "the goal was not written as a checklist, so no individual requirement was "
                    "extracted or checked on its own; the outcome above is about the run as a "
                    "whole, not about each requirement in it"
                ),
            }
        )
    return mapping


def build_run_report(
    *,
    goal: str = "",
    definition: str = "",
    transcript: str = "",
    events: list[dict[str, Any]] | None = None,
    changed_files: list[str] | None = None,
    returncode: int | None = None,
    ok: bool = False,
    outcome: str = "",
    reason: str = "",
    foreign_writes: list[str] | None = None,
) -> dict[str, Any]:
    """Build the structured post-run report from a run's recorded data.

    ``events`` (already-parsed forge events) wins over ``transcript`` (raw stored
    text). Every section is derived from what the run data actually shows.
    """
    parsed = list(events) if events is not None else parse_forge_events(transcript)
    changed = [str(f) for f in (changed_files or [])]
    validations = _build_validations(parsed)
    return {
        # The recorded outcome word ("completed" | "conversation" | "stopped" |
        # "noop" | "failed"), carried on the report so the card can tell what
        # KIND of run it is grading. Without it the renderer could only see the
        # five sections, and it graded an answer-only run and a person's stop
        # with the same build-verification scorecard it uses for a build --
        # measured 2026-08-05 as "Nothing was checked · 1 requirement
        # unverified · 2 open risks" on a run the person had stopped on purpose.
        "outcome": str(outcome or ""),
        "attempts": _build_attempts(parsed, goal=goal, outcome=outcome, returncode=returncode, reason=reason),
        "validations": validations,
        "open_risks": _build_open_risks(
            parsed,
            validations,
            changed_files=changed,
            returncode=returncode,
            ok=ok,
            outcome=outcome,
            reason=reason,
            foreign_writes=list(foreign_writes or []),
        ),
        # The same `foreign` list both sections read, so the report cannot say a
        # file "may not have been written by this run" in one place and "changed
        # in this run" in the other.
        "attention_pointers": _build_attention_pointers(
            parsed, validations, changed, foreign_writes=list(foreign_writes or [])
        ),
        "rubric_mapping": _build_rubric_mapping(goal, definition, validations, ok=ok, outcome=outcome, reason=reason),
    }


def report_from_dispatch_result(
    result: Any, *, goal: str = "", definition: str = "", transcript: str = ""
) -> dict[str, Any]:
    """Build a report from a ``CliDispatchResult``-shaped dispatch outcome.

    Duck-typed (``ok``/``reason``/``returncode``/``changed_files``/``stdout_tail``)
    so it works for BOTH the claude-CLI and agent-loop dispatch results without
    importing either dispatcher.
    """
    return build_run_report(
        goal=goal,
        definition=definition,
        transcript=transcript or str(getattr(result, "stdout_tail", "") or ""),
        changed_files=list(getattr(result, "changed_files", None) or []),
        returncode=getattr(result, "returncode", None),
        ok=bool(getattr(result, "ok", False)),
        reason=str(getattr(result, "reason", "") or ""),
    )
