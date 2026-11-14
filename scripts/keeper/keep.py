"""The keep: how a capture is written there (create-only) and how it comes back (into a new folder, hash-checked).

Every file is written to its final name with exclusive create, all of its bytes through that one handle, then read
back and hashed. Nothing in the keep is opened for writing a second time, renamed, appended to or removed; the keep's
access list denies all of that to you anyway (design R1). A capture is ``<id>.zip`` (files as found, their base
content and any staged-only content), ``<id>.bundle`` (commits dev lacks, when there are any) and ``<id>.json`` (the
manifest), written in that order, so a manifest only exists for a capture whose content is complete.

The archive is deterministic: the same files in the same order give the same bytes (fixed times and attributes).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .gitplace import _plain_folder, check_alternates, make_view
from .places import keeper_fs

FORMAT = "thomas-keeper-capture/1"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ID = re.compile(r"cap-(\d{4})(\d{2})\d{2}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
PATH_LIMIT = 400


class UnsafePath(ValueError):
    pass


class RestoreFailed(Exception):
    pass


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def is_text(data: bytes) -> bool:
    return b"\0" not in data


def normalise(data: bytes) -> bytes:
    """Design 5.1: a UTF-8 BOM removed, CRLF and CR made LF. Used only to compare, never to store."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def safe_rel(rel: str) -> str:
    """A relative path that cannot leave the folder it is written into, or ``UnsafePath``."""
    bad = not rel or len(rel) > PATH_LIMIT or rel.startswith("/") or any(c in rel for c in '\\:\0<>"|?*')
    for part in rel.split("/"):
        bad = bad or part in ("", ".", "..") or part.rstrip(" .") != part or any(ord(c) < 32 for c in part)
        bad = bad or part.split(".")[0].lower() in RESERVED
    if bad:
        raise UnsafePath(f"unsafe path: {rel!r}")
    return rel


def sha256_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class ArchiveWriter:
    """A zip built in the private work folder, entry by entry, with fixed times and attributes.

    ``guard(on_disk, incoming)`` runs before each entry is written (``incoming`` is its size before compression) and
    again after it (``incoming`` 0); whatever it raises stops the archive there. Closing twice is harmless.
    """

    def __init__(self, path: Path, guard: Callable[[int, int], None] | None = None) -> None:
        self.path, self.entries, self.guard = path, [], guard
        self._zip = zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6)

    @property
    def size(self) -> int:
        """Bytes the archive takes in the work folder so far."""
        return self._zip.fp.tell() if self._zip.fp is not None else self.path.stat().st_size

    def add(self, name: str, data: bytes, **facts) -> dict:
        safe_rel(name)
        if self.guard is not None:
            self.guard(self.size, len(data))
        info = zipfile.ZipInfo(name, ZIP_TIME)
        info.create_system, info.external_attr, info.compress_type = 0, 0, zipfile.ZIP_DEFLATED
        self._zip.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        entry = {"stored": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), **facts}
        self.entries.append(entry)
        if self.guard is not None:
            self.guard(self.size, 0)
        return entry

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> ArchiveWriter:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def new_capture_id(place_key: str, at: datetime) -> str:
    return f"cap-{at:%Y%m%dT%H%M%SZ}-{hashlib.sha256(place_key.encode()).hexdigest()[:8]}-{secrets.token_hex(2)}"


def month_folder(keep: Path, cap_id: str) -> Path:
    """``<keep>\\captures\\<yyyy-mm>``, from the date inside the capture id."""
    match = ID.fullmatch(cap_id)
    if not match:
        raise ValueError(f"not a capture id: {cap_id!r}")
    return Path(keep) / "captures" / f"{match.group(1)}-{match.group(2)}"


