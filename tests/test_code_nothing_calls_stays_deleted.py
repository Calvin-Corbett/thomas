"""Code that nothing called is gone, and stays gone.

On dev af2be66f (2026-10-10) nothing imported or ran any module below: no
import, no ``python -m`` entry point, no importlib string, no tool manifest or
route table entry. Some were re-export shims for a module that had moved
(``thomas/server/model_auth_health.py`` for ``thomas.core.model_auth_health``,
``thomas/server/delegation_emitter.py`` for
``thomas.server.chat_delegation_emitter``); ``thomas/server/live_repo_tracking.py``
was a stale copy of ``thomas/server/chat_delegation_live_repo.py``; the rest
were generated and never wired. ``app_provisioning`` and ``approvals`` had no
caller but their own tests (``approvals`` held a one-line placeholder and the
``thomas/approvals`` shim re-exporting it).

A deletion a merge can silently undo is not a deletion, so these assertions are
the record: nothing stands at any removed path, no removed module can be
imported, nothing under ``thomas/`` or ``tests/`` still cites one, the
marketplace manifest lists only subpackages that exist, and the server still
imports without loading any of them.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_THIS = Path(__file__).resolve()

_REMOVED_PATHS = (
    "thomas/integrations/slack/channels.py",
    "thomas/integrations/slack/users.py",
    "thomas/integrations/slack/files.py",
    "thomas/integrations/notion/rich_text.py",
    "thomas/tray_agent/dirty_state_monitor.py",
    "thomas/server/routes/observability_integration_example.py",
    "thomas/server/INTEGRATION_STEP.txt",
    "thomas/intake/hotkey.py",
    "thomas/intake/__init__.py",
    "thomas/intake/api.py",
    "thomas/intake/tools.py",
    "thomas/intake/clipboard_watcher.py",
    "tools/apply_feature_14.py",
    "tools/install_feature_15_conversation_search.py",
    "thomas/server/model_auth_health.py",
    "thomas/server/live_repo_tracking.py",
    "thomas/server/delegation_emitter.py",
    "thomas/core/safe_pickle.py",
    "thomas/chat/module_context.py",
    "thomas/plugins_registry/STATUS.md",
    "thomas/plugins_registry/api_keys.json",
    "thomas/plugins_registry/reports.json",
    "thomas/marketplace/app_provisioning/__init__.py",
    "thomas/marketplace/app_provisioning/auth.py",
    "thomas/marketplace/app_provisioning/database.py",
    "thomas/marketplace/app_provisioning/payments.py",
    "thomas/marketplace/approvals/AGENTS.md",
    "thomas/marketplace/approvals/STATUS.md",
    "thomas/marketplace/approvals/__init__.py",
    "thomas/approvals/__init__.py",
    "tests/test_app_auth.py",
    "tests/test_app_database.py",
    "tests/test_app_payments.py",
)

_REMOVED_MODULES = (
    "thomas.integrations.slack.channels",
    "thomas.integrations.slack.users",
    "thomas.integrations.slack.files",
    "thomas.integrations.notion.rich_text",
    "thomas.tray_agent.dirty_state_monitor",
    "thomas.server.routes.observability_integration_example",
    "thomas.intake.hotkey",
    "thomas.intake",
    "thomas.server.model_auth_health",
    "thomas.server.live_repo_tracking",
    "thomas.server.delegation_emitter",
    "thomas.core.safe_pickle",
    "thomas.chat.module_context",
    "thomas.marketplace.app_provisioning",
    "thomas.marketplace.approvals",
    "thomas.approvals",
)

# Dotted names, repository paths, and names only the removed code used. A
# token matches only as a whole name: ``thomas.server.chat_delegation_emitter``
# does not cite ``thomas.server.delegation_emitter``.
_CITATIONS = (
    *_REMOVED_MODULES,
    *(path.removesuffix(".py") for path in _REMOVED_PATHS if path.startswith("thomas/")),
    "thomas/plugins_registry",
    "thomas/approvals",
    "SlackChannels",
    "SlackUsers",
    "SlackFiles",
    "dirty_state_monitor",
    "observability_integration_example",
    "INTEGRATION_STEP.txt",
    "live_repo_tracking",
    "safe_pickle",
    "app_provisioning",
)
_CITATION_RE = re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(token) for token in _CITATIONS) + r")(?![\w])")
_SCANNED_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".js", ".html", ".cfg", ".ini"}

# Methods only SlackChannels, SlackUsers and SlackFiles defined. The Slack
# README and examples may not show a call to one.
_REMOVED_SLACK_METHODS = (
    "archive_channel", "clear_status", "create_channel", "delete_file", "download_file",
    "get_channel_history", "get_channel_info", "get_display_name", "get_file_info", "get_file_name",
    "get_file_preview", "get_file_size", "get_file_type", "get_file_url", "get_presence", "get_user",
    "get_user_avatar", "get_user_by_email", "get_user_department", "get_user_email", "get_user_title",
    "get_users_in_team", "invite_users", "is_app_user", "is_bot_user", "is_document_file", "is_image_file",
    "is_text_file", "is_user_active", "join_channel", "leave_channel", "list_all_channels", "list_all_members",
    "list_all_users", "list_channels", "list_files", "list_members", "list_users", "rename_channel",
    "search_users", "set_presence", "set_purpose", "set_status", "set_topic", "unarchive_channel", "upload_file",
)  # fmt: skip
_SLACK_DOCS = ("thomas/integrations/slack/README.md", "thomas/integrations/slack/EXAMPLES.md")


def _importable_here(name: str) -> bool:
    """True when ``import name`` would load source from this tree.

    A folder left holding only ``__pycache__`` is a namespace package with no
    origin, and counts as gone. A spec from outside this tree counts as gone
    too: an editable install of another checkout answers for a direct child of
    ``thomas`` that this tree no longer has, and that file is not this tree's.
    """
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        return False
    if spec is None or spec.origin in (None, "namespace"):
        return False
    return Path(spec.origin).resolve().is_relative_to(_ROOT)


def test_nothing_stands_at_any_removed_path() -> None:
    present = [relative for relative in _REMOVED_PATHS if (_ROOT / relative).exists()]
    assert not present, (
        "Files this change deleted exist again. They were removed because nothing called them; "
        "bringing one back needs a caller and a test, not a merge: " + ", ".join(present)
    )


def test_a_removed_module_cannot_be_imported() -> None:
    importable = [name for name in _REMOVED_MODULES if _importable_here(name)]
    assert not importable, "removed modules that still import: " + ", ".join(importable)


def test_nothing_under_thomas_or_tests_cites_a_removed_module() -> None:
    cited: list[str] = []
    scanned = 0
    for top in ("thomas", "tests"):
        for path in sorted((_ROOT / top).rglob("*")):
            if path.suffix not in _SCANNED_SUFFIXES or "__pycache__" in path.parts or path == _THIS:
                continue
            if not path.is_file():
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _CITATION_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                cited.append(f"{path.relative_to(_ROOT).as_posix()}:{line}: {match.group(0)}")
    assert scanned > 1000, f"scanned only {scanned} files; the walk is not reading the tree"
    assert not cited, "citations of removed code:\n" + "\n".join(cited)


def test_the_slack_docs_call_no_method_only_the_removed_modules_had() -> None:
    calls = re.compile(r"\.(" + "|".join(_REMOVED_SLACK_METHODS) + r")\(")
    found = []
    for relative in _SLACK_DOCS:
        text = (_ROOT / relative).read_text(encoding="utf-8")
        found += [f"{relative}: .{match.group(1)}(" for match in calls.finditer(text)]
    assert not found, "the Slack docs show calls to methods nothing defines:\n" + "\n".join(found)


def test_the_marketplace_manifest_lists_only_subpackages_that_exist() -> None:
    marketplace = _ROOT / "thomas" / "marketplace"
    modules = json.loads((marketplace / "MANIFEST.json").read_text(encoding="utf-8"))["modules"]
    missing = sorted(name for name in modules if not (marketplace / name / "__init__.py").is_file())
    assert not missing, "MANIFEST.json lists subpackages that do not exist: " + ", ".join(missing)

    status = (marketplace / "STATUS.md").read_text(encoding="utf-8")
    count = re.search(r"over (\d+) subpackages", status)
    assert count is not None, "STATUS.md no longer says how many subpackages it covers"
    assert int(count.group(1)) == len(modules), (
        f"STATUS.md says {count.group(1)} subpackages, MANIFEST.json lists {len(modules)}"
    )


def test_the_server_imports_and_loads_none_of_them() -> None:
    app = importlib.import_module("thomas.server.app")
    assert app.__name__ == "thomas.server.app"
    loaded = [name for name in _REMOVED_MODULES if name in sys.modules]
    assert not loaded, "importing the server loaded removed modules: " + ", ".join(loaded)
