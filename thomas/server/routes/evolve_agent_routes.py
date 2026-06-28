"""HTTP API for the *directed* Evolve agent -- Thomas's self-builder.

This is the direct engineering seam. The Evolve chat talks straight to the
Evolve agent (Thomas's own autonomy-4 agent loop), bypassing the normal
``chat -> dispatcher -> task-manager`` route: self-development is not a task to
hand off, it is a direct engineering session.

In *directed* mode the agent runs against the LIVE repo and edits it directly --
git + the existing gates are the safety net and the user is in the loop watching
the stream. Its work (reasoning, tool calls, edits) is streamed back over SSE so
the user can see it and steer it -- the Codex/Claude-Code engineering experience,
powered entirely by Thomas's own model (no external CLIs).

Autonomous mode stays in the existing green/blue loop (``evolve_loop_routes``).
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_deliverables, forge_code_git, forge_code_store

log = logging.getLogger(__name__)

APP_EVOLVE_AGENT_TASK = "evolve_agent_task"
APP_EVOLVE_AGENT_DRAIN = "evolve_agent_drain"
APP_EVOLVE_AGENT_SESSION = "evolve_agent_session"
APP_EVOLVE_AGENT_CONVO = "evolve_agent_convo"
APP_EVOLVE_AGENT_SNAPSHOT = "evolve_agent_snapshot"
APP_EVOLVE_AGENT_MODEL = "evolve_agent_model"


def _default_repo_root() -> Path:
    # thomas/server/routes/evolve_agent_routes.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _agent_dir(root: Path) -> Path:
    d = root / ".thomas" / "evolve" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _transcript_path(root: Path) -> Path:
    return _agent_dir(root) / "transcript.txt"


async def _drain(proc: Any, transcript: Path) -> None:
    """Stream the agent's combined stdout into the transcript file, line by line,
    flushing so the SSE tail sees output as it happens."""
    try:
        with open(transcript, "ab") as fh:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                fh.write(line)
                fh.flush()
    except Exception:  # noqa: BLE001 - draining is best-effort; never crash the server
        log.warning("evolve agent: transcript drain failed", exc_info=True)
    finally:
        with contextlib.suppress(Exception):
            await proc.wait()


async def _drain_and_record(
    proc: Any,
    transcript: Path,
    root: Path,
    cid: str,
    model: str,
    snap: dict[str, str],
    app: web.Application,
) -> None:
    """Drain the live transcript, then record the run outcome onto the conversation.

    The outcome is computed from *git truth* at the moment the build finishes:
    a run that exits 0 but touched nothing is a no-op, exits 0 with changes is a
    success, and a non-zero exit is a failure. Recording is wrapped so a bad
    store/git call can never crash the server or lose the transcript.
    """
    await _drain(proc, transcript)
    try:
        rc = proc.returncode or 0
        try:
            text = transcript.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - transcript read is best-effort
            text = ""
        changed = forge_code_git.delta_since(root, snap)
        noop = rc == 0 and not changed
        ok = rc == 0 and bool(changed)
        if noop:
            reason = "no change made"
        elif rc:
            reason = f"exited {rc}"
        else:
            reason = f"{len(changed)} file(s) changed"
        forge_code_store.append_agent_turn(
            root,
            cid,
            model=model,
            transcript=text,
            changed_files=changed,
            returncode=rc,
            ok=ok,
            noop=noop,
            reason=reason,
        )
        # Close the loop into "My Stuff": a SUCCESSFUL run that produced a coherent
        # deliverable (the detector decides -- a built page/doc/image/data file, not
        # a code-only edit) becomes a durable, openable entry pointing back at this
        # conversation. A code-only or failed run registers nothing. The title is the
        # conversation's own (model-derived) name -- the build's purpose.
        if ok:
            conv = forge_code_store.load_conversation(root, cid) or {}
            forge_code_deliverables.register_from_run(
                root,
                conversation_id=cid,
                changed_files=changed,
                title=str(conv.get("title") or ""),
                model=model,
            )
    except Exception:  # noqa: BLE001 - recording must never crash the server
        log.warning("evolve agent: recording run outcome failed", exc_info=True)


def _line_to_sse_payload(line: str) -> dict[str, Any]:
    """Map one transcript line to an SSE payload for the live stream.

    A *forge event* line (``{"fc": <kind>, ...}`` emitted by the bridge as the CLI
    streams) becomes a typed frame: it stays ``type:"output"`` (so progressive
    output frames are still counted as such) but carries a ``kind``
    (say/tool/tool_result/error/meta) plus its fields, which the browser renders
    with a distinct transcript class. Any other line is forwarded as plain output
    text (e.g. the CLI's own summary echo). Parsing is fully defensive: a
    malformed line degrades to plain text rather than breaking the stream.
    """
    stripped = line.strip()
    if not stripped:
        return {}
    if stripped[0] == "{":
        try:
            obj = json.loads(stripped)
        except Exception:  # noqa: BLE001 - not a forge event -> fall through to plain text
            obj = None
        if isinstance(obj, dict) and obj.get("fc"):
            payload: dict[str, Any] = {
                "type": "output",
                "kind": str(obj.get("fc")),
                "text": str(obj.get("text") or ""),
            }
            if obj.get("name"):
                payload["name"] = str(obj.get("name"))
            if obj.get("is_error"):
                payload["is_error"] = True
            # A token-progressive ``say`` fragment (claude partial-message / GPT
            # TEXT_DELTA): carry the flag so the browser APPENDS it incrementally
            # instead of treating it as a whole finished block.
            if obj.get("delta"):
                payload["delta"] = True
            return payload
    return {"type": "output", "text": line}


class _IncrementalLineDecoder:
    """Turn a stream of arbitrary UTF-8 *byte* chunks into complete text lines,
    holding any partial trailing multibyte char AND any partial trailing line
    across feeds.

    The build subprocess emits each forge event as one UTF-8 JSON line, but the
    transcript is tailed in arbitrary byte chunks (``fh.read()`` returns whatever
    bytes are on disk so far). A multibyte char can straddle that boundary -- an
    em-dash is 3 bytes (E2 80 94), an emoji 4 -- so a per-chunk
    ``bytes.decode(..., errors="replace")`` would mangle each split half into the
    U+FFFD replacement char (the Perf-45 narration glitch). Feeding every chunk
    through ONE stateful incremental decoder keeps the partial sequence buffered
    until the bytes that complete it arrive, so unicode renders intact in the
    live transcript.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""

    def feed(self, chunk: bytes) -> list[str]:
        """Decode ``chunk`` and return only the lines it newly COMPLETES.

        A partial trailing line (no terminating newline yet) and a partial
        trailing multibyte char are both retained for the next feed.
        """
        if chunk:
            self._buf += self._decoder.decode(chunk)
        *lines, self._buf = self._buf.split("\n")
        return lines

    def flush(self) -> list[str]:
        """Final drain at end-of-stream.

        Flush any genuinely-truncated trailing byte sequence exactly once
        (``final=True``) and return any remaining complete lines plus a final
        newline-less remainder (dropped if it is only whitespace).
        """
        self._buf += self._decoder.decode(b"", final=True)
        parts = self._buf.split("\n")
        self._buf = ""
        remainder = parts.pop() if parts else ""
        if remainder.strip():
            parts.append(remainder)
        return parts


def _kill_tree(proc: Any) -> None:
    """Kill the whole build process tree -- the dispatch python AND any
    ``claude -p`` grandchild -- not just the immediate child.

    The claude brain spawns a headless ``claude -p`` child; the GPT brain runs
    in-process (no grandchild). Stopping only ``proc`` would orphan a headless CLI
    it spawned, leaving the real build still running. Prefer psutil (cross-platform
    recursive kill);
    fall back to ``taskkill /T`` on Windows and ``terminate()`` elsewhere. Every
    path is defensive: a process that already exited must not raise.
    """
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            with contextlib.suppress(Exception):
                child.kill()
        with contextlib.suppress(Exception):
            parent.kill()
    except Exception:  # noqa: BLE001 - psutil missing or process gone; fall back
        with contextlib.suppress(Exception):
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.terminate()


def build_evolve_agent_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> dict[str, Any]:
    def _root() -> Path:
        return Path(root_resolver())

    def _running() -> bool:
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        return proc is not None and proc.returncode is None

    async def send(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        message = str((body or {}).get("message") or "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "empty message"}, status=400)
        if _running():
            return web.json_response({"ok": False, "error": "agent is already working"}, status=409)
        # Both engines build through the headless CLI bridge: it runs on the operator's
        # OWN Claude/GPT subscription (no in-process OAuth needed) and honours the brain
        # picker. "agent" = build directly; "funnel" = converge a plan across isolated
        # agents first, then build. Pressing Send in the Code UI is the explicit
        # authorization the bridge requires (THOMAS_CLAUDE_BRIDGE_ENABLED).
        engine = str((body or {}).get("engine") or "agent").strip().lower()
        model = str((body or {}).get("model") or "claude:sonnet").strip()
        effort = str((body or {}).get("effort") or "medium").strip()
        conversation_id = str((body or {}).get("conversation_id") or "").strip()
        source_evolve_item = (body or {}).get("source_evolve_item")
        if not isinstance(source_evolve_item, dict):
            source_evolve_item = None

        root = _root()

        # Resolve the conversation this turn belongs to: resume the requested one
        # when it exists, else open a fresh build. The user turn is recorded now;
        # the agent turn (with its git-truth outcome) is recorded when the build
        # finishes (see _drain_and_record).
        conv = forge_code_store.load_conversation(root, conversation_id) if conversation_id else None
        if conv is None:
            conv = forge_code_store.new_conversation(root, source_evolve_item=source_evolve_item)
        cid = conv["id"]
        app[APP_EVOLVE_AGENT_CONVO] = cid
        app[APP_EVOLVE_AGENT_MODEL] = model
        forge_code_store.append_user_turn(root, cid, message)

        # Fingerprint the working tree BEFORE the build so we can attribute the
        # exact set of files this run touched (delta_since) when it completes.
        snap = forge_code_git.snapshot(root)
        app[APP_EVOLVE_AGENT_SNAPSHOT] = snap

        transcript = _transcript_path(root)
        transcript.write_bytes(b"")  # fresh transcript for this turn; the stream tails it (append)
        env = dict(os.environ)
        env["THOMAS_CLAUDE_BRIDGE_ENABLED"] = "1"
        # Force the child's stdio to UTF-8 regardless of the host's code page. On
        # Windows the spawned interpreter would otherwise default sys.stdout to
        # cp1252, so an em-dash/curly-quote in a forge event would go out as a
        # cp1252 byte (e.g. 0x97) — invalid UTF-8 to the byte-level reader below,
        # which renders it as the U+FFFD replacement char. PYTHONUTF8 puts the
        # interpreter in UTF-8 mode; PYTHONIOENCODING pins the stdio encoding even
        # on interpreters that don't honor the former. This is the belt to the
        # bridge's own UTF-8 byte emit (suspenders) — either alone fixes it.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [
            "-m",
            "thomas",
            "evolve",
            "dispatch",
            message,
            "--via",
            "cli",
            "--execute",
            "--yes",
            "--model",
            model,
            "--effort",
            effort,
            # Hand the conversation id down so the dispatched turn loads its prior
            # turns as history -- a real multi-turn exchange, not a one-shot. The
            # current user turn was just recorded above; the composer drops it so
            # it is not duplicated alongside the goal.
            "--conversation-id",
            cid,
        ]
        if engine == "funnel":
            cmd.append("--use-funnel")
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *cmd,
            cwd=str(root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_DRAIN] = asyncio.ensure_future(
            _drain_and_record(proc, transcript, root, cid, model, snap, app)
        )
        app[APP_EVOLVE_AGENT_SESSION] = {"started_at": time.time(), "message": message}
        return web.json_response({"ok": True, "started": True, "conversation_id": cid})

    async def stream(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        transcript = _transcript_path(_root())
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await resp.prepare(request)
        pos = 0
        # A STATEFUL utf-8 line decoder: each file read returns an arbitrary number
        # of bytes that may split a multibyte char (an em-dash "—" is 3 bytes, an
        # emoji 4), so a per-chunk ``bytes.decode`` would emit U+FFFD (�) for the
        # split halves. The incremental decoder holds the partial sequence until
        # the next chunk completes it, so unicode renders correctly across reads.
        linedec = _IncrementalLineDecoder()

        async def _emit_line(line: str) -> None:
            payload = _line_to_sse_payload(line)
            if payload:
                await resp.write(("data: " + json.dumps(payload) + "\n\n").encode("utf-8"))

        try:
            while not (request.transport is None or request.transport.is_closing()):
                chunk = b""
                if transcript.exists():
                    with open(transcript, "rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        pos = fh.tell()
                if chunk:
                    # Emit each COMPLETE line as its own (possibly typed) frame so the
                    # transcript fills progressively and structure is preserved.
                    for line in linedec.feed(chunk):
                        await _emit_line(line)
                    # Data was flowing — loop again IMMEDIATELY (no poll delay) to
                    # drain the rest of the burst, so a fast run's tokens are not
                    # paced by the idle interval. We only sleep when the file is
                    # momentarily empty (below).
                    await asyncio.sleep(0)
                    continue
                if not _running():
                    # Final drain: the child may have flushed its last lines after
                    # our read above but before we noticed it exited — pick them up.
                    if transcript.exists():
                        with open(transcript, "rb") as fh:
                            fh.seek(pos)
                            tail = fh.read()
                            pos = fh.tell()
                        if tail:
                            for line in linedec.feed(tail):
                                await _emit_line(line)
                    # Flush any bytes the decoder is still holding (a truncated
                    # trailing sequence) so nothing is silently dropped.
                    for line in linedec.flush():
                        await _emit_line(line)
                    proc = app.get(APP_EVOLVE_AGENT_TASK)
                    rc = proc.returncode if proc is not None else None
                    # Carry the real run outcome, computed from git truth at done
                    # time, so the UI can render success/no-op/failure without a
                    # second round-trip.
                    snap = app.get(APP_EVOLVE_AGENT_SNAPSHOT) or {}
                    changed = forge_code_git.delta_since(_root(), snap)
                    await resp.write(
                        (
                            "data: "
                            + json.dumps(
                                {
                                    "type": "done",
                                    "returncode": rc,
                                    "changed_files": changed,
                                    # Renderable previews this run produced, so the
                                    # UI can show artifact cards immediately (the
                                    # same set is also recorded on the agent turn).
                                    "artifacts": forge_code_store.detect_artifacts(changed),
                                    "conversation_id": app.get(APP_EVOLVE_AGENT_CONVO) or "",
                                    "noop": rc == 0 and not changed,
                                }
                            )
                            + "\n\n"
                        ).encode("utf-8")
                    )
                    break
                # Idle: nothing on disk yet. Poll TIGHTLY (was 0.4s) so the FIRST
                # token surfaces fast (TTFT) and subsequent tokens feel live, not
                # ~400ms-quantized. A burst short-circuits this via the `continue`
                # above, so this only paces the genuinely-empty gaps.
                await asyncio.sleep(0.05)
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        return resp

    async def status(request: web.Request) -> web.Response:
        require_api_access(request)
        sess = app.get(APP_EVOLVE_AGENT_SESSION) or {}
        return web.json_response(
            {
                "ok": True,
                "running": _running(),
                "session": {"message": sess.get("message", ""), "started_at": sess.get("started_at")},
            }
        )

    async def stop(request: web.Request) -> web.Response:
        require_api_access(request)
        proc = app.get(APP_EVOLVE_AGENT_TASK)
        if proc is not None and proc.returncode is None:
            # Sub-1s perceived Stop: the process-tree kill (psutil / taskkill /T)
            # can take a beat and would block the event loop, so we hand it to a
            # worker thread and return the "stopped" reply IMMEDIATELY — we do NOT
            # await the kill. The client has already optimistically flipped to idle
            # and closed its EventSource, so nothing depends on the kill finishing
            # before this response lands.
            def _kill() -> None:
                with contextlib.suppress(Exception):
                    _kill_tree(proc)

            with contextlib.suppress(Exception):
                asyncio.get_running_loop().run_in_executor(None, _kill)
        return web.json_response({"ok": True, "stopped": True})

    async def deliverables_list(request: web.Request) -> web.Response:
        """List Forge Code build deliverables for the "My Stuff" surface.

        Each entry is a real, openable build output (carrying its title, kind,
        ``open_url`` artifact-preview link, and a ``deep_link`` back to the
        originating Code conversation). Code-only runs are never present here --
        registration is gated on the artifact detector at run completion.
        """
        require_api_access(request)
        return web.json_response({"ok": True, "deliverables": forge_code_deliverables.list_deliverables(_root())})

    async def conversations_list(request: web.Request) -> web.Response:
        require_api_access(request)
        root = _root()
        summaries = forge_code_store.list_conversations(root)
        return web.json_response(
            {
                "ok": True,
                "conversations": summaries,
                "days": forge_code_store.group_by_day(summaries),
            }
        )

    async def conversation_get(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        conv = forge_code_store.load_conversation(_root(), cid)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        return web.json_response({"ok": True, "conversation": conv})

    async def conversation_new(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        title = str((body or {}).get("title") or "").strip()
        source = (body or {}).get("source_evolve_item")
        if not isinstance(source, dict):
            source = None
        conv = forge_code_store.new_conversation(_root(), title=title or None, source_evolve_item=source or None)
        return web.json_response({"ok": True, "conversation": conv})

    async def conversation_rename(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        title = str((body or {}).get("title") or "").strip()
        if not title:
            return web.json_response({"ok": False, "error": "empty title"}, status=400)
        conv = forge_code_store.rename_conversation(_root(), cid, title)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        return web.json_response({"ok": True, "conversation": conv})

    async def conversation_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        removed = forge_code_store.delete_conversation(_root(), cid)
        if not removed:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        return web.json_response({"ok": True, "deleted": True, "id": cid})

    def _conversation_changed_files(root: Path, cid: str) -> set[str] | None:
        """Union of the files THIS conversation's build(s) actually wrote.

        Returns the set recorded across the conversation's agent turns
        (``changed_files``, the per-turn git delta captured when each build
        finished), or ``None`` when the conversation is unknown -- the caller
        then falls back to the whole dirty tree.
        """
        conv = forge_code_store.load_conversation(root, cid) if cid else None
        if conv is None:
            return None
        files: set[str] = set()
        for turn in conv.get("turns") or []:
            if turn.get("role") == "agent":
                for f in turn.get("changed_files") or []:
                    if f:
                        files.add(str(f))
        return files

    async def changes(request: web.Request) -> web.Response:
        require_api_access(request)
        root = _root()
        # SCOPE to the active conversation's OWN build output, not the whole dirty
        # tree. The set of files this run wrote is recorded per agent turn
        # (changed_files); we intersect it with what git STILL reports as dirty so
        # a file that was reverted/committed drops out -- the diffs stay REAL, just
        # narrowed to this run's set. With no conversation context we fall back to
        # the full dirty tree (prior behavior) rather than show nothing.
        cid = request.query.get("cid") or app.get(APP_EVOLVE_AGENT_CONVO) or ""
        scoped = _conversation_changed_files(root, str(cid))
        dirty = forge_code_git.changed_files(root)
        if scoped is not None:
            files = [f for f in dirty if f in scoped]
        else:
            files = dirty
        out: list[dict[str, Any]] = []
        for f in files:
            out.append(
                {
                    "file": f,
                    "untracked": forge_code_git.is_untracked(root, f),
                    "diff": forge_code_git.unified_diff(root, f),
                }
            )
        return web.json_response({"ok": True, "changed": out})

    async def revert(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        file = str((body or {}).get("file") or "").strip()
        if not file:
            return web.json_response({"ok": False, "error": "no file"}, status=400)
        return web.json_response(forge_code_git.revert_file(_root(), file))

    async def keep(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - missing/invalid body -> treat as empty
            body = {}
        file = str((body or {}).get("file") or "").strip()
        if not file:
            return web.json_response({"ok": False, "error": "no file"}, status=400)
        # Keep is a deliberate no-op on disk: the change already lives in the
        # working tree, so "keep" just acknowledges it and leaves it untouched.
        return web.json_response({"ok": True, "kept": True, "file": file})

    async def artifact(request: web.Request) -> web.StreamResponse:
        """Serve ONE file a build produced, same-origin, for the transcript preview.

        This backs the artifact card's <iframe>/<img>/markdown/data preview. It is
        deliberately narrow: a path is served only when it is a file THIS build
        actually wrote -- it must appear in the conversation's recorded
        ``changed_files`` (git-truth captured when the build finished) OR in git's
        CURRENT dirty set (covering the brief window before the agent turn is
        persisted). It is never an arbitrary repo file, and a path that escapes the
        repo root is refused.

        The bytes are the REAL built file -- no templating, no fabrication. Built
        output is untrusted, so (exactly like the deliverable route) it is forced
        into a sandboxed opaque origin at the response layer: a built HTML page can
        render in the preview iframe but can never reach the host app's
        DOM/cookies/localStorage. CORP ``same-site`` keeps the same-origin
        <iframe>/<img> load working (the "CORP white-screen" fix) without exposing
        the artifact cross-site.
        """
        require_api_access(request)
        root = _root()
        cid = request.match_info.get("cid", "")
        tail = (request.match_info.get("tail", "") or "").strip()
        if not tail:
            raise web.HTTPNotFound(text="no artifact path")
        rel = tail.replace("\\", "/")
        allowed = _conversation_changed_files(root, str(cid)) or set()
        allowed |= set(forge_code_git.changed_files(root))
        if rel not in allowed:
            raise web.HTTPNotFound(text="not an artifact of this build")
        root_resolved = root.resolve()
        target = (root_resolved / rel).resolve()
        if not target.is_file() or not target.is_relative_to(root_resolved):
            raise web.HTTPNotFound(text="artifact file not found")
        response = web.FileResponse(target)
        response.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-forms"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        return response

    return {
        "send": send,
        "stream": stream,
        "status": status,
        "stop": stop,
        "deliverables_list": deliverables_list,
        "conversations_list": conversations_list,
        "conversation_get": conversation_get,
        "conversation_new": conversation_new,
        "conversation_rename": conversation_rename,
        "conversation_delete": conversation_delete,
        "changes": changes,
        "revert": revert,
        "keep": keep,
        "artifact": artifact,
    }


def register_evolve_agent_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> None:
    """Register the directed Evolve-agent API onto the aiohttp app."""
    handlers = build_evolve_agent_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    app.router.add_post("/api/evolve/agent/send", handlers["send"])
    app.router.add_get("/api/evolve/agent/stream", handlers["stream"])
    app.router.add_get("/api/evolve/agent/status", handlers["status"])
    app.router.add_post("/api/evolve/agent/stop", handlers["stop"])
    # "My Stuff": list the build deliverables this Forge Code agent has produced.
    app.router.add_get("/api/evolve/agent/deliverables", handlers["deliverables_list"])
    # Conversation history: list / resume / open-new.
    app.router.add_get("/api/evolve/agent/conversations", handlers["conversations_list"])
    app.router.add_post("/api/evolve/agent/conversations/new", handlers["conversation_new"])
    app.router.add_get("/api/evolve/agent/conversations/{cid}", handlers["conversation_get"])
    # Rename (inline edit) and delete from the history sidebar.
    app.router.add_post("/api/evolve/agent/conversations/{cid}/rename", handlers["conversation_rename"])
    app.router.add_delete("/api/evolve/agent/conversations/{cid}", handlers["conversation_delete"])
    # Git-truth review surface: see the diff, revert a file, or keep it.
    app.router.add_get("/api/evolve/agent/changes", handlers["changes"])
    app.router.add_post("/api/evolve/agent/revert", handlers["revert"])
    app.router.add_post("/api/evolve/agent/keep", handlers["keep"])
    # Same-origin artifact preview source for the transcript's artifact cards
    # (sandboxed built output: HTML page / image / markdown / data file).
    app.router.add_get("/api/evolve/agent/artifact/{cid}/{tail:.*}", handlers["artifact"])
