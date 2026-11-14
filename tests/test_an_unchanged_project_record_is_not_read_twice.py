"""The project list reads a record in full once, then only when its file changes.

On 2026-11-05 the record cap was lifted so a long-running team stays listed, and the first scan afterwards read more
than 3 GB and was still unfinished after 17 minutes. Every refresh did the same again. A record that has not changed
since the last scan is now taken from memory.
"""

from __future__ import annotations

import json
from pathlib import Path

from thomas.server.routes import self_project_listing_cache as listing


def _record(folder: Path, cid: str, text: str = "hello") -> Path:
    path = folder / f"{cid}.json"
    path.write_text(
        json.dumps(
            {
                "id": cid,
                "title": "t",
                "thomas_project": {"execution_id": f"exec-{cid}"},
                "settings": {},
                "turns": [{"role": "user", "text": text}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _count_reads(monkeypatch) -> list[int]:
    reads: list[int] = []
    real = listing._ProjectJSON.read

    def counting(self):
        reads.append(1)
        return real(self)

    monkeypatch.setattr(listing._ProjectJSON, "read", counting)
    return reads


def test_an_unchanged_record_is_parsed_once(tmp_path, monkeypatch):
    listing._PARSED.clear()
    _record(tmp_path, "a")
    _record(tmp_path, "b")
    reads = _count_reads(monkeypatch)

    first = listing.read_project_records(tmp_path)
    second = listing.read_project_records(tmp_path)

    assert [c["id"] for c in first] == [c["id"] for c in second] == ["a", "b"]
    assert len(reads) == 2, "the second scan must not parse either record again"


def test_a_changed_record_is_parsed_again(tmp_path, monkeypatch):
    listing._PARSED.clear()
    _record(tmp_path, "a")
    reads = _count_reads(monkeypatch)
    listing.read_project_records(tmp_path)

    _record(tmp_path, "a", text="a much longer message than before")
    again = listing.read_project_records(tmp_path)

    assert len(reads) == 2
    assert again[0]["turns"][0]["text"].startswith("a much longer")


def _parse(record, *, whole, chunk):
    import io

    old = listing._READ_CHUNK
    listing._READ_CHUNK = chunk
    try:
        return listing._ProjectJSON(io.BytesIO(json.dumps(record).encode()), whole=whole).read()
    finally:
        listing._READ_CHUNK = old


def test_a_long_string_crossing_a_read_boundary_is_read_whole_or_tailed():
    """A string longer than one read piece used to be refused ("control character in string")."""
    text = ('x "q" y\n' * 40) + "END"
    record = {"id": "a", "turns": [{"role": "agent", "text": text, "status": "done"}]}
    for chunk in (3, 5, 7, 64, 65536):
        got = _parse(record, whole=True, chunk=chunk)
        assert got["turns"][0]["status"] == "done", chunk
        assert got["turns"][0]["text"].endswith("END"), chunk


def test_a_long_user_message_keeps_its_prefix_and_is_still_checked_after_it(tmp_path):
    long_text = "p" * 300 + ("\\n" * 5000)
    ok = '{"id":"a","turns":[{"role":"user","text":"' + long_text + '"}]}'
    got = listing._ProjectJSON(__import__("io").BytesIO(ok.encode())).read()
    assert got["turns"][0]["text"] == "p" * 256

    bad = '{"id":"a","turns":[{"role":"user","text":"' + "p" * 300 + '\\q"}]}'
    try:
        listing._ProjectJSON(__import__("io").BytesIO(bad.encode())).read()
    except ValueError:
        pass
    else:
        raise AssertionError("an invalid escape after the kept prefix must still be refused")


def test_a_caller_changing_its_copy_does_not_change_the_next_scan(tmp_path):
    listing._PARSED.clear()
    _record(tmp_path, "a")
    first = listing.read_project_records(tmp_path)
    first[0]["title"] = "changed by a caller"
    first[0]["turns"].clear()

    second = listing.read_project_records(tmp_path)

    assert second[0]["title"] == "t"
    assert len(second[0]["turns"]) == 1
