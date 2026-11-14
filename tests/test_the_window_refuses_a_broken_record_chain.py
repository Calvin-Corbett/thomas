"""Missing, reordered or relinked events cannot authorize continued window work."""

from __future__ import annotations

import json

import pytest
from scripts.cage import window_record as wr


@pytest.fixture
def record(tmp_path):
    result = wr.Record(tmp_path)
    result.event("window_opened", window_id="w")
    result.event("landing_intent", sid="self-a", commit="a" * 40)
    result.event("landed", sid="self-a", commit="a" * 40)
    return result


@pytest.mark.parametrize("damage", ["delete_first", "delete_middle", "rename", "prev", "seq", "name", "malformed"])
def test_chain_damage_is_torn_and_refuses_further_appends(record, damage):
    paths = sorted(record.root.glob("*.json"))
    if damage == "delete_first":
        paths[0].unlink()
    elif damage == "delete_middle":
        paths[1].unlink()
    elif damage == "rename":
        paths[1].rename(paths[1].with_name("00000004-landing_intent.json"))
    elif damage == "malformed":
        paths[1].write_text("{not json", encoding="utf-8")
    else:
        raw = json.loads(paths[1].read_text(encoding="utf-8"))
        raw[damage] = {"prev": "0" * 64, "seq": 4, "name": "refused"}[damage]
        raw["hash"] = wr._hash(raw)  # a self-consistent individual hash never repairs the chain
        paths[1].write_text(json.dumps(raw), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in record.root.glob("*.json")}
    assert any(row.get("torn") for row in record.events())
    assert record.usable()
    with pytest.raises(OSError, match="record"):
        record.event("window_closed", window_id="w")
    assert before == {path.name: path.read_bytes() for path in record.root.glob("*.json")}


def test_a_complete_chain_stays_append_only_and_usable(record):
    original = sorted(record.root.glob("*.json"))[0].read_bytes()
    assert not record.usable() and not any(row.get("torn") for row in record.events())
    added = record.event("window_closed", window_id="w")
    assert added["seq"] == 4 and added["prev"] == record.events()[-2]["hash"]
    assert sorted(record.root.glob("*.json"))[0].read_bytes() == original
