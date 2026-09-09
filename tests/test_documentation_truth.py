from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "DOCUMENTATION_INDEX.md",
    ROOT / "thomas" / "README.md",
    ROOT / "docs" / "AGENT_FILE_EDITING_RULES.md",
    ROOT / "ARCHITECTURE.md",
)
RUNTIME_LOADER = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_loader.js"
RUNTIME_DIR = ROOT / "thomas" / "server" / "web" / "js" / "runtime"

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_RUNTIME_BLOCK_RE = re.compile(
    r"\bvar\s+RUNTIME_SCRIPTS\s*=\s*\[(?P<body>.*?)\]\s*;",
    re.DOTALL,
)
_RUNTIME_ENTRY_RE = re.compile(r"['\"]([^'\"]+\.js)['\"]")
_REPO_PATH_PREFIXES = ("docs/", "plans/", "scripts/", "tests/", "thomas/")

_ABSENT_PATH_ALIASES = {
    "thomas/agent/dispatch.py": ("thomas/agent/dispatch.py", "agent/dispatch.py"),
    "thomas/orchestrator/brain.py": ("thomas/orchestrator/brain.py", "orchestrator/brain.py"),
    "thomas/orchestrator/README.md": ("thomas/orchestrator/README.md", "orchestrator/README.md"),
    "thomas/specialists/README.md": ("thomas/specialists/README.md", "specialists/README.md"),
    "thomas/memory/episodic.py": ("thomas/memory/episodic.py", "memory/episodic.py"),
    "thomas/memory/episodic_store.py": (
        "thomas/memory/episodic_store.py",
        "memory/episodic_store.py",
    ),
    "thomas/memory/summarization.py": (
        "thomas/memory/summarization.py",
        "memory/summarization.py",
    ),
    "thomas/server/web/js/app_runtime_primary.mjs": (
        "thomas/server/web/js/app_runtime_primary.mjs",
        "server/web/js/app_runtime_primary.mjs",
        "app_runtime_primary.mjs",
    ),
}
_OBSOLETE_ARCHITECTURE_TOKENS = (
    "dispatch-first architecture",
    "CASUAL",
    "ACTIONABLE",
    "loop_part01",
    "chat_aiohttp_part01",
    "workboard_task_manager_part01",
    "components_parts/",
    "theme_rules.js",
    "docs/deletions/",
)
_LIVE_CHAT_TOKENS = (
    "thomas/server/routes/chat_v2_registration.py",
    "thomas/server/routes/chat_v2.py",
    "thomas/marketplace/orchestrator/brain.py",
    "send_task",
    "thomas/server/chat_delegation.py",
    "thomas/server/worker_runtime.py",
    "AgentLoop",
    "Task Manager",
    "model-owned",
)
_CLI_HELP_CASES = (
    (("--help",), "Usage: python -m thomas [OPTIONS] COMMAND [ARGS]...", "Plain `thomas` starts the interactive REPL"),
    (("repl", "--help"), "Usage: python -m thomas repl [OPTIONS]", "Start the interactive REPL"),
    (("serve", "--help"), "Usage: python -m thomas serve [OPTIONS]", "Run the web UI + HTTP API server"),
)
_ROUTE_REGISTRAR = "thomas/server/routes/chat_v2_registration.py"
_COMPAT_CHAT_ROUTE = "thomas/server/routes/chat_aiohttp.py"
_CONTRADICTORY_ROUTE_PATTERNS = (
    re.compile(r"(?:/api/chat|/api/v2/chat)[^\n]{0,120}\broutes?\s+in\s+`thomas/server/routes/chat_aiohttp\.py`"),
    re.compile(r"`thomas/server/routes/chat_aiohttp\.py`[^\n]{0,80}\b(?:registers|handles|owns)\b"),
)
_FROZEN_RUNTIME_PATTERNS = (
    re.compile(
        r"\b\d+\s+(?:(?:numbered|ordered|split)\s+)?"
        r"(?:classic\s+)?(?:runtime\s+)?(?:files|modules)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{3}\s*[-–]\s*\d{3}\b"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _document_corpus() -> str:
    return "\n".join(_read(path) for path in DOCUMENTS)


def _runtime_manifest() -> tuple[str, ...]:
    source = _read(RUNTIME_LOADER)
    match = _RUNTIME_BLOCK_RE.search(source)
    assert match is not None, "RUNTIME_SCRIPTS manifest was not found"
    entries = tuple(_RUNTIME_ENTRY_RE.findall(match.group("body")))
    assert entries, "RUNTIME_SCRIPTS manifest contained zero JavaScript entries"
    return entries


def _tracked_runtime_names() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", RUNTIME_DIR.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {Path(line.strip()).name for line in completed.stdout.splitlines() if line.strip().endswith(".js")}


def test_onboarding_markdown_links_resolve() -> None:
    checked: list[tuple[str, str]] = []
    broken: list[tuple[str, str]] = []

    for document in DOCUMENTS:
        for raw_target in _MARKDOWN_LINK_RE.findall(_read(document)):
            target = raw_target.partition("#")[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            checked.append((document.relative_to(ROOT).as_posix(), target))
            if not (document.parent / target).resolve().exists():
                broken.append(checked[-1])

    assert checked, f"scanned {len(DOCUMENTS)} documents but found zero local links"
    assert not broken, (
        f"scanned {len(DOCUMENTS)} documents and {len(checked)} local links; broken destinations: {broken}"
    )


def test_repo_relative_paths_cited_in_code_spans_exist() -> None:
    checked: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []

    for document in DOCUMENTS:
        for raw_value in _CODE_SPAN_RE.findall(_read(document)):
            value = raw_value.strip()
            if not value.startswith(_REPO_PATH_PREFIXES) or any(character.isspace() for character in value):
                continue
            checked.append((document.relative_to(ROOT).as_posix(), value))
            if any(character in value for character in "*?["):
                exists = any(ROOT.glob(value))
            else:
                exists = (ROOT / value.rstrip("/")).exists()
            if not exists:
                missing.append(checked[-1])

    assert checked, f"scanned {len(DOCUMENTS)} documents but found zero repo-relative path citations"
    assert not missing, (
        f"scanned {len(DOCUMENTS)} documents and {len(checked)} repo-relative path citations; missing paths: {missing}"
    )


def test_onboarding_docs_name_live_model_owned_chat_flow() -> None:
    corpus = _document_corpus()
    code_spans = set(_CODE_SPAN_RE.findall(corpus))
    stale_paths = [
        canonical
        for canonical, aliases in _ABSENT_PATH_ALIASES.items()
        if any(alias in code_spans for alias in aliases)
    ]
    stale_architecture = [token for token in _OBSOLETE_ARCHITECTURE_TOKENS if token in corpus]
    missing = [token for token in _LIVE_CHAT_TOKENS if token not in corpus]

    assert not (stale_paths or stale_architecture), (
        f"scanned {len(DOCUMENTS)} documents for {len(_ABSENT_PATH_ALIASES)} absent paths "
        f"and {len(_OBSOLETE_ARCHITECTURE_TOKENS)} stale architecture tokens; "
        f"found paths={stale_paths}, architecture={stale_architecture}"
    )
    assert not missing, (
        f"scanned {len(DOCUMENTS)} documents for {len(_LIVE_CHAT_TOKENS)} live chat anchors; missing: {missing}"
    )


def test_documented_cli_surfaces_are_click_registered() -> None:
    corpus = _document_corpus()
    assert "`thomas`" in corpus
    assert "`thomas repl`" in corpus
    assert "`thomas serve`" in corpus
    assert "`thomas cli" not in corpus
    assert "`thomas server`" not in corpus

    failures: list[str] = []
    for arguments, usage, description in _CLI_HELP_CASES:
        completed = subprocess.run(
            [sys.executable, "-m", "thomas", *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        output = completed.stdout + completed.stderr
        if completed.returncode != 0 or usage not in output or description not in output:
            failures.append(
                f"arguments={arguments!r}, exit={completed.returncode}, "
                f"usage={usage in output}, description={description in output}"
            )

    assert not failures, f"checked {len(_CLI_HELP_CASES)} Click help surfaces; failures: {failures}"


def test_each_onboarding_doc_names_the_exclusive_live_chat_registrar() -> None:
    failures: list[str] = []

    for document in DOCUMENTS:
        text = _read(document)
        normalized = " ".join(text.lower().split())
        label = document.relative_to(ROOT).as_posix()
        if _ROUTE_REGISTRAR not in text:
            failures.append(f"{label}: missing {_ROUTE_REGISTRAR}")
        if "exclusive live registrar" not in normalized:
            failures.append(f"{label}: does not name the exclusive live registrar")
        for pattern in _CONTRADICTORY_ROUTE_PATTERNS:
            if match := pattern.search(text):
                failures.append(f"{label}: contradictory route claim {match.group(0)!r}")
        if _COMPAT_CHAT_ROUTE in text and "compatibility" not in text.lower():
            failures.append(f"{label}: {_COMPAT_CHAT_ROUTE} is not identified as compatibility-only")

    assert not failures, (
        f"scanned {len(DOCUMENTS)} documents with {len(_CONTRADICTORY_ROUTE_PATTERNS)} "
        f"contradiction patterns; failures: {failures}"
    )


def test_editing_docs_include_safe_cross_platform_cache_and_restart_steps() -> None:
    for document in (
        ROOT / "DOCUMENTATION_INDEX.md",
        ROOT / "thomas" / "README.md",
        ROOT / "docs" / "AGENT_FILE_EDITING_RULES.md",
    ):
        text = _read(document)
        normalized = " ".join(text.lower().split())
        assert "Get-ChildItem -LiteralPath thomas" in text
        assert "find thomas -type f -name '*.pyc' -delete" in text
        assert "python.exe -m thomas serve" in text
        assert "python -m thomas serve" in text
        assert "do not kill every python process" in normalized


def test_runtime_docs_derive_membership_from_runtime_scripts() -> None:
    failures: list[str] = []

    for document in DOCUMENTS:
        text = _read(document)
        label = document.relative_to(ROOT).as_posix()
        if "RUNTIME_SCRIPTS" not in text:
            failures.append(f"{label}: missing RUNTIME_SCRIPTS")
        if "thomas/server/web/js/app_runtime_loader.js" not in text:
            failures.append(f"{label}: missing loader path")
        for pattern in _FROZEN_RUNTIME_PATTERNS:
            if match := pattern.search(text):
                failures.append(f"{label}: frozen runtime snapshot {match.group(0)!r}")

    assert not failures, (
        f"scanned {len(DOCUMENTS)} documents with {len(_FROZEN_RUNTIME_PATTERNS)} "
        f"frozen-count patterns; failures: {failures}"
    )


def test_runtime_manifest_matches_tracked_runtime_javascript_one_to_one() -> None:
    manifest = _runtime_manifest()
    manifest_names = set(manifest)
    tracked_names = _tracked_runtime_names()
    disk_names = {path.name for path in RUNTIME_DIR.glob("*.js") if path.is_file()}
    duplicate_entries = sorted({name for name in manifest if manifest.count(name) > 1})
    missing_tracked = sorted(manifest_names - tracked_names)
    unlisted_tracked = sorted(tracked_names - manifest_names)
    missing_on_disk = sorted(manifest_names - disk_names)
    unlisted_on_disk = sorted(disk_names - manifest_names)

    assert not (duplicate_entries or missing_tracked or unlisted_tracked or missing_on_disk or unlisted_on_disk), (
        f"scanned {len(manifest)} manifest entries, {len(tracked_names)} tracked runtime JS files, "
        f"and {len(disk_names)} runtime JS files on disk; duplicates={duplicate_entries}, "
        f"missing_tracked={missing_tracked}, unlisted_tracked={unlisted_tracked}, "
        f"missing_on_disk={missing_on_disk}, unlisted_on_disk={unlisted_on_disk}"
    )
