"""Disk-persistent "My Stuff" registry for Forge Code build outputs.

When a Forge Code run produces a coherent DELIVERABLE -- a built HTML page/app, a
rendered doc, an image, a data file -- this module records it as a first-class,
openable entry so it survives the session as a durable thing in the app's "My
Stuff" section, not a diff that scrolls away.

The single gate is the existing artifact detector
(:func:`forge_code_store.detect_artifacts`): a run that only touched code (``.py``
etc.) yields NO descriptors, so :func:`register_from_run` returns ``None`` and
nothing is registered -- an ordinary code edit never fabricates a My Stuff entry.
A run that wrote a renderable output yields descriptors, and the FIRST one (the
detector promotes HTML to the front) becomes the entry's headline deliverable.

Each entry carries enough to open and trace it later:
  * a model-derived ``title`` (the originating conversation's title -- the build's
    name/purpose), falling back to the deliverable's filename when blank;
  * ``conversation_id`` + ``deep_link`` back to the originating Code conversation;
  * ``open_url`` -- the same-origin, sandboxed artifact-preview URL the transcript
    already serves the file from, so "Open" lands on the REAL built file;
  * ``kind``/``thumbnail`` so the UI can show an image preview or a kind glyph.

All reads are defensive: a missing or corrupt registry yields ``[]`` rather than
raising, and registration never propagates an exception to the caller (a build's
success must never hinge on bookkeeping).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from thomas.forge.anvil import forge_code_store

logger = logging.getLogger(__name__)

# Cap the registry so a long-lived install can never grow it without bound; the
# newest deliverables win.
_MAX_DELIVERABLES = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def deliverables_path(root: str | Path) -> Path:
    """Return the registry file path, creating its parent directory if needed.

    Lives beside the conversation store under ``.thomas/evolve/agent`` so the
    Forge Code state is self-contained.
    """
    base = Path(root) / ".thomas" / "evolve" / "agent"
    base.mkdir(parents=True, exist_ok=True)
    return base / "deliverables.json"


def _read(root: str | Path) -> list[dict]:
    path = deliverables_path(root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        logger.debug("forge code deliverables read failed (non-fatal): %s", path, exc_info=True)
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get("deliverables")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _write(root: str | Path, entries: list[dict]) -> None:
    path = deliverables_path(root)
    path.write_text(
        json.dumps({"version": 1, "deliverables": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _artifact_url(conversation_id: str, file: str) -> str:
    """Build the same-origin artifact-preview URL the transcript already uses.

    Mirrors the per-segment encoding of the front-end ``artifactUrl`` helper so a
    nested path (``site/index.html``) keeps its slashes while each segment is
    escaped -- the URL resolves to the exact file the artifact route serves.
    """
    segs = [quote(s, safe="") for s in str(file or "").split("/") if s != ""]
    return f"/api/evolve/agent/artifact/{quote(str(conversation_id or ''), safe='')}/" + "/".join(segs)


def _deliverable_id(conversation_id: str, file: str) -> str:
    digest = hashlib.sha1(f"{conversation_id}|{file}".encode()).hexdigest()[:10]
    return f"del_{digest}"


def register_from_run(
    root: str | Path,
    *,
    conversation_id: str,
    changed_files: list[str] | None,
    title: str = "",
    model: str = "",
) -> dict | None:
    """Register the run's deliverable in "My Stuff"; return the entry, or None.

    Returns ``None`` -- and writes nothing -- when the run produced no renderable
    output (a code-only edit): the detector decides, so an ordinary edit is never
    fabricated into a My Stuff entry. Otherwise the headline artifact (HTML-first,
    per the detector's ordering) becomes a persisted, openable entry keyed by
    ``conversation_id`` + the primary file, so re-running the same build UPDATES
    its entry instead of duplicating it.

    Fully defensive: any failure is logged and swallowed (returns ``None``) so a
    bad write can never crash the build or lose the run.
    """
    try:
        cid = str(conversation_id or "").strip()
        if not cid:
            return None
        artifacts = forge_code_store.detect_artifacts(changed_files)
        primary = forge_code_store.primary_artifact(artifacts)
        if not primary:
            return None  # code-only run -> no deliverable, no entry

        file = str(primary.get("file") or "")
        kind = str(primary.get("kind") or "")
        clean_title = str(title or "").strip() or (file.rsplit("/", 1)[-1] if file else "Untitled build")
        open_url = _artifact_url(cid, file)
        now = _now_iso()
        entry = {
            "id": _deliverable_id(cid, file),
            "title": clean_title,
            "kind": kind,
            "file": file,
            # The full renderable set this run produced, so a multi-file build keeps
            # every preview-able output, not just the headline one.
            "artifacts": artifacts,
            "conversation_id": cid,
            # Deep-link back to the originating Code conversation (consumed by the
            # Forge Code surface to re-open + resume that transcript).
            #
            # NOT FIXED, MEASURED 2026-07-28: this link currently goes nowhere.
            # Its only consumer is `maybeOpenForgeCodeDeepLink` in
            # web/js/runtime/039_module_rendering_dispatch_02.js, which is
            # loaded by `app_runtime_loader.js` -- and `/` now serves the
            # unified chat shell, whose 13 script tags do not include that
            # loader. Loading `/?forge_code=<cid>` live: the param is still in
            # the URL afterwards (that consumer strips it first thing, so it
            # never ran), `forgeShowSide` and `forgeCodeOpenConversation` are
            # both `undefined`, `data-surface-mode` stays `chat`, and no Code
            # turn renders. The consumer also targets the retired Evolution
            # shell (`setSidebarNavMode('evolution')`), not the Chat/Code/Work
            # mode switcher that replaced it.
            #
            # Left as-is deliberately rather than half-rewired: the honest fix
            # is for the unified shell to read this param and drive the `code`
            # mode adapter, which is a change to shell boot order, and a
            # guessed version would be a new kind of wrong. The field is still
            # recorded because the id in it is correct -- only the consumer is
            # missing.
            "deep_link": f"/?forge_code={quote(cid, safe='')}",
            "open_url": open_url,
            # An image is its own thumbnail; other kinds fall back to a kind glyph
            # chosen by the UI.
            "thumbnail": open_url if kind == "image" else "",
            "model": str(model or "").strip(),
            "created_at": now,
            "updated_at": now,
        }

        entries = _read(root)
        kept = [e for e in entries if e.get("id") != entry["id"]]
        if len(kept) != len(entries):
            # Preserve the original creation time across an update.
            for e in entries:
                if e.get("id") == entry["id"]:
                    entry["created_at"] = str(e.get("created_at") or now)
                    break
        kept.insert(0, entry)
        _write(root, kept[:_MAX_DELIVERABLES])
        return entry
    except Exception:  # noqa: BLE001 - registration must never crash a build
        logger.warning("forge code deliverable registration failed (non-fatal)", exc_info=True)
        return None


def _artifact_exists(root: str | Path, file: str) -> bool:
    """Return ``True`` when the deliverable's underlying built file still exists.

    A registered deliverable is just a registry row plus a path; the built file it
    points at can later be reverted, moved, or deleted, leaving the row DANGLING --
    its "Open" would then 404. This mirrors the artifact route's own resolution
    (resolve the relative path under the repo root and require a real file within
    it), so "exists here" means precisely "the artifact route would actually serve
    it". Fully defensive: any path error yields ``False`` rather than raising.
    """
    rel = str(file or "").replace("\\", "/").strip()
    if not rel:
        return False
    try:
        root_resolved = Path(root).resolve()
        target = (root_resolved / rel).resolve()
        return target.is_file() and target.is_relative_to(root_resolved)
    except (OSError, ValueError):
        return False


def list_deliverables(root: str | Path) -> list[dict]:
    """Return all registered deliverables, newest-updated first.

    Each entry is annotated with ``available`` -- ``True`` when its underlying
    built file still exists on disk, ``False`` when that file was since reverted,
    moved, or deleted (a dangling entry whose "Open" would 404). The entry is kept
    (its card greys rather than vanishing), and the UI guards "Open" on this flag,
    so a missing artifact degrades gracefully instead of throwing a console 404 /
    white screen. Live deliverables (``available`` true) still open exactly as
    before.
    """
    entries = _read(root)
    for e in entries:
        e["available"] = _artifact_exists(root, e.get("file") or "")
    entries.sort(key=lambda e: str(e.get("updated_at") or ""), reverse=True)
    return entries


def list_deliverables_across(catalog_root: str | Path, roots: Iterable[str | Path]) -> list[dict]:
    """Every registered deliverable across the project roots builds live in.

    ``register_from_run`` writes ``deliverables.json`` into the PROJECT a run
    worked in. Since every Code task now gets a folder of its own, that is
    almost never the catalog root -- so reading the catalog root alone answered
    with an empty list, and My Stuff showed nothing at all. Measured on a live
    workspace: 16 deliverables across 4 project roots, endpoint returned 0,
    including two apps built minutes before that both open and work. An empty
    list is indistinguishable from "you have not built anything", which is why
    nothing ever reported it.

    ``available`` is resolved per entry against the root it was READ from, not
    against the catalog -- judging a project's file from the catalog root would
    mark every live artifact dangling and grey out the whole Library.

    Deduplicated by id because the roots genuinely overlap: the catalog, the
    shared drawer and every registered project can name the same folder twice.
    The catalog root is included so a deliverable recorded there before tasks
    got their own folders is still listed.
    """

    merged: dict[str, dict] = {}
    for candidate in [catalog_root, *roots]:
        for entry in list_deliverables(candidate):
            key = str(entry.get("id") or "")
            if key and key not in merged:
                merged[key] = entry
    return sorted(merged.values(), key=lambda e: str(e.get("updated_at") or ""), reverse=True)
