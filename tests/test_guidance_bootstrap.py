from pathlib import Path

from thomas.agent.guidance import load_purpose_brief


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_purpose_brief_uses_ordered_sources(tmp_path: Path) -> None:
    _write(
        tmp_path / "AGENTS.md",
        "# Agents\n- Startup guidance\n- Explain weird behavior with source file",
    )
    _write(tmp_path / "USER.md", "# User\n- Prefer direct action")
    _write(tmp_path / "SOUL.md", "# Soul\n- User benefit first")

    text, statuses = load_purpose_brief(root=tmp_path, max_chars=4_000)
    by_path = {s.path: s for s in statuses}

    assert "[AGENTS.md]" in text
    assert "[USER.md]" in text
    assert "[SOUL.md]" in text
    assert by_path["AGENTS.md"].exists is True
    assert by_path["AGENTS.md"].selected is True
    assert by_path["IDENTITY.md"].exists is False
    assert by_path["IDENTITY.md"].selected is False


def test_load_purpose_brief_truncates(tmp_path: Path) -> None:
    long_bullets = "\n".join(f"- line {i} with extra content for truncation behavior" for i in range(80))
    _write(tmp_path / "AGENTS.md", "# Agents\n" + long_bullets)

    text, statuses = load_purpose_brief(root=tmp_path, max_chars=220)

    assert text.endswith("...(purpose brief truncated)")
    assert len(text) <= 220
    by_path = {s.path: s for s in statuses}
    assert by_path["AGENTS.md"].selected is True


def test_readme_is_fallback_only(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n- Primary guidance")
    _write(tmp_path / "README.md", "# Readme\n- Backup guidance")

    text, statuses = load_purpose_brief(root=tmp_path, max_chars=4_000)
    by_path = {s.path: s for s in statuses}

    assert "[AGENTS.md]" in text
    assert "[README.md]" not in text
    assert by_path["README.md"].exists is True
    assert by_path["README.md"].selected is False


def test_readme_used_when_no_other_guidance(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Readme\n- Backup guidance")

    text, statuses = load_purpose_brief(root=tmp_path, max_chars=4_000)
    by_path = {s.path: s for s in statuses}

    assert "[README.md]" in text
    assert by_path["README.md"].selected is True
