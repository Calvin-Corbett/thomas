"""Compatibility surface for maintenance checkpoint helpers and CLI."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_cli = importlib.import_module("scripts.agent_maintenance_cli")
_core = importlib.import_module("scripts.agent_maintenance_core")
_helpers = importlib.import_module("scripts.agent_maintenance_helpers")
_services = importlib.import_module("scripts.agent_maintenance_services")
_window = importlib.import_module("scripts.agent_maintenance_window")

_build_parser = _cli._build_parser
_text_status = _cli._text_status
main = _cli.main

CommitResult = _core.CommitResult
DEFAULT_WORKBOARD = _core.DEFAULT_WORKBOARD
attempt_maintenance_checkpoint = _core.attempt_maintenance_checkpoint
commit_scoped_changes = _core.commit_scoped_changes

STATE_PATH_PREFIX = _helpers.STATE_PATH_PREFIX
_finalize_maintenance_payload = _helpers._finalize_maintenance_payload
_isoformat = _helpers._isoformat
_parse_timestamp = _helpers._parse_timestamp
_preview_paths = _helpers._preview_paths
_state_root = _helpers._state_root
_suggest_claim_batch_command = _helpers._suggest_claim_batch_command
_suggest_claim_scopes = _helpers._suggest_claim_scopes
_suggest_workboard_claim_command = _helpers._suggest_workboard_claim_command
_utcnow = _helpers._utcnow
maintenance_audit_log_path = _helpers.maintenance_audit_log_path
maintenance_log_path = _helpers.maintenance_log_path
suggested_checkpoint_command = _helpers.suggested_checkpoint_command

DEFAULT_BATCH_MAX_FILES = _services.DEFAULT_BATCH_MAX_FILES
_batch_changed_lines = _services._batch_changed_lines
_checkpoint_batches = _services._checkpoint_batches
_git_status_paths = _services._git_status_paths
_group_retry_paths = _services._group_retry_paths
_normalize_repo_path = _services._normalize_repo_path
_path_matches_claim_scopes = _services._path_matches_claim_scopes
_resolve_active_claim_scopes = _services._resolve_active_claim_scopes
_split_checkpointable_paths = _services._split_checkpointable_paths
_split_claimed_paths = _services._split_claimed_paths
_split_growth_guard_batch = _services._split_growth_guard_batch
_split_ignored_paths = _services._split_ignored_paths

EVENT_CHECKPOINT_FAILED = _window.EVENT_CHECKPOINT_FAILED
EVENT_CHECKPOINT_SUCCEEDED = _window.EVENT_CHECKPOINT_SUCCEEDED
EVENT_TYPES = _window.EVENT_TYPES
load_maintenance_window = _window.load_maintenance_window
maintenance_quota_status = _window.maintenance_quota_status
record_maintenance_event = _window.record_maintenance_event
reset_maintenance_window = _window.reset_maintenance_window


if __name__ == "__main__":
    raise SystemExit(main())