def write_new(dst: Path, src: Path | bytes) -> tuple[str, int]:
    """Create ``dst`` (it must not exist) with all of ``src`` through one handle, then read it back to check it."""
    digest, size = hashlib.sha256(), 0
    with open(dst, "xb") as out:  # exclusive create: the only handle that ever writes this file
        if isinstance(src, bytes):
            out.write(src)
            digest.update(src)
            size = len(src)
        else:
            with open(src, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    out.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        out.flush()
        os.fsync(out.fileno())
    if sha256_file(dst) != (digest.hexdigest(), size):
        raise OSError(f"{dst} does not read back as written")
    return digest.hexdigest(), size


def store_capture(keep: Path, manifest: dict, parts: dict[str, Path]) -> Path:
    """Write ``<id>.<ext>`` for each part, then ``<id>.json``; ``FileExistsError`` before anything if a name is taken."""
    folder = month_folder(keep, manifest["id"])
    folder.mkdir(parents=True, exist_ok=True)
    names = {ext: f"{manifest['id']}.{ext}" for ext in parts}
    taken = [n for n in [*names.values(), f"{manifest['id']}.json"] if os.path.lexists(folder / n)]
    if taken:
        raise FileExistsError(f"already in the keep: {taken}")
    for ext, src in parts.items():
        sha, size = sha256_file(src)
        key = "archive" if ext == "zip" else "bundle"
        manifest[key] = {**(manifest.get(key) or {}), "name": names[ext], "sha256": sha, "size": size}
    for ext, src in parts.items():
        if write_new(folder / names[ext], src)[0] != manifest["archive" if ext == "zip" else "bundle"]["sha256"]:
            raise OSError(f"{names[ext]} changed between hashing and writing")
    body = json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False).encode("utf-8")
    write_new(folder / f"{manifest['id']}.json", body)
    return folder / f"{manifest['id']}.json"


def load_manifest(keep: Path, cap_id: str) -> tuple[Path, dict]:
    path = month_folder(keep, cap_id) / f"{cap_id}.json"
    manifest = json.loads(path.read_bytes())
    if manifest.get("format") != FORMAT or manifest.get("id") != cap_id:
        raise RestoreFailed(f"{path} is not a v1 capture manifest for {cap_id}")
    return path, manifest


def restore(
    keep: Path,
    cap_id: str,
    dest: Path,
    *,
    git_path: str | None = None,
    main_objects: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Rebuild a capture's files (and commits) into a new, empty ``dest`` and check every hash."""
    path, manifest = load_manifest(keep, cap_id)
    dest = Path(os.path.abspath(dest))
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise RestoreFailed(f"{dest} is not a new, empty folder; restore writes only into one")
    report: dict = {"id": cap_id, "dest": str(dest), "dry_run": dry_run, "written": 0, "problems": []}
    if main_objects is not None:  # read through alternates: the same checks as any place's objects
        _plain_folder(keeper_fs(), Path(main_objects))
        check_alternates(keeper_fs(), Path(main_objects))
    archive = manifest.get("archive")
    if archive:
        zpath = path.parent / archive["name"]
        if sha256_file(zpath)[0] != archive["sha256"]:
            raise RestoreFailed(f"{zpath.name}: its sha256 does not match the manifest")
        expected = {e["stored"]: e["sha256"] for e in manifest["entries"]}
        with zipfile.ZipFile(zpath) as zipped:
            names = zipped.namelist()
            if sorted(names) != sorted(expected):
                raise RestoreFailed("the archive and its manifest list different files")
            try:
                [safe_rel(n) for n in names]
            except UnsafePath as exc:
                raise RestoreFailed(str(exc)) from exc
            report["would_write"] = sorted(names) if dry_run else None
            for name in [] if dry_run else sorted(names):
                data = zipped.read(name)
                target = dest.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "xb") as out:
                    out.write(data)
                report["written"] += 1
                if hashlib.sha256(data).hexdigest() != expected[name]:
                    report["problems"].append(f"{name}: sha256 does not match the manifest")
    bundle = manifest.get("bundle")
    if bundle:
        bpath = path.parent / bundle["name"]
        if sha256_file(bpath)[0] != bundle["sha256"]:
            raise RestoreFailed(f"{bpath.name}: its sha256 does not match the manifest")
        report["refs"] = []
        if not dry_run:
            if git_path is None:
                raise RestoreFailed("restoring commits needs --git")
            runner = make_view(git_path, dest, [main_objects] if main_objects else [], name="commits.git")
            runner.run("bundle", "verify", "--quiet", str(bpath))
            runner.run("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", str(bpath), "+refs/keep/*:refs/keep/*")
            for ref in bundle["refs"]:
                got = runner.text("rev-parse", "--verify", "--quiet", ref["view_ref"], check=False)
                report["refs"].append({**ref, "ok": got == ref["sha"]})
                if got != ref["sha"]:
                    report["problems"].append(f"{ref['name']}: restored {got or 'nothing'}, expected {ref['sha']}")
    report["ok"] = not report["problems"]
    return report
