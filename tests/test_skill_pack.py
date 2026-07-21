"""Tests for portable skill capability packs (CAP-023)."""

from __future__ import annotations

import copy

import pytest

from thomas.skills.skill_pack import (
    PACK_SCHEMA_VERSION,
    PortableSkill,
    SkillPackError,
    export_pack,
    import_pack,
    select_relevant,
)


def _sample_skill() -> PortableSkill:
    return PortableSkill(
        name="pdf-forms",
        description="Fill and extract fields from PDF forms.",
        body="Use this skill to parse PDF forms and populate fields.",
        version="2.3.1",
        keywords=["pdf", "forms", "extraction"],
        metadata={"origin": "builtin", "author": "thomas"},
    )


# --- Versioned export ------------------------------------------------------


def test_export_produces_versioned_pack_with_hash():
    pack = export_pack(_sample_skill())
    assert pack["schema_version"] == PACK_SCHEMA_VERSION  # explicit schema version
    assert pack["skill_version"] == "2.3.1"  # skill's own version preserved
    assert pack["content_hash"].startswith("sha256:")  # content hash present
    assert pack["skill"]["name"] == "pdf-forms"


def test_export_is_deterministic():
    a = export_pack(_sample_skill())
    b = export_pack(_sample_skill())
    assert a == b
    assert a["content_hash"] == b["content_hash"]


def test_export_accepts_bundle_like_and_mapping_inputs():
    class _BundleLike:
        name = "shell-runner"
        description = "Run shell commands."
        body = "body text"
        metadata = {"version": "1.4.0", "keywords": ["shell", "exec"]}

    pack = export_pack(_BundleLike())
    assert pack["skill_version"] == "1.4.0"  # picked up from metadata
    assert pack["skill"]["keywords"] == ["shell", "exec"]

    mapping_pack = export_pack({"name": "m", "description": "d", "version": "0.9.0"})
    assert mapping_pack["skill_version"] == "0.9.0"


def test_export_rejects_nameless_skill():
    with pytest.raises(SkillPackError):
        export_pack({"description": "no name here"})


# --- Versioned import + round-trip -----------------------------------------


def test_import_round_trips_losslessly():
    original = _sample_skill()
    restored = import_pack(export_pack(original))
    assert restored == original  # dataclass equality => lossless


def test_import_validates_hash_and_version_together():
    pack = export_pack(_sample_skill())
    restored = import_pack(pack)
    assert restored.version == "2.3.1"
    assert restored.keywords == ["pdf", "forms", "extraction"]
    assert restored.metadata == {"origin": "builtin", "author": "thomas"}


def test_tampered_hash_is_rejected():
    pack = export_pack(_sample_skill())
    tampered = copy.deepcopy(pack)
    tampered["skill"]["body"] = "malicious injected body"  # payload changed, hash not
    with pytest.raises(SkillPackError, match="hash mismatch"):
        import_pack(tampered)


def test_tampered_skill_version_is_rejected():
    pack = export_pack(_sample_skill())
    tampered = copy.deepcopy(pack)
    tampered["skill_version"] = "9.9.9"  # hash covers skill_version
    with pytest.raises(SkillPackError, match="hash mismatch"):
        import_pack(tampered)


def test_unknown_newer_schema_major_is_rejected():
    pack = export_pack(_sample_skill())
    future = copy.deepcopy(pack)
    future["schema_version"] = "2.0"  # newer major than reader supports
    with pytest.raises(SkillPackError, match="Unsupported pack schema major 2"):
        import_pack(future)


def test_legacy_schema_major_is_rejected():
    pack = export_pack(_sample_skill())
    legacy = copy.deepcopy(pack)
    legacy["schema_version"] = "0.5"
    with pytest.raises(SkillPackError, match="Unsupported pack schema major 0"):
        import_pack(legacy)


def test_malformed_schema_version_is_rejected():
    pack = export_pack(_sample_skill())
    pack["schema_version"] = "not-a-version"
    with pytest.raises(SkillPackError, match="Malformed schema version"):
        import_pack(pack)


def test_import_requires_mapping_and_fields():
    with pytest.raises(SkillPackError):
        import_pack("not a dict")
    with pytest.raises(SkillPackError, match="schema_version"):
        import_pack({})
    with pytest.raises(SkillPackError, match="skill' payload"):
        import_pack({"schema_version": PACK_SCHEMA_VERSION})


# --- Default relevance selection -------------------------------------------


def _skills_for_ranking() -> list[PortableSkill]:
    return [
        PortableSkill(
            name="pdf-forms",
            description="Fill and extract fields from PDF forms.",
            keywords=["pdf", "forms"],
        ),
        PortableSkill(
            name="calendar",
            description="Schedule and manage calendar events.",
            keywords=["calendar", "events"],
        ),
        PortableSkill(
            name="spreadsheet",
            description="Read and write spreadsheet data.",
            keywords=["excel", "csv"],
        ),
    ]


def test_select_relevant_ranks_clearly_relevant_first():
    skills = _skills_for_ranking()
    ranked = select_relevant(skills, "extract fields from a pdf form", k=2)
    assert ranked[0].name == "pdf-forms"  # clearly-relevant skill ranked first
    assert len(ranked) == 1  # non-matching skills scored zero and are excluded


def test_select_relevant_is_deterministic():
    skills = _skills_for_ranking()
    first = select_relevant(skills, "pdf form extraction", k=3)
    second = select_relevant(skills, "pdf form extraction", k=3)
    assert [s.name for s in first] == [s.name for s in second]


def test_select_relevant_tie_break_is_stable_by_name():
    tied = [
        PortableSkill(name="zebra", keywords=["alpha"]),
        PortableSkill(name="apple", keywords=["alpha"]),
    ]
    ranked = select_relevant(tied, "alpha", k=2)
    assert [s.name for s in ranked] == ["apple", "zebra"]  # name-asc tie-break


def test_select_relevant_excludes_zero_score_skills():
    skills = _skills_for_ranking()
    ranked = select_relevant(skills, "pdf", k=5)
    names = {s.name for s in ranked}
    assert names == {"pdf-forms"}  # only the matching skill returned


def test_select_relevant_handles_empty_inputs():
    skills = _skills_for_ranking()
    assert select_relevant([], "pdf") == []  # no skills
    assert select_relevant(skills, "") == []  # empty query
    assert select_relevant(skills, "pdf", k=0) == []  # non-positive k
    assert select_relevant(None, "pdf") == []  # None skills
