"""Verified background-task completion announcements for Chat V2."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

# A real-world SIDE-EFFECT command on external devices/accounts. When the ask
# is one of these but the deliverable is a script/config/bridge FILE, the
# physical action did NOT happen (Thomas built the control; the user connects
# their hub). The announcement must never claim "your lights are off."
_DEVICE_ACTION_RE = re.compile(
    r"\b(turn\b[\w\s]{0,24}\b(?:on|off)|switch\b[\w\s]{0,24}\b(?:on|off)|"
    r"(?:lights?|lamp|fan|tv|plug|outlet|thermostat|door|lock|garage)\b[\w\s]{0,24}\b(?:on|off)|"
    # "set my bedroom thermostat to 68" — allow words between the verb and the
    # device/target so real phrasings (and derived titles) match.
    r"set\b[\w\s]{0,30}\b(?:thermostat|temperature|temp|heat(?:er|ing)?|ac|air\s*condition|"
    r"alarm|degrees?|lights?|scene|brightness|volume)|"
    # The device group used to end in `?`, which made it optional -- so the bare
    # word "toggle" matched on its own and "Add a dark mode toggle to the site"
    # was read as a request to touch a physical device. Shipping app.js then made
    # Thomas announce that the work had NOT been done. A device word is required.
    r"(?:dim|brighten|lock|unlock|arm|disarm|toggle)\b[\w\s]{0,24}\b"
    r"(?:lights?|lamp|door|garage|alarm|thermostat|system)|"
    r"open\b[\w\s]{0,24}\b(?:door|garage|blinds?|shades?)|"
    r"close\b[\w\s]{0,24}\b(?:door|garage|blinds?|shades?)|"
    r"(?:play|pause|send|text|email|call|schedule|book|order|pay|transfer)\b)",
    re.I,
)
_SCRIPT_ARTIFACT_RE = re.compile(r"\.(ps1|sh|bat|cmd|py|js|mjs|ts|json|ya?ml|toml|ini|env|conf)$", re.I)

from aiohttp import web

from thomas.agent.response_tone import strip_sandbox_links
from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core.file_access import file_access_refusal_remedy
from thomas.server.chat_delegation_result_policy import result_with_policy_remedy
from thomas.server.routes.chat_v2_keys import (
    APP_ANNOUNCE_LOCKS,
    APP_SESSION_LLM_CACHE,
    APP_SESSION_STORE,
)
from thomas.server.routes.chat_v2_support import _UNSUPPORTED_GAP_CLAIM_RE

try:
    from thomas.server.app_keys import APP_CONFIG
except ImportError:
    APP_CONFIG = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Spellings this surface accepts on top of task_bot_runtime.TERMINAL_STATES,
# which is the vocabulary the task ledger actually WRITES. Legacy/foreign rows
# reach here with workboard words ("done"), with the pre-completion "verified",
# and with "error" from non-ledger producers, so they stay recognised -- but the
# is-it-over test is DERIVED from the writer instead of being spelled out again,
# so it can never drift past it. "blocked" is deliberately absent: see
# _handle_announce_delegation_locked.
_ANNOUNCE_TERMINAL_ALIASES = frozenset({"done", "verified", "succeeded", "passed", "error"})
# "abandoned" belongs here for the same reason the orchestrator's report-once
# machinery lists it (brain._FAILED_STATES) and Mission Control files it under
# review/failed: nobody is coming back to it. "cancelled" is left out on
# purpose -- the user stopped it themselves, and this card is binary, so calling
# a run you stopped "failed" is wrong and calling it "completed" is also wrong.
# It is terminal (so it is no longer retried as "not_terminal" forever) but not
# a failure, which lands it on the existing unverified-completion skip.
_ANNOUNCE_FAILED_STATES = frozenset({"failed", "abandoned", "error"})


def _announce_llm(app: web.Application, sid: str) -> Any | None:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    entry = cache.get(sid)
    if entry is not None and getattr(entry, "llm", None) is not None:
        return entry.llm
    cfg = app.get(APP_CONFIG) if APP_CONFIG is not None else None
    if cfg is None:
        return None
    try:
        from thomas.core.llm_client import LLMClient

        return LLMClient(cfg.get_model(getattr(cfg, "default_model", "") or None))
    except (AttributeError, ImportError, LookupError, RuntimeError, TypeError, ValueError) as exc:
        log.debug("announce LLM lookup failed for session %s: %s", sid, exc, exc_info=True)
        return None


def _announcement_lock_for(app: web.Application, sid: str) -> asyncio.Lock:
    cache = app.get(APP_SESSION_LLM_CACHE) or {}
    cached_lock = getattr(cache.get(sid), "lock", None)
    if isinstance(cached_lock, asyncio.Lock):
        return cached_lock
    locks = app.get(APP_ANNOUNCE_LOCKS)
    if not isinstance(locks, dict):
        locks = {}
        app[APP_ANNOUNCE_LOCKS] = locks
    lock = locks.get(sid)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[sid] = lock
    return lock


async def _generate_note(llm: Any, system: str, user: str, timeout_s: float = 30.0) -> str:
    parts: list[str] = []

    async def _run() -> None:
        aiter = llm.stream_chat(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=None,
        ).__aiter__()
        while True:
            try:
                event = await aiter.__anext__()
            except StopAsyncIteration:
                break
            event_type = str(getattr(event, "type", "") or "")
            if event_type == "token":
                text = str((getattr(event, "data", {}) or {}).get("text") or "")
                if text:
                    parts.append(text)
            elif event_type == "error":
                break

    try:
        await asyncio.wait_for(_run(), timeout=timeout_s)
    except asyncio.TimeoutError:
        pass
    except (AttributeError, RuntimeError, OSError, TypeError, ValueError) as exc:
        log.debug("announce note generation failed: %s", exc, exc_info=True)
    return "".join(parts).strip()


def _failed_note_with_policy_remedy(note: str, summary: str) -> str:
    """Keep a file-access refusal's remedy in the sentence the user reads.

    Measured live (exec-c3adbfcfa341, 2026-08-07 08:50): a refused Desktop
    write ended with the reply "I can try again if you provide a permitted
    folder path" — improvised, with no mention that a user-settable file-access
    level exists. The note here is model-authored from ``summary[:300]`` and
    asked to be "one or two short sentences", so a remedy threaded into the
    stored summary dies twice before the chat bubble: truncated away, then
    paraphrased away.

    So the remedy the summary carries is guaranteed deterministically: if the
    note already says it, nothing changes; otherwise it is appended. Additive
    only — the model's own sentence is kept, and a summary with no remedy
    changes nothing.
    """
    return result_with_policy_remedy(note, [str(summary or "")])


async def handle_announce_delegation(request: web.Request) -> web.Response:
    app = request.app
    sid = str(request.match_info.get("session_id", "") or "").strip()
    exec_id = str(request.match_info.get("execution_id", "") or "").strip()
    if not sid or not exec_id:
        return web.json_response({"ok": False, "error": "missing_ids"}, status=400)
    async with _announcement_lock_for(app, sid):
        return await _handle_announce_delegation_locked(app, sid, exec_id)


async def _handle_announce_delegation_locked(app: web.Application, sid: str, exec_id: str) -> web.Response:
    try:
        from datetime import datetime, timezone

        from thomas.core import task_bot_runtime
        from thomas.core.action_receipt import delegated_action_receipt

        row = task_bot_runtime.get_execution(exec_id) or {}
        owner = str(row.get("conversation_id") or "").strip()
        if owner and owner != sid:
            return web.json_response({"ok": False, "error": "session_mismatch"}, status=403)
        if str(row.get("reported_to_chat_at") or "").strip():
            return web.json_response({"ok": True, "skipped": "already_reported"})
        state = str(row.get("state") or "").lower()
        # "blocked" is NOT an ending, and this endpoint used to treat it as one.
        #
        # One decision -- "is this run over, and did it fail" -- was spelled out
        # here as a literal that disagreed with task_bot_runtime, the module that
        # WRITES these states. TERMINAL_STATES does not contain "blocked", and
        # ALLOWED_TRANSITIONS lets a blocked run go back to
        # queued/claimed/executing, so a task merely waiting on an approval gate
        # is paused, not over.
        #
        # The damage was durable rather than cosmetic. The blocked row passed
        # this gate, `failed` on the next line called it a failure, and the
        # handler wrote a model-authored "I ran into a problem and could not
        # finish that" into the SAVED transcript -- then stamped
        # reported_to_chat_at, which is the very first thing checked above. So
        # when the user approved the gate and the work really did finish, the
        # genuine announcement came back "already_reported" and Thomas never
        # mentioned it again.
        #
        # Same shape as the classic shell's Mission Control fallback, which was
        # settled the same way and by the same state machine.
        terminal = task_bot_runtime.TERMINAL_STATES | _ANNOUNCE_TERMINAL_ALIASES
        if state not in terminal:
            return web.json_response({"ok": True, "skipped": "not_terminal"})
        failed = state in _ANNOUNCE_FAILED_STATES
        receipt = delegated_action_receipt(row, session_id=sid).to_dict()
        if not failed and receipt.get("ok") is not True:
            return web.json_response({"ok": True, "skipped": "unverified_completion"})
        runtime_profile = row.get("runtime_profile") if isinstance(row.get("runtime_profile"), dict) else {}
        proof = row.get("proof") if isinstance(row.get("proof"), dict) else {}
        artifacts = proof.get("artifacts") if isinstance(proof.get("artifacts"), list) else []
        if not failed and bool(runtime_profile.get("canvas")) and not artifacts:
            return web.json_response({"ok": True, "skipped": "canvas_without_verified_artifact"})
        session_store: SessionStore = app[APP_SESSION_STORE]
        conversation = await session_store.load(sid) or ConversationManager()
        progress_summary = str(row.get("progress_summary") or "").strip()
        summary = progress_summary or str(row.get("summary") or "").strip()
        task_title = str(row.get("summary") or "the task").strip() or "the task"
        bot = str(row.get("bot_name") or row.get("bot_id") or "a worker").strip() or "a worker"
        artifact_names = [
            str(item.get("name") or item.get("path") or "").strip()
            for item in artifacts
            if isinstance(item, dict) and str(item.get("name") or item.get("path") or "").strip()
        ]
        verified_answer = str(runtime_profile.get("max_verified_answer_text") or "").strip()
        if not failed and bool(runtime_profile.get("max_answer_only")) and verified_answer:
            # The Max crew's last draft is the exact candidate the fresh graders
            # approved. Present it verbatim; asking another ungraded model to
            # summarize would replace the audited result with a new one.
            note = verified_answer[:64_000]
        elif not failed and not artifacts and progress_summary:
            # A verified text-only answer is already the requested deliverable.
            # Rewriting it through another model turns plans, explanations, and
            # markers into vague "worker finished" status prose.
            note = progress_summary[:64_000]
        elif not failed and not artifacts:
            # A verified receipt does not turn the original task title into an
            # answer. Wait for the persisted worker answer instead of echoing the
            # request back as if it were the completed deliverable.
            return web.json_response({"ok": True, "skipped": "verified_text_missing"})
        else:
            llm = _announce_llm(app, sid)
            if llm is None or not hasattr(llm, "stream_chat"):
                return web.json_response({"ok": False, "error": "no_llm"}, status=503)
            # Give Thomas the recent conversation so the result lands as him
            # jumping back into the SAME thread — "here's what they were talking
            # about, let me drop this in" — not a detached worker notification.
            recent_context = ""
            try:
                convo_msgs = conversation.get_messages() if hasattr(conversation, "get_messages") else []
                tail = [m for m in convo_msgs if isinstance(m, dict) and m.get("role") in ("user", "assistant")][-4:]
                if tail:
                    lines = []
                    for m in tail:
                        who = "User" if m.get("role") == "user" else "You (Thomas)"
                        content = m.get("content")
                        if isinstance(content, list):
                            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
                        text = str(content or "").strip().replace("\n", " ")[:280]
                        if text:
                            lines.append(f"{who}: {text}")
                    if lines:
                        recent_context = "Recent conversation so far:\n" + "\n".join(lines) + "\n\n"
            except (AttributeError, TypeError, ValueError):
                recent_context = ""
            system = (
                "You are Thomas, the user's warm, capable assistant. You are continuing an "
                "ongoing conversation — a task you were working on just finished, so jump back "
                "in naturally with the result, aware of what you were both just discussing. "
                "Reply in your own natural voice: brief, human, first person, no preamble, "
                "no 'as an AI', and never mention a 'task manager' or 'worker' — YOU did this."
            )
            bits = [recent_context] if recent_context else []
            bits += [
                "The work you were doing "
                + ("ran into a problem and could not finish." if failed else "just finished.")
            ]
            bits.append(f"What you were doing: {task_title[:240]}.")
            if summary and failed:
                bits.append(f"Failure: {summary[:300]}.")
                # The 300-char cap can chop the file-access remedy off the end
                # of the summary, so hand the model the lever explicitly. The
                # deterministic guarantee lives below (_failed_note_with_policy_remedy);
                # this only helps the sentence read as one thought.
                remedy = file_access_refusal_remedy(summary)
                if remedy:
                    bits.append(
                        "The failure was a file-access POLICY refusal and the user "
                        "controls the setting. Include this exact sentence in your "
                        f"reply: {remedy}"
                    )
            # A device-action ask that yields ANY control script (.ps1/.sh/.py/…)
            # is a built bridge — the physical action did NOT happen. Requiring
            # ALL artifacts to be scripts wrongly cleared the flag when the real
            # deliverable bundled setup docs (SETUP.md/SETUP.pdf) with the script,
            # so Thomas falsely announced "the kitchen lights are off." (live 2026-07-21)
            built_bridge = bool(
                artifact_names
                and not failed
                and _DEVICE_ACTION_RE.search(task_title or "")
                and any(_SCRIPT_ARTIFACT_RE.search(name or "") for name in artifact_names)
            )
            if artifact_names and not failed:
                bits.append("The complete list of files it produced is: " + ", ".join(artifact_names) + ".")
                bits.append(
                    "Automatic checks confirmed those files exist and open; the content was "
                    "NOT separately checked against the user's exact request, so do not claim "
                    "the result was verified or tested beyond that."
                )
                bits.append(
                    "Mention every artifact in that list and no other deliverable. "
                    "Never claim a sibling item is missing. Refer to each file by name only — do "
                    "NOT write markdown links, URLs, or file paths; the interface attaches the "
                    "downloads for the user."
                )
            if built_bridge:
                bits.append(
                    "IMPORTANT: this task ASKED for a real-world action, but the deliverable is a "
                    "CONTROL/BRIDGE the worker BUILT — the physical action has NOT been performed and "
                    "no real device or account was touched. In one or two sentences, say you built a "
                    "working control for it and name the ONE thing the user must connect to run it "
                    "(e.g. their hub URL + access token). NEVER say the action happened "
                    "(do NOT say the lights are off, the message was sent, etc.)."
                )
            else:
                bits.append(
                    "In one or two short sentences, proactively tell the user it is done and what is ready."
                    if not failed
                    else (
                        "In one or two short sentences, be precise about where it stands: if the "
                        "failure text shows files WERE produced, say the result exists but a step "
                        "failed along the way so you can't fully vouch for it, and offer to "
                        "double-check or redo it. Never say nothing was done when files were made. "
                        "If nothing was produced, say it plainly and offer another run."
                    )
                )
            note = await _generate_note(llm, system, " ".join(bits))
            # Only an ABSENT note falls back to a template. Thomas's own sentence is
            # never thrown away for what it says.
            #
            # It used to be. Two filters ran over the model's note and replaced the
            # whole thing on a match, and both resolved toward the cheerful claim:
            #
            #   _UNSUPPORTED_GAP_CLAIM_RE matched ordinary honest English -- "still
            #   needs to", "not yet", "isn't complete". It was meant to catch a
            #   fabricated gap, but a fabricated gap and a REAL one read identically,
            #   and "verified" upstream never meant "everything asked for was made"
            #   (chat_delegation_artifact_verification.py opens with `del prompt`; it
            #   only checks the files that were made are real). So a run that produced
            #   two of three requested files, and said so truthfully, had that sentence
            #   deleted and was announced as "I have a verified result ready."
            #
            #   missing_name required every artifact filename to appear verbatim, while
            #   the prompt above asks for "one or two short sentences". Past about three
            #   files those instructions cannot both be met, and a live-repo run lists
            #   every changed file -- so good prose was discarded for naming the work
            #   instead of reciting filenames.
            #
            # Naming the files is still worth having, so it is APPENDED when the note
            # mentions none of them. Adding a fact is not the same as overruling the
            # sentence, and the artifact cards are attached below regardless.
            # The template must not outclaim the checks. "I have a verified
            # result ready" shipped an unwinnable game (gauntlet g-fieldgoal):
            # what actually ran was existence/render verification, which never
            # reads the ask, so the fallback names exactly that and no more.
            if not note:
                if failed:
                    note = f"I couldn't finish {task_title}. I can take another run at it."
                elif artifact_names:
                    note = (
                        f"Done — {task_title}: "
                        + ", ".join(f"`{name}`" for name in artifact_names)
                        + ". The files exist and open; I didn't separately check them "
                        "against your exact ask."
                    )
                else:
                    note = (
                        f"Done — {task_title}. Automatic checks passed; I didn't "
                        "separately check the result against your exact ask."
                    )
            elif artifact_names and not any(
                name.casefold() in note.casefold() for name in artifact_names
            ):
                note = note.rstrip() + " Ready: " + ", ".join(f"`{n}`" for n in artifact_names) + "."
        if failed:
            # A refused write's remedy sentence must survive into the sentence
            # the user actually reads — the LLM above is asked for "one or two
            # short sentences" from a truncated summary and reliably drops it
            # (measured live, exec-c3adbfcfa341 2026-08-07). Additive only.
            note = _failed_note_with_policy_remedy(note, summary)
        # Drop any broken sandbox/local-path links the model inlined; the real
        # deliverable is attached below as an artifact card. (Same hygiene as the
        # classic AgentLoop and the V2 orchestrator reply paths.)
        note = strip_sandbox_links(note)
        conversation = conversation.append_message("assistant", note, metadata={"announce": exec_id})
        await session_store.save(sid, conversation, SessionMeta(session_id=sid), force=True)
        task_bot_runtime.update_execution(
            exec_id,
            reported_to_chat_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        # Return the artifacts so the "here it is" bubble itself carries the
        # result — the user sees Thomas present it in the same reply, once, and
        # a playable/renderable one pops open. Reuse the delegation normalizer
        # so each artifact has a real preview URL + kind (raw proof.artifacts
        # carries neither). (Calvin, 2026-07-20.)
        art_payload = []
        if not failed:
            try:
                from thomas.server.chat_delegation_session import _normalize_record

                normalized = _normalize_record(row)
                art_payload = [
                    {
                        "name": str(a.get("name") or a.get("path") or ""),
                        "url": str(a.get("url") or ""),
                        "kind": str(a.get("kind") or ""),
                    }
                    for a in (normalized.get("artifacts") or [])
                    if isinstance(a, dict) and (a.get("url") or a.get("name"))
                ]
            except (ImportError, KeyError, TypeError, ValueError):
                art_payload = []
        return web.json_response({"ok": True, "message": note, "artifacts": art_payload})
    except (KeyError, LookupError, RuntimeError, OSError, TypeError, ValueError) as exc:
        log.debug("announce failed for %s/%s: %s", sid, exec_id, exc, exc_info=True)
        return web.json_response({"ok": False, "error": "exception"}, status=500)


__all__ = [
    "_announce_llm",
    "_announcement_lock_for",
    "_generate_note",
    "_handle_announce_delegation_locked",
    "handle_announce_delegation",
]
