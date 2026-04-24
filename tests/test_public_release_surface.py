from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    files: list[str] = []
    for line in raw.splitlines():
        rel = line.strip().replace("\\", "/")
        if rel and (ROOT / rel).exists():
            files.append(rel)
    return sorted(files)


def test_public_release_excludes_private_and_stale_surfaces() -> None:
    files = _tracked_files()
    blocked_prefixes = {
        ".codex/",
        "benchmarks/",
        "demo/",
        "scripts/" + "com" + "petitors/",
        "tests/" + "com" + "petitors/",
        "thomas/_archived/",
        "thomas/benchmarks/",
        "thomas/eval/",
        "thomas/" + "open" + "claw_compat/",
        "thomas/marketplace/" + "open" + "claw_compat/",
        "skills/" + "cloud" + "flare-deploy/",
        "skills/" + "thomas" + "-site-visual-proof/",
    }
    blocked_exact = {
        "MODULE_REGISTRY.md",
        "THOMAS_FEATURE_INVENTORY.md",
        "docs/PRE_PUBLIC_CLEANUP.md",
        "CLAUDE_CODE_GAP_ANALYSIS.md",
        "PLAN-UI-UPGRADE.md",
        "PROJECT_MANAGEMENT_RULES.md",
        "REPO_CANONICAL_RULES.md",
        "docs/OPEN" + "CLAW_PARITY.md",
        "docs/launch/LAUNCH_GATE_SCOREBOARD_2026-02-25.md",
        "docs/ops/agent_handoff_log.md",
        "docs/ops/module_audit_log.json",
        "docs/ops/repo_orphan_inventory.md",
        "docs/thomas-core-vs-marketplace-triage.md",
        "scripts/export_site_marketplace_snapshot.py",
    }

    violations = [
        path
        for path in files
        if path in blocked_exact or any(path.startswith(prefix) for prefix in blocked_prefixes)
    ]

    assert violations == []


def test_public_release_text_avoids_private_surface_terms() -> None:
    forbidden_terms = (
        "open" + "claw",
        "cloud" + "flare",
        "com" + "petitor",
        "thomas" + "devhub",
        "bobs" + "_chromebook",
        "calvinaustin" + "31",
        "for_" + "chatgpt_builds",
        "inbox/" + "_ready_to_integrate",
        "publish" + "-clean",
        "my " + "cousin",
    )
    skipped_suffixes = {
        ".gif",
        ".ico",
        ".jpg",
        ".jpeg",
        ".lock",
        ".pdf",
        ".png",
        ".pyc",
        ".woff",
        ".woff2",
        ".zip",
    }
    violations: list[tuple[str, str]] = []
    for rel in _tracked_files():
        path = ROOT / rel
        if path.suffix.lower() in skipped_suffixes or not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in forbidden_terms:
            if term.lower() in text:
                violations.append((rel, term))

    assert violations == []


def test_public_release_documents_status_and_local_networking() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/FUNCTIONALITY_INVENTORY.md" in readme
    assert "docs/NETWORKING_AND_FIREWALL.md" in readme

    run_ui = (ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")
    assert '[string]$BindHost = "127.0.0.1"' in run_ui

    networking = (ROOT / "docs" / "NETWORKING_AND_FIREWALL.md").read_text(encoding="utf-8")
    assert "127.0.0.1:8899" in networking
    assert "does not configure router port forwarding" in networking


def test_public_install_and_feature_docs_do_not_show_mojibake() -> None:
    public_paths = (
        "docs/FEATURE_MASTER_LIST.md",
        "install.cmd",
        "install.sh",
        "scripts/run-ui.ps1",
        "scripts/sync_feature_master_list.py",
    )
    mojibake_fragments = ("â", "Ã", "�")
    violations: list[tuple[str, str]] = []
    for rel in public_paths:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for fragment in mojibake_fragments:
            if fragment in text:
                violations.append((rel, fragment))

    assert violations == []
