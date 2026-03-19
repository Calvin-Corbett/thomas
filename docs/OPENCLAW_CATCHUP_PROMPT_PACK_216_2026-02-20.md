# Thomas Catch-Up Prompt Pack - 216 Prompts (2026-02-20)

This is the full prompt set requested for accelerated catch-up work.
This supersedes the smaller starter pack at `docs/OPENCLAW_CATCHUP_PROMPT_PACK_2026-02-20.md`.

Goal of this pack: close capability gaps tracked in `docs/OPENCLAW_GAP_CHANGELOG.md` using controlled parallel execution.

## Scale Plan

- Total prompts: 216
- Batch model: 27 batches x 8 prompts
- Recommended parallelism: 8 tabs at once, one batch at a time
- Merge rule: do not merge untested multi-prompt piles

## Global Prefix To Paste In Every ChatGPT Tab

```text
You are implementing features for Thomas at <repo_root>.

Hard constraints:
1) Do not copy OpenClaw branding, command names, internal identifiers, or docs text.
2) Use Thomas-native naming and architecture.
3) Edit only the files listed in Ownership.
4) Add tests for success and failure paths.
5) Keep changes production-safe and minimal.
6) Return unified diff, then test command list, then residual risks.
```

## Batch Legend

- B01-B06: Browser + Nodes only
- B07: Transition batch (end of Browser/Nodes + start of Messaging/Channels)
- B08-B12: Messaging + Channels only
- B13-B19: Plugins + Gateway/API
- B20-B22: Memory + Security + System + Approvals
- B23-B27: Tests + CI + Hardening

## Prompt P001 - Browser command registry scaffold
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p001_browser_command_registry_scaffold.py (new)
- thomas/browser/p001_browser_command_registry_scaffold.py (new)
- tests/prompt_pack/test_p001_browser_command_registry_scaffold.py (new)
- docs/openclaw_gap_runs/p001_browser_command_registry_scaffold.md (new)

Task:
- Implement: Browser command registry scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser command registry scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p001_browser_command_registry_scaffold.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P002 - Browser action navigate and open
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p002_browser_action_navigate_and_open.py (new)
- thomas/browser/p002_browser_action_navigate_and_open.py (new)
- tests/prompt_pack/test_p002_browser_action_navigate_and_open.py (new)
- docs/openclaw_gap_runs/p002_browser_action_navigate_and_open.md (new)

Task:
- Implement: Browser action navigate and open.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action navigate and open" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p002_browser_action_navigate_and_open.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P003 - Browser action click
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p003_browser_action_click.py (new)
- thomas/browser/p003_browser_action_click.py (new)
- tests/prompt_pack/test_p003_browser_action_click.py (new)
- docs/openclaw_gap_runs/p003_browser_action_click.md (new)

Task:
- Implement: Browser action click.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action click" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p003_browser_action_click.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P004 - Browser action type and press
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p004_browser_action_type_and_press.py (new)
- thomas/browser/p004_browser_action_type_and_press.py (new)
- tests/prompt_pack/test_p004_browser_action_type_and_press.py (new)
- docs/openclaw_gap_runs/p004_browser_action_type_and_press.md (new)

Task:
- Implement: Browser action type and press.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action type and press" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p004_browser_action_type_and_press.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P005 - Browser action hover and focus
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p005_browser_action_hover_and_focus.py (new)
- thomas/browser/p005_browser_action_hover_and_focus.py (new)
- tests/prompt_pack/test_p005_browser_action_hover_and_focus.py (new)
- docs/openclaw_gap_runs/p005_browser_action_hover_and_focus.md (new)

Task:
- Implement: Browser action hover and focus.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action hover and focus" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p005_browser_action_hover_and_focus.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P006 - Browser action scroll and scroll-into-view
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p006_browser_action_scroll_and_scroll_into_view.py (new)
- thomas/browser/p006_browser_action_scroll_and_scroll_into_view.py (new)
- tests/prompt_pack/test_p006_browser_action_scroll_and_scroll_into_view.py (new)
- docs/openclaw_gap_runs/p006_browser_action_scroll_and_scroll_into_view.md (new)

Task:
- Implement: Browser action scroll and scroll-into-view.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action scroll and scroll-into-view" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p006_browser_action_scroll_and_scroll_into_view.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P007 - Browser action wait conditions
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p007_browser_action_wait_conditions.py (new)
- thomas/browser/p007_browser_action_wait_conditions.py (new)
- tests/prompt_pack/test_p007_browser_action_wait_conditions.py (new)
- docs/openclaw_gap_runs/p007_browser_action_wait_conditions.md (new)

Task:
- Implement: Browser action wait conditions.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action wait conditions" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p007_browser_action_wait_conditions.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P008 - Browser action evaluate script
Batch: B01 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p008_browser_action_evaluate_script.py (new)
- thomas/browser/p008_browser_action_evaluate_script.py (new)
- tests/prompt_pack/test_p008_browser_action_evaluate_script.py (new)
- docs/openclaw_gap_runs/p008_browser_action_evaluate_script.md (new)

Task:
- Implement: Browser action evaluate script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser action evaluate script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p008_browser_action_evaluate_script.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P009 - Browser artifact screenshot
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p009_browser_artifact_screenshot.py (new)
- thomas/browser/p009_browser_artifact_screenshot.py (new)
- tests/prompt_pack/test_p009_browser_artifact_screenshot.py (new)
- docs/openclaw_gap_runs/p009_browser_artifact_screenshot.md (new)

Task:
- Implement: Browser artifact screenshot.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser artifact screenshot" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p009_browser_artifact_screenshot.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P010 - Browser artifact pdf export
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p010_browser_artifact_pdf_export.py (new)
- thomas/browser/p010_browser_artifact_pdf_export.py (new)
- tests/prompt_pack/test_p010_browser_artifact_pdf_export.py (new)
- docs/openclaw_gap_runs/p010_browser_artifact_pdf_export.md (new)

Task:
- Implement: Browser artifact pdf export.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser artifact pdf export" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p010_browser_artifact_pdf_export.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P011 - Browser artifact dom snapshot
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py (new)
- thomas/browser/p011_browser_artifact_dom_snapshot.py (new)
- tests/prompt_pack/test_p011_browser_artifact_dom_snapshot.py (new)
- docs/openclaw_gap_runs/p011_browser_artifact_dom_snapshot.md (new)

Task:
- Implement: Browser artifact dom snapshot.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser artifact dom snapshot" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p011_browser_artifact_dom_snapshot.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P012 - Browser artifact accessibility snapshot
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p012_browser_artifact_accessibility_snapshot.py (new)
- thomas/browser/p012_browser_artifact_accessibility_snapshot.py (new)
- tests/prompt_pack/test_p012_browser_artifact_accessibility_snapshot.py (new)
- docs/openclaw_gap_runs/p012_browser_artifact_accessibility_snapshot.md (new)

Task:
- Implement: Browser artifact accessibility snapshot.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser artifact accessibility snapshot" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p012_browser_artifact_accessibility_snapshot.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P013 - Browser telemetry console stream
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p013_browser_telemetry_console_stream.py (new)
- thomas/browser/p013_browser_telemetry_console_stream.py (new)
- tests/prompt_pack/test_p013_browser_telemetry_console_stream.py (new)
- docs/openclaw_gap_runs/p013_browser_telemetry_console_stream.md (new)

Task:
- Implement: Browser telemetry console stream.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser telemetry console stream" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p013_browser_telemetry_console_stream.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P014 - Browser telemetry network requests
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p014_browser_telemetry_network_requests.py (new)
- thomas/browser/p014_browser_telemetry_network_requests.py (new)
- tests/prompt_pack/test_p014_browser_telemetry_network_requests.py (new)
- docs/openclaw_gap_runs/p014_browser_telemetry_network_requests.md (new)

Task:
- Implement: Browser telemetry network requests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser telemetry network requests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p014_browser_telemetry_network_requests.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P015 - Browser telemetry response body fetch
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p015_browser_telemetry_response_body_fetch.py (new)
- thomas/browser/p015_browser_telemetry_response_body_fetch.py (new)
- tests/prompt_pack/test_p015_browser_telemetry_response_body_fetch.py (new)
- docs/openclaw_gap_runs/p015_browser_telemetry_response_body_fetch.md (new)

Task:
- Implement: Browser telemetry response body fetch.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser telemetry response body fetch" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p015_browser_telemetry_response_body_fetch.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P016 - Browser data cookies export and import
Batch: B02 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p016_browser_data_cookies_export_and_import.py (new)
- thomas/browser/p016_browser_data_cookies_export_and_import.py (new)
- tests/prompt_pack/test_p016_browser_data_cookies_export_and_import.py (new)
- docs/openclaw_gap_runs/p016_browser_data_cookies_export_and_import.md (new)

Task:
- Implement: Browser data cookies export and import.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser data cookies export and import" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p016_browser_data_cookies_export_and_import.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P017 - Browser data storage snapshot
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p017_browser_data_storage_snapshot.py (new)
- thomas/browser/p017_browser_data_storage_snapshot.py (new)
- tests/prompt_pack/test_p017_browser_data_storage_snapshot.py (new)
- docs/openclaw_gap_runs/p017_browser_data_storage_snapshot.md (new)

Task:
- Implement: Browser data storage snapshot.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser data storage snapshot" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p017_browser_data_storage_snapshot.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P018 - Browser tab management
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p018_browser_tab_management.py (new)
- thomas/browser/p018_browser_tab_management.py (new)
- tests/prompt_pack/test_p018_browser_tab_management.py (new)
- docs/openclaw_gap_runs/p018_browser_tab_management.md (new)

Task:
- Implement: Browser tab management.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser tab management" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p018_browser_tab_management.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P019 - Browser profile create delete list
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p019_browser_profile_create_delete_list.py (new)
- thomas/browser/p019_browser_profile_create_delete_list.py (new)
- tests/prompt_pack/test_p019_browser_profile_create_delete_list.py (new)
- docs/openclaw_gap_runs/p019_browser_profile_create_delete_list.md (new)

Task:
- Implement: Browser profile create delete list.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser profile create delete list" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p019_browser_profile_create_delete_list.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P020 - Browser lifecycle start stop restart
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p020_browser_lifecycle_start_stop_restart.py (new)
- thomas/browser/p020_browser_lifecycle_start_stop_restart.py (new)
- tests/prompt_pack/test_p020_browser_lifecycle_start_stop_restart.py (new)
- docs/openclaw_gap_runs/p020_browser_lifecycle_start_stop_restart.md (new)

Task:
- Implement: Browser lifecycle start stop restart.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser lifecycle start stop restart" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p020_browser_lifecycle_start_stop_restart.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P021 - Browser download tracking
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p021_browser_download_tracking.py (new)
- thomas/browser/p021_browser_download_tracking.py (new)
- tests/prompt_pack/test_p021_browser_download_tracking.py (new)
- docs/openclaw_gap_runs/p021_browser_download_tracking.md (new)

Task:
- Implement: Browser download tracking.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser download tracking" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p021_browser_download_tracking.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P022 - Browser upload helper
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p022_browser_upload_helper.py (new)
- thomas/browser/p022_browser_upload_helper.py (new)
- tests/prompt_pack/test_p022_browser_upload_helper.py (new)
- docs/openclaw_gap_runs/p022_browser_upload_helper.md (new)

Task:
- Implement: Browser upload helper.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser upload helper" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p022_browser_upload_helper.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P023 - Browser trace start stop export
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p023_browser_trace_start_stop_export.py (new)
- thomas/browser/p023_browser_trace_start_stop_export.py (new)
- tests/prompt_pack/test_p023_browser_trace_start_stop_export.py (new)
- docs/openclaw_gap_runs/p023_browser_trace_start_stop_export.md (new)

Task:
- Implement: Browser trace start stop export.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser trace start stop export" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p023_browser_trace_start_stop_export.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P024 - Browser error normalization
Batch: B03 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p024_browser_error_normalization.py (new)
- thomas/browser/p024_browser_error_normalization.py (new)
- tests/prompt_pack/test_p024_browser_error_normalization.py (new)
- docs/openclaw_gap_runs/p024_browser_error_normalization.md (new)

Task:
- Implement: Browser error normalization.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser error normalization" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p024_browser_error_normalization.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P025 - Browser json output contract
Batch: B04 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p025_browser_json_output_contract.py (new)
- thomas/browser/p025_browser_json_output_contract.py (new)
- tests/prompt_pack/test_p025_browser_json_output_contract.py (new)
- docs/openclaw_gap_runs/p025_browser_json_output_contract.md (new)

Task:
- Implement: Browser json output contract.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser json output contract" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p025_browser_json_output_contract.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P026 - Browser integration into top-level cli
Batch: B04 | Lane: Browser and Nodes | Domain: browser

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/live_browser.py
- thomas/tools/browser.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/browser/p026_browser_integration_into_top_level_cli.py (new)
- thomas/cli/main.py
- thomas/browser/p026_browser_integration_into_top_level_cli.py (new)
- tests/prompt_pack/test_p026_browser_integration_into_top_level_cli.py (new)
- docs/openclaw_gap_runs/p026_browser_integration_into_top_level_cli.md (new)

Task:
- Implement: Browser integration into top-level cli.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser integration into top-level cli" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p026_browser_integration_into_top_level_cli.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "browser"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P027 - Node host config model
Batch: B04 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p027_node_host_config_model.py (new)
- thomas/nodes/p027_node_host_config_model.py (new)
- tests/prompt_pack/test_p027_node_host_config_model.py (new)
- docs/openclaw_gap_runs/p027_node_host_config_model.md (new)

Task:
- Implement: Node host config model.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node host config model" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p027_node_host_config_model.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P028 - Node host state store
Batch: B04 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p028_node_host_state_store.py (new)
- thomas/nodes/p028_node_host_state_store.py (new)
- tests/prompt_pack/test_p028_node_host_state_store.py (new)
- docs/openclaw_gap_runs/p028_node_host_state_store.md (new)

Task:
- Implement: Node host state store.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node host state store" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p028_node_host_state_store.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P029 - Node host lifecycle service
Batch: B04 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p029_node_host_lifecycle_service.py (new)
- thomas/nodes/p029_node_host_lifecycle_service.py (new)
- tests/prompt_pack/test_p029_node_host_lifecycle_service.py (new)
- docs/openclaw_gap_runs/p029_node_host_lifecycle_service.md (new)

Task:
- Implement: Node host lifecycle service.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node host lifecycle service" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p029_node_host_lifecycle_service.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P030 - Node cli group scaffold
Batch: B04 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p030_node_cli_group_scaffold.py (new)
- thomas/nodes/p030_node_cli_group_scaffold.py (new)
- tests/prompt_pack/test_p030_node_cli_group_scaffold.py (new)
- docs/openclaw_gap_runs/p030_node_cli_group_scaffold.md (new)

Task:
- Implement: Node cli group scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node cli group scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p030_node_cli_group_scaffold.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P031 - Node command install
Batch: B04 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p031_node_command_install.py (new)
- thomas/nodes/p031_node_command_install.py (new)
- tests/prompt_pack/test_p031_node_command_install.py (new)
- docs/openclaw_gap_runs/p031_node_command_install.md (new)

Task:
- Implement: Node command install.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node command install" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p031_node_command_install.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P032 - Node command run
Batch: B04 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p032_node_command_run.py (new)
- thomas/nodes/p032_node_command_run.py (new)
- tests/prompt_pack/test_p032_node_command_run.py (new)
- docs/openclaw_gap_runs/p032_node_command_run.md (new)

Task:
- Implement: Node command run.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node command run" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p032_node_command_run.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P033 - Node command status
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p033_node_command_status.py (new)
- thomas/nodes/p033_node_command_status.py (new)
- tests/prompt_pack/test_p033_node_command_status.py (new)
- docs/openclaw_gap_runs/p033_node_command_status.md (new)

Task:
- Implement: Node command status.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node command status" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p033_node_command_status.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P034 - Node command restart
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p034_node_command_restart.py (new)
- thomas/nodes/p034_node_command_restart.py (new)
- tests/prompt_pack/test_p034_node_command_restart.py (new)
- docs/openclaw_gap_runs/p034_node_command_restart.md (new)

Task:
- Implement: Node command restart.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node command restart" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p034_node_command_restart.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P035 - Node command stop
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p035_node_command_stop.py (new)
- thomas/nodes/p035_node_command_stop.py (new)
- tests/prompt_pack/test_p035_node_command_stop.py (new)
- docs/openclaw_gap_runs/p035_node_command_stop.md (new)

Task:
- Implement: Node command stop.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node command stop" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p035_node_command_stop.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P036 - Node command uninstall
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p036_node_command_uninstall.py (new)
- thomas/nodes/p036_node_command_uninstall.py (new)
- tests/prompt_pack/test_p036_node_command_uninstall.py (new)
- docs/openclaw_gap_runs/p036_node_command_uninstall.md (new)

Task:
- Implement: Node command uninstall.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node command uninstall" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p036_node_command_uninstall.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P037 - Nodes registry model
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p037_nodes_registry_model.py (new)
- thomas/nodes/p037_nodes_registry_model.py (new)
- tests/prompt_pack/test_p037_nodes_registry_model.py (new)
- docs/openclaw_gap_runs/p037_nodes_registry_model.md (new)

Task:
- Implement: Nodes registry model.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes registry model" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p037_nodes_registry_model.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P038 - Nodes list and status
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p038_nodes_list_and_status.py (new)
- thomas/nodes/p038_nodes_list_and_status.py (new)
- tests/prompt_pack/test_p038_nodes_list_and_status.py (new)
- docs/openclaw_gap_runs/p038_nodes_list_and_status.md (new)

Task:
- Implement: Nodes list and status.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes list and status" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p038_nodes_list_and_status.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P039 - Nodes invoke action
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p039_nodes_invoke_action.py (new)
- thomas/nodes/p039_nodes_invoke_action.py (new)
- tests/prompt_pack/test_p039_nodes_invoke_action.py (new)
- docs/openclaw_gap_runs/p039_nodes_invoke_action.md (new)

Task:
- Implement: Nodes invoke action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes invoke action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p039_nodes_invoke_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P040 - Nodes notify action
Batch: B05 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p040_nodes_notify_action.py (new)
- thomas/nodes/p040_nodes_notify_action.py (new)
- tests/prompt_pack/test_p040_nodes_notify_action.py (new)
- docs/openclaw_gap_runs/p040_nodes_notify_action.md (new)

Task:
- Implement: Nodes notify action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes notify action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p040_nodes_notify_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P041 - Nodes push payload
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p041_nodes_push_payload.py (new)
- thomas/nodes/p041_nodes_push_payload.py (new)
- tests/prompt_pack/test_p041_nodes_push_payload.py (new)
- docs/openclaw_gap_runs/p041_nodes_push_payload.md (new)

Task:
- Implement: Nodes push payload.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes push payload" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p041_nodes_push_payload.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P042 - Nodes camera action
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p042_nodes_camera_action.py (new)
- thomas/nodes/p042_nodes_camera_action.py (new)
- tests/prompt_pack/test_p042_nodes_camera_action.py (new)
- docs/openclaw_gap_runs/p042_nodes_camera_action.md (new)

Task:
- Implement: Nodes camera action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes camera action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p042_nodes_camera_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P043 - Nodes screen capture action
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p043_nodes_screen_capture_action.py (new)
- thomas/nodes/p043_nodes_screen_capture_action.py (new)
- tests/prompt_pack/test_p043_nodes_screen_capture_action.py (new)
- docs/openclaw_gap_runs/p043_nodes_screen_capture_action.md (new)

Task:
- Implement: Nodes screen capture action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes screen capture action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p043_nodes_screen_capture_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P044 - Nodes location action
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p044_nodes_location_action.py (new)
- thomas/nodes/p044_nodes_location_action.py (new)
- tests/prompt_pack/test_p044_nodes_location_action.py (new)
- docs/openclaw_gap_runs/p044_nodes_location_action.md (new)

Task:
- Implement: Nodes location action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes location action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p044_nodes_location_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P045 - Nodes canvas action
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p045_nodes_canvas_action.py (new)
- thomas/nodes/p045_nodes_canvas_action.py (new)
- tests/prompt_pack/test_p045_nodes_canvas_action.py (new)
- docs/openclaw_gap_runs/p045_nodes_canvas_action.md (new)

Task:
- Implement: Nodes canvas action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes canvas action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p045_nodes_canvas_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P046 - Nodes pending approvals
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p046_nodes_pending_approvals.py (new)
- thomas/nodes/p046_nodes_pending_approvals.py (new)
- tests/prompt_pack/test_p046_nodes_pending_approvals.py (new)
- docs/openclaw_gap_runs/p046_nodes_pending_approvals.md (new)

Task:
- Implement: Nodes pending approvals.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes pending approvals" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p046_nodes_pending_approvals.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P047 - Nodes approve action
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p047_nodes_approve_action.py (new)
- thomas/nodes/p047_nodes_approve_action.py (new)
- tests/prompt_pack/test_p047_nodes_approve_action.py (new)
- docs/openclaw_gap_runs/p047_nodes_approve_action.md (new)

Task:
- Implement: Nodes approve action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes approve action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p047_nodes_approve_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P048 - Nodes reject action
Batch: B06 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p048_nodes_reject_action.py (new)
- thomas/nodes/p048_nodes_reject_action.py (new)
- tests/prompt_pack/test_p048_nodes_reject_action.py (new)
- docs/openclaw_gap_runs/p048_nodes_reject_action.md (new)

Task:
- Implement: Nodes reject action.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes reject action" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p048_nodes_reject_action.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P049 - Nodes pairing handshake
Batch: B07 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p049_nodes_pairing_handshake.py (new)
- thomas/nodes/p049_nodes_pairing_handshake.py (new)
- tests/prompt_pack/test_p049_nodes_pairing_handshake.py (new)
- docs/openclaw_gap_runs/p049_nodes_pairing_handshake.md (new)

Task:
- Implement: Nodes pairing handshake.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes pairing handshake" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p049_nodes_pairing_handshake.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P050 - Nodes token rotate and revoke
Batch: B07 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p050_nodes_token_rotate_and_revoke.py (new)
- thomas/nodes/p050_nodes_token_rotate_and_revoke.py (new)
- tests/prompt_pack/test_p050_nodes_token_rotate_and_revoke.py (new)
- docs/openclaw_gap_runs/p050_nodes_token_rotate_and_revoke.md (new)

Task:
- Implement: Nodes token rotate and revoke.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes token rotate and revoke" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p050_nodes_token_rotate_and_revoke.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P051 - Nodes api routes and auth
Batch: B07 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p051_nodes_api_routes_and_auth.py (new)
- thomas/nodes/p051_nodes_api_routes_and_auth.py (new)
- tests/prompt_pack/test_p051_nodes_api_routes_and_auth.py (new)
- docs/openclaw_gap_runs/p051_nodes_api_routes_and_auth.md (new)

Task:
- Implement: Nodes api routes and auth.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes api routes and auth" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p051_nodes_api_routes_and_auth.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P052 - Nodes cli integration and parity tests
Batch: B07 | Lane: Browser and Nodes | Domain: nodes

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/nodes/p052_nodes_cli_integration_and_parity_tests.py (new)
- thomas/cli/main.py
- thomas/nodes/p052_nodes_cli_integration_and_parity_tests.py (new)
- tests/prompt_pack/test_p052_nodes_cli_integration_and_parity_tests.py (new)
- docs/openclaw_gap_runs/p052_nodes_cli_integration_and_parity_tests.md (new)

Task:
- Implement: Nodes cli integration and parity tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nodes cli integration and parity tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p052_nodes_cli_integration_and_parity_tests.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "node or nodes or devices"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P053 - Message schema and persistence refactor
Batch: B07 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p053_message_schema_and_persistence_refactor.py (new)
- thomas/messages/p053_message_schema_and_persistence_refactor.py (new)
- tests/prompt_pack/test_p053_message_schema_and_persistence_refactor.py (new)
- docs/openclaw_gap_runs/p053_message_schema_and_persistence_refactor.md (new)

Task:
- Implement: Message schema and persistence refactor.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message schema and persistence refactor" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p053_message_schema_and_persistence_refactor.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P054 - Message read command
Batch: B07 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p054_message_read_command.py (new)
- thomas/messages/p054_message_read_command.py (new)
- tests/prompt_pack/test_p054_message_read_command.py (new)
- docs/openclaw_gap_runs/p054_message_read_command.md (new)

Task:
- Implement: Message read command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message read command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p054_message_read_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P055 - Message edit command
Batch: B07 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p055_message_edit_command.py (new)
- thomas/messages/p055_message_edit_command.py (new)
- tests/prompt_pack/test_p055_message_edit_command.py (new)
- docs/openclaw_gap_runs/p055_message_edit_command.md (new)

Task:
- Implement: Message edit command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message edit command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p055_message_edit_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P056 - Message delete command
Batch: B07 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p056_message_delete_command.py (new)
- thomas/messages/p056_message_delete_command.py (new)
- tests/prompt_pack/test_p056_message_delete_command.py (new)
- docs/openclaw_gap_runs/p056_message_delete_command.md (new)

Task:
- Implement: Message delete command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message delete command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p056_message_delete_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P057 - Message search command
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p057_message_search_command.py (new)
- thomas/messages/p057_message_search_command.py (new)
- tests/prompt_pack/test_p057_message_search_command.py (new)
- docs/openclaw_gap_runs/p057_message_search_command.md (new)

Task:
- Implement: Message search command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message search command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p057_message_search_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P058 - Message thread list
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p058_message_thread_list.py (new)
- thomas/messages/p058_message_thread_list.py (new)
- tests/prompt_pack/test_p058_message_thread_list.py (new)
- docs/openclaw_gap_runs/p058_message_thread_list.md (new)

Task:
- Implement: Message thread list.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message thread list" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p058_message_thread_list.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P059 - Message thread reply
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p059_message_thread_reply.py (new)
- thomas/messages/p059_message_thread_reply.py (new)
- tests/prompt_pack/test_p059_message_thread_reply.py (new)
- docs/openclaw_gap_runs/p059_message_thread_reply.md (new)

Task:
- Implement: Message thread reply.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message thread reply" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p059_message_thread_reply.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P060 - Message pin command
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p060_message_pin_command.py (new)
- thomas/messages/p060_message_pin_command.py (new)
- tests/prompt_pack/test_p060_message_pin_command.py (new)
- docs/openclaw_gap_runs/p060_message_pin_command.md (new)

Task:
- Implement: Message pin command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message pin command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p060_message_pin_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P061 - Message unpin command
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p061_message_unpin_command.py (new)
- thomas/messages/p061_message_unpin_command.py (new)
- tests/prompt_pack/test_p061_message_unpin_command.py (new)
- docs/openclaw_gap_runs/p061_message_unpin_command.md (new)

Task:
- Implement: Message unpin command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message unpin command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p061_message_unpin_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P062 - Message reactions add remove list
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p062_message_reactions_add_remove_list.py (new)
- thomas/messages/p062_message_reactions_add_remove_list.py (new)
- tests/prompt_pack/test_p062_message_reactions_add_remove_list.py (new)
- docs/openclaw_gap_runs/p062_message_reactions_add_remove_list.md (new)

Task:
- Implement: Message reactions add remove list.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message reactions add remove list" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p062_message_reactions_add_remove_list.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P063 - Message poll create command
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p063_message_poll_create_command.py (new)
- thomas/messages/p063_message_poll_create_command.py (new)
- tests/prompt_pack/test_p063_message_poll_create_command.py (new)
- docs/openclaw_gap_runs/p063_message_poll_create_command.md (new)

Task:
- Implement: Message poll create command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message poll create command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p063_message_poll_create_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P064 - Message poll vote and close
Batch: B08 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p064_message_poll_vote_and_close.py (new)
- thomas/messages/p064_message_poll_vote_and_close.py (new)
- tests/prompt_pack/test_p064_message_poll_vote_and_close.py (new)
- docs/openclaw_gap_runs/p064_message_poll_vote_and_close.md (new)

Task:
- Implement: Message poll vote and close.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message poll vote and close" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p064_message_poll_vote_and_close.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P065 - Message member timeout
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p065_message_member_timeout.py (new)
- thomas/messages/p065_message_member_timeout.py (new)
- tests/prompt_pack/test_p065_message_member_timeout.py (new)
- docs/openclaw_gap_runs/p065_message_member_timeout.md (new)

Task:
- Implement: Message member timeout.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message member timeout" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p065_message_member_timeout.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P066 - Message member kick and ban
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p066_message_member_kick_and_ban.py (new)
- thomas/messages/p066_message_member_kick_and_ban.py (new)
- tests/prompt_pack/test_p066_message_member_kick_and_ban.py (new)
- docs/openclaw_gap_runs/p066_message_member_kick_and_ban.md (new)

Task:
- Implement: Message member kick and ban.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message member kick and ban" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p066_message_member_kick_and_ban.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P067 - Message role assign and remove
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p067_message_role_assign_and_remove.py (new)
- thomas/messages/p067_message_role_assign_and_remove.py (new)
- tests/prompt_pack/test_p067_message_role_assign_and_remove.py (new)
- docs/openclaw_gap_runs/p067_message_role_assign_and_remove.md (new)

Task:
- Implement: Message role assign and remove.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message role assign and remove" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p067_message_role_assign_and_remove.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P068 - Message permissions view
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p068_message_permissions_view.py (new)
- thomas/messages/p068_message_permissions_view.py (new)
- tests/prompt_pack/test_p068_message_permissions_view.py (new)
- docs/openclaw_gap_runs/p068_message_permissions_view.md (new)

Task:
- Implement: Message permissions view.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message permissions view" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p068_message_permissions_view.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P069 - Message event history
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p069_message_event_history.py (new)
- thomas/messages/p069_message_event_history.py (new)
- tests/prompt_pack/test_p069_message_event_history.py (new)
- docs/openclaw_gap_runs/p069_message_event_history.md (new)

Task:
- Implement: Message event history.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message event history" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p069_message_event_history.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P070 - Message broadcast with safety gate
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p070_message_broadcast_with_safety_gate.py (new)
- thomas/messages/p070_message_broadcast_with_safety_gate.py (new)
- tests/prompt_pack/test_p070_message_broadcast_with_safety_gate.py (new)
- docs/openclaw_gap_runs/p070_message_broadcast_with_safety_gate.md (new)

Task:
- Implement: Message broadcast with safety gate.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message broadcast with safety gate" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p070_message_broadcast_with_safety_gate.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P071 - Message voice metadata stub
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p071_message_voice_metadata_stub.py (new)
- thomas/messages/p071_message_voice_metadata_stub.py (new)
- tests/prompt_pack/test_p071_message_voice_metadata_stub.py (new)
- docs/openclaw_gap_runs/p071_message_voice_metadata_stub.md (new)

Task:
- Implement: Message voice metadata stub.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message voice metadata stub" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p071_message_voice_metadata_stub.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P072 - Message channel specific route resolver
Batch: B09 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p072_message_channel_specific_route_resolver.py (new)
- thomas/messages/p072_message_channel_specific_route_resolver.py (new)
- tests/prompt_pack/test_p072_message_channel_specific_route_resolver.py (new)
- docs/openclaw_gap_runs/p072_message_channel_specific_route_resolver.md (new)

Task:
- Implement: Message channel specific route resolver.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message channel specific route resolver" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p072_message_channel_specific_route_resolver.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P073 - Message retry policy and idempotency
Batch: B10 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p073_message_retry_policy_and_idempotency.py (new)
- thomas/messages/p073_message_retry_policy_and_idempotency.py (new)
- tests/prompt_pack/test_p073_message_retry_policy_and_idempotency.py (new)
- docs/openclaw_gap_runs/p073_message_retry_policy_and_idempotency.md (new)

Task:
- Implement: Message retry policy and idempotency.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message retry policy and idempotency" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p073_message_retry_policy_and_idempotency.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P074 - Message integration into cli group
Batch: B10 | Lane: Messaging and Channels | Domain: messages

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_compat.py
- thomas/cli/parity_commands.py
- thomas/server/routes/webhooks.py

Ownership (edit only these paths):
- thomas/cli/commands/messages/p074_message_integration_into_cli_group.py (new)
- thomas/cli/parity_compat.py
- thomas/messages/p074_message_integration_into_cli_group.py (new)
- tests/prompt_pack/test_p074_message_integration_into_cli_group.py (new)
- docs/openclaw_gap_runs/p074_message_integration_into_cli_group.md (new)

Task:
- Implement: Message integration into cli group.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message integration into cli group" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/parity_compat.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p074_message_integration_into_cli_group.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "message"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P075 - Channel provider interface contract
Batch: B10 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p075_channel_provider_interface_contract.py (new)
- thomas/channels/p075_channel_provider_interface_contract.py (new)
- tests/prompt_pack/test_p075_channel_provider_interface_contract.py (new)
- docs/openclaw_gap_runs/p075_channel_provider_interface_contract.md (new)

Task:
- Implement: Channel provider interface contract.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel provider interface contract" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p075_channel_provider_interface_contract.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P076 - Channel registry loader
Batch: B10 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p076_channel_registry_loader.py (new)
- thomas/channels/p076_channel_registry_loader.py (new)
- tests/prompt_pack/test_p076_channel_registry_loader.py (new)
- docs/openclaw_gap_runs/p076_channel_registry_loader.md (new)

Task:
- Implement: Channel registry loader.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel registry loader" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p076_channel_registry_loader.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P077 - Channel provider config schema
Batch: B10 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p077_channel_provider_config_schema.py (new)
- thomas/channels/p077_channel_provider_config_schema.py (new)
- tests/prompt_pack/test_p077_channel_provider_config_schema.py (new)
- docs/openclaw_gap_runs/p077_channel_provider_config_schema.md (new)

Task:
- Implement: Channel provider config schema.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel provider config schema" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p077_channel_provider_config_schema.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P078 - Channel add command
Batch: B10 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p078_channel_add_command.py (new)
- thomas/channels/p078_channel_add_command.py (new)
- tests/prompt_pack/test_p078_channel_add_command.py (new)
- docs/openclaw_gap_runs/p078_channel_add_command.md (new)

Task:
- Implement: Channel add command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel add command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p078_channel_add_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P079 - Channel remove command
Batch: B10 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p079_channel_remove_command.py (new)
- thomas/channels/p079_channel_remove_command.py (new)
- tests/prompt_pack/test_p079_channel_remove_command.py (new)
- docs/openclaw_gap_runs/p079_channel_remove_command.md (new)

Task:
- Implement: Channel remove command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel remove command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p079_channel_remove_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P080 - Channel login command
Batch: B10 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p080_channel_login_command.py (new)
- thomas/channels/p080_channel_login_command.py (new)
- tests/prompt_pack/test_p080_channel_login_command.py (new)
- docs/openclaw_gap_runs/p080_channel_login_command.md (new)

Task:
- Implement: Channel login command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel login command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p080_channel_login_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P081 - Channel logout command
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p081_channel_logout_command.py (new)
- thomas/channels/p081_channel_logout_command.py (new)
- tests/prompt_pack/test_p081_channel_logout_command.py (new)
- docs/openclaw_gap_runs/p081_channel_logout_command.md (new)

Task:
- Implement: Channel logout command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel logout command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p081_channel_logout_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P082 - Channel logs command
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p082_channel_logs_command.py (new)
- thomas/channels/p082_channel_logs_command.py (new)
- tests/prompt_pack/test_p082_channel_logs_command.py (new)
- docs/openclaw_gap_runs/p082_channel_logs_command.md (new)

Task:
- Implement: Channel logs command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel logs command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p082_channel_logs_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P083 - Channel capabilities command
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p083_channel_capabilities_command.py (new)
- thomas/channels/p083_channel_capabilities_command.py (new)
- tests/prompt_pack/test_p083_channel_capabilities_command.py (new)
- docs/openclaw_gap_runs/p083_channel_capabilities_command.md (new)

Task:
- Implement: Channel capabilities command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel capabilities command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p083_channel_capabilities_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P084 - Channel resolve command
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p084_channel_resolve_command.py (new)
- thomas/channels/p084_channel_resolve_command.py (new)
- tests/prompt_pack/test_p084_channel_resolve_command.py (new)
- docs/openclaw_gap_runs/p084_channel_resolve_command.md (new)

Task:
- Implement: Channel resolve command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel resolve command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p084_channel_resolve_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P085 - Channel list enriched output
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p085_channel_list_enriched_output.py (new)
- thomas/channels/p085_channel_list_enriched_output.py (new)
- tests/prompt_pack/test_p085_channel_list_enriched_output.py (new)
- docs/openclaw_gap_runs/p085_channel_list_enriched_output.md (new)

Task:
- Implement: Channel list enriched output.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel list enriched output" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p085_channel_list_enriched_output.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P086 - Channel status diagnostic reasons
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p086_channel_status_diagnostic_reasons.py (new)
- thomas/channels/p086_channel_status_diagnostic_reasons.py (new)
- tests/prompt_pack/test_p086_channel_status_diagnostic_reasons.py (new)
- docs/openclaw_gap_runs/p086_channel_status_diagnostic_reasons.md (new)

Task:
- Implement: Channel status diagnostic reasons.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel status diagnostic reasons" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p086_channel_status_diagnostic_reasons.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P087 - Channel auth validation helper
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p087_channel_auth_validation_helper.py (new)
- thomas/channels/p087_channel_auth_validation_helper.py (new)
- tests/prompt_pack/test_p087_channel_auth_validation_helper.py (new)
- docs/openclaw_gap_runs/p087_channel_auth_validation_helper.md (new)

Task:
- Implement: Channel auth validation helper.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel auth validation helper" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p087_channel_auth_validation_helper.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P088 - Channel secret resolution precedence
Batch: B11 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p088_channel_secret_resolution_precedence.py (new)
- thomas/channels/p088_channel_secret_resolution_precedence.py (new)
- tests/prompt_pack/test_p088_channel_secret_resolution_precedence.py (new)
- docs/openclaw_gap_runs/p088_channel_secret_resolution_precedence.md (new)

Task:
- Implement: Channel secret resolution precedence.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel secret resolution precedence" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p088_channel_secret_resolution_precedence.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P089 - Channel throttling policy
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p089_channel_throttling_policy.py (new)
- thomas/channels/p089_channel_throttling_policy.py (new)
- tests/prompt_pack/test_p089_channel_throttling_policy.py (new)
- docs/openclaw_gap_runs/p089_channel_throttling_policy.md (new)

Task:
- Implement: Channel throttling policy.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel throttling policy" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p089_channel_throttling_policy.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P090 - Channel webhook bridge adapter
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p090_channel_webhook_bridge_adapter.py (new)
- thomas/channels/p090_channel_webhook_bridge_adapter.py (new)
- tests/prompt_pack/test_p090_channel_webhook_bridge_adapter.py (new)
- docs/openclaw_gap_runs/p090_channel_webhook_bridge_adapter.md (new)

Task:
- Implement: Channel webhook bridge adapter.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel webhook bridge adapter" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p090_channel_webhook_bridge_adapter.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P091 - Channel delivery acknowledgement mapping
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p091_channel_delivery_acknowledgement_mapping.py (new)
- thomas/channels/p091_channel_delivery_acknowledgement_mapping.py (new)
- tests/prompt_pack/test_p091_channel_delivery_acknowledgement_mapping.py (new)
- docs/openclaw_gap_runs/p091_channel_delivery_acknowledgement_mapping.md (new)

Task:
- Implement: Channel delivery acknowledgement mapping.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel delivery acknowledgement mapping" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p091_channel_delivery_acknowledgement_mapping.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P092 - Channel failure taxonomy
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p092_channel_failure_taxonomy.py (new)
- thomas/channels/p092_channel_failure_taxonomy.py (new)
- tests/prompt_pack/test_p092_channel_failure_taxonomy.py (new)
- docs/openclaw_gap_runs/p092_channel_failure_taxonomy.md (new)

Task:
- Implement: Channel failure taxonomy.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel failure taxonomy" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p092_channel_failure_taxonomy.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P093 - Channel retry and backoff strategy
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p093_channel_retry_and_backoff_strategy.py (new)
- thomas/channels/p093_channel_retry_and_backoff_strategy.py (new)
- tests/prompt_pack/test_p093_channel_retry_and_backoff_strategy.py (new)
- docs/openclaw_gap_runs/p093_channel_retry_and_backoff_strategy.md (new)

Task:
- Implement: Channel retry and backoff strategy.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel retry and backoff strategy" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p093_channel_retry_and_backoff_strategy.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P094 - Channel docs generator
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p094_channel_docs_generator.py (new)
- thomas/channels/p094_channel_docs_generator.py (new)
- tests/prompt_pack/test_p094_channel_docs_generator.py (new)
- docs/openclaw_gap_runs/p094_channel_docs_generator.md (new)

Task:
- Implement: Channel docs generator.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel docs generator" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p094_channel_docs_generator.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P095 - Channel provider contract tests
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p095_channel_provider_contract_tests.py (new)
- thomas/channels/p095_channel_provider_contract_tests.py (new)
- tests/prompt_pack/test_p095_channel_provider_contract_tests.py (new)
- docs/openclaw_gap_runs/p095_channel_provider_contract_tests.md (new)

Task:
- Implement: Channel provider contract tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel provider contract tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p095_channel_provider_contract_tests.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P096 - Channel integration into existing channels module
Batch: B12 | Lane: Messaging and Channels | Domain: channels

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/commands/channels.py
- thomas/integrations/telegram.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/channel_ops/p096_channel_integration_into_existing_channels_module.py (new)
- thomas/cli/commands/channels.py
- thomas/channels/p096_channel_integration_into_existing_channels_module.py (new)
- tests/prompt_pack/test_p096_channel_integration_into_existing_channels_module.py (new)
- docs/openclaw_gap_runs/p096_channel_integration_into_existing_channels_module.md (new)

Task:
- Implement: Channel integration into existing channels module.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channel integration into existing channels module" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/commands/channels.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p096_channel_integration_into_existing_channels_module.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P097 - Plugin package bootstrap
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p097_plugin_package_bootstrap.py (new)
- thomas/plugins/p097_plugin_package_bootstrap.py (new)
- tests/prompt_pack/test_p097_plugin_package_bootstrap.py (new)
- docs/openclaw_gap_runs/p097_plugin_package_bootstrap.md (new)

Task:
- Implement: Plugin package bootstrap.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin package bootstrap" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p097_plugin_package_bootstrap.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P098 - Plugin manifest schema
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p098_plugin_manifest_schema.py (new)
- thomas/plugins/p098_plugin_manifest_schema.py (new)
- tests/prompt_pack/test_p098_plugin_manifest_schema.py (new)
- docs/openclaw_gap_runs/p098_plugin_manifest_schema.md (new)

Task:
- Implement: Plugin manifest schema.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin manifest schema" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p098_plugin_manifest_schema.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P099 - Plugin manifest loader
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p099_plugin_manifest_loader.py (new)
- thomas/plugins/p099_plugin_manifest_loader.py (new)
- tests/prompt_pack/test_p099_plugin_manifest_loader.py (new)
- docs/openclaw_gap_runs/p099_plugin_manifest_loader.md (new)

Task:
- Implement: Plugin manifest loader.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin manifest loader" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p099_plugin_manifest_loader.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P100 - Plugin discovery scanner
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p100_plugin_discovery_scanner.py (new)
- thomas/plugins/p100_plugin_discovery_scanner.py (new)
- tests/prompt_pack/test_p100_plugin_discovery_scanner.py (new)
- docs/openclaw_gap_runs/p100_plugin_discovery_scanner.md (new)

Task:
- Implement: Plugin discovery scanner.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin discovery scanner" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p100_plugin_discovery_scanner.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P101 - Plugin enable and disable state store
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p101_plugin_enable_and_disable_state_store.py (new)
- thomas/plugins/p101_plugin_enable_and_disable_state_store.py (new)
- tests/prompt_pack/test_p101_plugin_enable_and_disable_state_store.py (new)
- docs/openclaw_gap_runs/p101_plugin_enable_and_disable_state_store.md (new)

Task:
- Implement: Plugin enable and disable state store.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin enable and disable state store" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p101_plugin_enable_and_disable_state_store.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P102 - Plugin install from local path
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p102_plugin_install_from_local_path.py (new)
- thomas/plugins/p102_plugin_install_from_local_path.py (new)
- tests/prompt_pack/test_p102_plugin_install_from_local_path.py (new)
- docs/openclaw_gap_runs/p102_plugin_install_from_local_path.md (new)

Task:
- Implement: Plugin install from local path.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin install from local path" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p102_plugin_install_from_local_path.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P103 - Plugin uninstall cleanup
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p103_plugin_uninstall_cleanup.py (new)
- thomas/plugins/p103_plugin_uninstall_cleanup.py (new)
- tests/prompt_pack/test_p103_plugin_uninstall_cleanup.py (new)
- docs/openclaw_gap_runs/p103_plugin_uninstall_cleanup.md (new)

Task:
- Implement: Plugin uninstall cleanup.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin uninstall cleanup" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p103_plugin_uninstall_cleanup.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P104 - Plugin update planner
Batch: B13 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p104_plugin_update_planner.py (new)
- thomas/plugins/p104_plugin_update_planner.py (new)
- tests/prompt_pack/test_p104_plugin_update_planner.py (new)
- docs/openclaw_gap_runs/p104_plugin_update_planner.md (new)

Task:
- Implement: Plugin update planner.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin update planner" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p104_plugin_update_planner.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P105 - Plugin registry core model
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p105_plugin_registry_core_model.py (new)
- thomas/plugins/p105_plugin_registry_core_model.py (new)
- tests/prompt_pack/test_p105_plugin_registry_core_model.py (new)
- docs/openclaw_gap_runs/p105_plugin_registry_core_model.md (new)

Task:
- Implement: Plugin registry core model.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin registry core model" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p105_plugin_registry_core_model.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P106 - Plugin command registry bridge
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p106_plugin_command_registry_bridge.py (new)
- thomas/plugins/p106_plugin_command_registry_bridge.py (new)
- tests/prompt_pack/test_p106_plugin_command_registry_bridge.py (new)
- docs/openclaw_gap_runs/p106_plugin_command_registry_bridge.md (new)

Task:
- Implement: Plugin command registry bridge.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin command registry bridge" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p106_plugin_command_registry_bridge.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P107 - Plugin hook types contract
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p107_plugin_hook_types_contract.py (new)
- thomas/plugins/p107_plugin_hook_types_contract.py (new)
- tests/prompt_pack/test_p107_plugin_hook_types_contract.py (new)
- docs/openclaw_gap_runs/p107_plugin_hook_types_contract.md (new)

Task:
- Implement: Plugin hook types contract.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin hook types contract" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p107_plugin_hook_types_contract.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P108 - Plugin hook runner core
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p108_plugin_hook_runner_core.py (new)
- thomas/plugins/p108_plugin_hook_runner_core.py (new)
- tests/prompt_pack/test_p108_plugin_hook_runner_core.py (new)
- docs/openclaw_gap_runs/p108_plugin_hook_runner_core.md (new)

Task:
- Implement: Plugin hook runner core.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin hook runner core" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p108_plugin_hook_runner_core.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P109 - Plugin hook before-model
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p109_plugin_hook_before_model.py (new)
- thomas/plugins/p109_plugin_hook_before_model.py (new)
- tests/prompt_pack/test_p109_plugin_hook_before_model.py (new)
- docs/openclaw_gap_runs/p109_plugin_hook_before_model.md (new)

Task:
- Implement: Plugin hook before-model.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin hook before-model" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p109_plugin_hook_before_model.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P110 - Plugin hook before-tool
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p110_plugin_hook_before_tool.py (new)
- thomas/plugins/p110_plugin_hook_before_tool.py (new)
- tests/prompt_pack/test_p110_plugin_hook_before_tool.py (new)
- docs/openclaw_gap_runs/p110_plugin_hook_before_tool.md (new)

Task:
- Implement: Plugin hook before-tool.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin hook before-tool" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p110_plugin_hook_before_tool.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P111 - Plugin hook after-tool
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p111_plugin_hook_after_tool.py (new)
- thomas/plugins/p111_plugin_hook_after_tool.py (new)
- tests/prompt_pack/test_p111_plugin_hook_after_tool.py (new)
- docs/openclaw_gap_runs/p111_plugin_hook_after_tool.md (new)

Task:
- Implement: Plugin hook after-tool.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin hook after-tool" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p111_plugin_hook_after_tool.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P112 - Plugin hook after-response
Batch: B14 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p112_plugin_hook_after_response.py (new)
- thomas/plugins/p112_plugin_hook_after_response.py (new)
- tests/prompt_pack/test_p112_plugin_hook_after_response.py (new)
- docs/openclaw_gap_runs/p112_plugin_hook_after_response.md (new)

Task:
- Implement: Plugin hook after-response.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin hook after-response" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p112_plugin_hook_after_response.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P113 - Plugin tool provider injection
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p113_plugin_tool_provider_injection.py (new)
- thomas/plugins/p113_plugin_tool_provider_injection.py (new)
- tests/prompt_pack/test_p113_plugin_tool_provider_injection.py (new)
- docs/openclaw_gap_runs/p113_plugin_tool_provider_injection.md (new)

Task:
- Implement: Plugin tool provider injection.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin tool provider injection" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p113_plugin_tool_provider_injection.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P114 - Plugin service lifecycle manager
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p114_plugin_service_lifecycle_manager.py (new)
- thomas/plugins/p114_plugin_service_lifecycle_manager.py (new)
- tests/prompt_pack/test_p114_plugin_service_lifecycle_manager.py (new)
- docs/openclaw_gap_runs/p114_plugin_service_lifecycle_manager.md (new)

Task:
- Implement: Plugin service lifecycle manager.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin service lifecycle manager" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p114_plugin_service_lifecycle_manager.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P115 - Plugin gateway handler registry
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p115_plugin_gateway_handler_registry.py (new)
- thomas/plugins/p115_plugin_gateway_handler_registry.py (new)
- tests/prompt_pack/test_p115_plugin_gateway_handler_registry.py (new)
- docs/openclaw_gap_runs/p115_plugin_gateway_handler_registry.md (new)

Task:
- Implement: Plugin gateway handler registry.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin gateway handler registry" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p115_plugin_gateway_handler_registry.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P116 - Plugin http route registry
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p116_plugin_http_route_registry.py (new)
- thomas/plugins/p116_plugin_http_route_registry.py (new)
- tests/prompt_pack/test_p116_plugin_http_route_registry.py (new)
- docs/openclaw_gap_runs/p116_plugin_http_route_registry.md (new)

Task:
- Implement: Plugin http route registry.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin http route registry" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p116_plugin_http_route_registry.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P117 - Plugin config schema validator
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p117_plugin_config_schema_validator.py (new)
- thomas/plugins/p117_plugin_config_schema_validator.py (new)
- tests/prompt_pack/test_p117_plugin_config_schema_validator.py (new)
- docs/openclaw_gap_runs/p117_plugin_config_schema_validator.md (new)

Task:
- Implement: Plugin config schema validator.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin config schema validator" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p117_plugin_config_schema_validator.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P118 - Plugin diagnostics collector
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p118_plugin_diagnostics_collector.py (new)
- thomas/plugins/p118_plugin_diagnostics_collector.py (new)
- tests/prompt_pack/test_p118_plugin_diagnostics_collector.py (new)
- docs/openclaw_gap_runs/p118_plugin_diagnostics_collector.md (new)

Task:
- Implement: Plugin diagnostics collector.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin diagnostics collector" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p118_plugin_diagnostics_collector.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P119 - Plugin doctor command
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p119_plugin_doctor_command.py (new)
- thomas/plugins/p119_plugin_doctor_command.py (new)
- tests/prompt_pack/test_p119_plugin_doctor_command.py (new)
- docs/openclaw_gap_runs/p119_plugin_doctor_command.md (new)

Task:
- Implement: Plugin doctor command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin doctor command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p119_plugin_doctor_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P120 - Plugin info command
Batch: B15 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p120_plugin_info_command.py (new)
- thomas/plugins/p120_plugin_info_command.py (new)
- tests/prompt_pack/test_p120_plugin_info_command.py (new)
- docs/openclaw_gap_runs/p120_plugin_info_command.md (new)

Task:
- Implement: Plugin info command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin info command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p120_plugin_info_command.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P121 - Plugin list command runtime-backed
Batch: B16 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p121_plugin_list_command_runtime_backed.py (new)
- thomas/plugins/p121_plugin_list_command_runtime_backed.py (new)
- tests/prompt_pack/test_p121_plugin_list_command_runtime_backed.py (new)
- docs/openclaw_gap_runs/p121_plugin_list_command_runtime_backed.md (new)

Task:
- Implement: Plugin list command runtime-backed.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin list command runtime-backed" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p121_plugin_list_command_runtime_backed.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P122 - Plugin lifecycle commands runtime-backed
Batch: B16 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p122_plugin_lifecycle_commands_runtime_backed.py (new)
- thomas/plugins/p122_plugin_lifecycle_commands_runtime_backed.py (new)
- tests/prompt_pack/test_p122_plugin_lifecycle_commands_runtime_backed.py (new)
- docs/openclaw_gap_runs/p122_plugin_lifecycle_commands_runtime_backed.md (new)

Task:
- Implement: Plugin lifecycle commands runtime-backed.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin lifecycle commands runtime-backed" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p122_plugin_lifecycle_commands_runtime_backed.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P123 - Sample plugin skeleton extension
Batch: B16 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p123_sample_plugin_skeleton_extension.py (new)
- thomas/plugins/p123_sample_plugin_skeleton_extension.py (new)
- tests/prompt_pack/test_p123_sample_plugin_skeleton_extension.py (new)
- docs/openclaw_gap_runs/p123_sample_plugin_skeleton_extension.md (new)

Task:
- Implement: Sample plugin skeleton extension.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Sample plugin skeleton extension" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p123_sample_plugin_skeleton_extension.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P124 - Plugin authoring docs and smoke tests
Batch: B16 | Lane: Plugins and Gateway API | Domain: plugins

```text
Project root: <repo_root>

Context to read first:
- thomas/autonomy/plugin.py
- thomas/tools/registry.py
- thomas/agent/loop.py

Ownership (edit only these paths):
- thomas/cli/commands/plugins/p124_plugin_authoring_docs_and_smoke_tests.py (new)
- thomas/cli/main.py
- thomas/plugins/p124_plugin_authoring_docs_and_smoke_tests.py (new)
- tests/prompt_pack/test_p124_plugin_authoring_docs_and_smoke_tests.py (new)
- docs/openclaw_gap_runs/p124_plugin_authoring_docs_and_smoke_tests.md (new)

Task:
- Implement: Plugin authoring docs and smoke tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin authoring docs and smoke tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p124_plugin_authoring_docs_and_smoke_tests.py
- python -m pytest -q tests/test_cli_parity_commands.py -k "plugins"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P125 - Gateway ops route package scaffold
Batch: B16 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p125_gateway_ops_route_package_scaffold.py (new)
- thomas/cli/commands/gateway/p125_gateway_ops_route_package_scaffold.py (new)
- tests/prompt_pack/test_p125_gateway_ops_route_package_scaffold.py (new)
- docs/openclaw_gap_runs/p125_gateway_ops_route_package_scaffold.md (new)

Task:
- Implement: Gateway ops route package scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway ops route package scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p125_gateway_ops_route_package_scaffold.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P126 - Gateway start command
Batch: B16 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p126_gateway_start_command.py (new)
- thomas/cli/commands/gateway/p126_gateway_start_command.py (new)
- tests/prompt_pack/test_p126_gateway_start_command.py (new)
- docs/openclaw_gap_runs/p126_gateway_start_command.md (new)

Task:
- Implement: Gateway start command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway start command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p126_gateway_start_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P127 - Gateway restart command
Batch: B16 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p127_gateway_restart_command.py (new)
- thomas/cli/commands/gateway/p127_gateway_restart_command.py (new)
- tests/prompt_pack/test_p127_gateway_restart_command.py (new)
- docs/openclaw_gap_runs/p127_gateway_restart_command.md (new)

Task:
- Implement: Gateway restart command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway restart command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p127_gateway_restart_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P128 - Gateway install command
Batch: B16 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p128_gateway_install_command.py (new)
- thomas/cli/commands/gateway/p128_gateway_install_command.py (new)
- tests/prompt_pack/test_p128_gateway_install_command.py (new)
- docs/openclaw_gap_runs/p128_gateway_install_command.md (new)

Task:
- Implement: Gateway install command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway install command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p128_gateway_install_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P129 - Gateway uninstall command
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p129_gateway_uninstall_command.py (new)
- thomas/cli/commands/gateway/p129_gateway_uninstall_command.py (new)
- tests/prompt_pack/test_p129_gateway_uninstall_command.py (new)
- docs/openclaw_gap_runs/p129_gateway_uninstall_command.md (new)

Task:
- Implement: Gateway uninstall command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway uninstall command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p129_gateway_uninstall_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P130 - Gateway probe command
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p130_gateway_probe_command.py (new)
- thomas/cli/commands/gateway/p130_gateway_probe_command.py (new)
- tests/prompt_pack/test_p130_gateway_probe_command.py (new)
- docs/openclaw_gap_runs/p130_gateway_probe_command.md (new)

Task:
- Implement: Gateway probe command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway probe command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p130_gateway_probe_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P131 - Gateway discover command
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p131_gateway_discover_command.py (new)
- thomas/cli/commands/gateway/p131_gateway_discover_command.py (new)
- tests/prompt_pack/test_p131_gateway_discover_command.py (new)
- docs/openclaw_gap_runs/p131_gateway_discover_command.md (new)

Task:
- Implement: Gateway discover command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway discover command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p131_gateway_discover_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P132 - Gateway configured command
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p132_gateway_configured_command.py (new)
- thomas/cli/commands/gateway/p132_gateway_configured_command.py (new)
- tests/prompt_pack/test_p132_gateway_configured_command.py (new)
- docs/openclaw_gap_runs/p132_gateway_configured_command.md (new)

Task:
- Implement: Gateway configured command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway configured command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p132_gateway_configured_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P133 - Gateway health detailed payload
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p133_gateway_health_detailed_payload.py (new)
- thomas/cli/commands/gateway/p133_gateway_health_detailed_payload.py (new)
- tests/prompt_pack/test_p133_gateway_health_detailed_payload.py (new)
- docs/openclaw_gap_runs/p133_gateway_health_detailed_payload.md (new)

Task:
- Implement: Gateway health detailed payload.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway health detailed payload" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p133_gateway_health_detailed_payload.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P134 - Gateway usage-cost command
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p134_gateway_usage_cost_command.py (new)
- thomas/cli/commands/gateway/p134_gateway_usage_cost_command.py (new)
- tests/prompt_pack/test_p134_gateway_usage_cost_command.py (new)
- docs/openclaw_gap_runs/p134_gateway_usage_cost_command.md (new)

Task:
- Implement: Gateway usage-cost command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway usage-cost command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p134_gateway_usage_cost_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P135 - Gateway state persistence model
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p135_gateway_state_persistence_model.py (new)
- thomas/cli/commands/gateway/p135_gateway_state_persistence_model.py (new)
- tests/prompt_pack/test_p135_gateway_state_persistence_model.py (new)
- docs/openclaw_gap_runs/p135_gateway_state_persistence_model.md (new)

Task:
- Implement: Gateway state persistence model.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway state persistence model" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p135_gateway_state_persistence_model.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P136 - Gateway auth policy enforcement
Batch: B17 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p136_gateway_auth_policy_enforcement.py (new)
- thomas/cli/commands/gateway/p136_gateway_auth_policy_enforcement.py (new)
- tests/prompt_pack/test_p136_gateway_auth_policy_enforcement.py (new)
- docs/openclaw_gap_runs/p136_gateway_auth_policy_enforcement.md (new)

Task:
- Implement: Gateway auth policy enforcement.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway auth policy enforcement" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p136_gateway_auth_policy_enforcement.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P137 - Gateway logs filter command
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p137_gateway_logs_filter_command.py (new)
- thomas/cli/commands/gateway/p137_gateway_logs_filter_command.py (new)
- tests/prompt_pack/test_p137_gateway_logs_filter_command.py (new)
- docs/openclaw_gap_runs/p137_gateway_logs_filter_command.md (new)

Task:
- Implement: Gateway logs filter command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway logs filter command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p137_gateway_logs_filter_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P138 - Gateway metrics snapshot command
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p138_gateway_metrics_snapshot_command.py (new)
- thomas/cli/commands/gateway/p138_gateway_metrics_snapshot_command.py (new)
- tests/prompt_pack/test_p138_gateway_metrics_snapshot_command.py (new)
- docs/openclaw_gap_runs/p138_gateway_metrics_snapshot_command.md (new)

Task:
- Implement: Gateway metrics snapshot command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway metrics snapshot command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p138_gateway_metrics_snapshot_command.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P139 - Openai compat route scaffold
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p139_openai_compat_route_scaffold.py (new)
- thomas/cli/commands/gateway/p139_openai_compat_route_scaffold.py (new)
- tests/prompt_pack/test_p139_openai_compat_route_scaffold.py (new)
- docs/openclaw_gap_runs/p139_openai_compat_route_scaffold.md (new)

Task:
- Implement: Openai compat route scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Openai compat route scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p139_openai_compat_route_scaffold.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P140 - Openai chat completions non-stream
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p140_openai_chat_completions_non_stream.py (new)
- thomas/cli/commands/gateway/p140_openai_chat_completions_non_stream.py (new)
- tests/prompt_pack/test_p140_openai_chat_completions_non_stream.py (new)
- docs/openclaw_gap_runs/p140_openai_chat_completions_non_stream.md (new)

Task:
- Implement: Openai chat completions non-stream.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Openai chat completions non-stream" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p140_openai_chat_completions_non_stream.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P141 - Openai chat completions stream
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p141_openai_chat_completions_stream.py (new)
- thomas/cli/commands/gateway/p141_openai_chat_completions_stream.py (new)
- tests/prompt_pack/test_p141_openai_chat_completions_stream.py (new)
- docs/openclaw_gap_runs/p141_openai_chat_completions_stream.md (new)

Task:
- Implement: Openai chat completions stream.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Openai chat completions stream" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p141_openai_chat_completions_stream.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P142 - Openai tool-call passthrough mapping
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p142_openai_tool_call_passthrough_mapping.py (new)
- thomas/cli/commands/gateway/p142_openai_tool_call_passthrough_mapping.py (new)
- tests/prompt_pack/test_p142_openai_tool_call_passthrough_mapping.py (new)
- docs/openclaw_gap_runs/p142_openai_tool_call_passthrough_mapping.md (new)

Task:
- Implement: Openai tool-call passthrough mapping.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Openai tool-call passthrough mapping" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p142_openai_tool_call_passthrough_mapping.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P143 - Openai error shape mapping
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p143_openai_error_shape_mapping.py (new)
- thomas/cli/commands/gateway/p143_openai_error_shape_mapping.py (new)
- tests/prompt_pack/test_p143_openai_error_shape_mapping.py (new)
- docs/openclaw_gap_runs/p143_openai_error_shape_mapping.md (new)

Task:
- Implement: Openai error shape mapping.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Openai error shape mapping" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p143_openai_error_shape_mapping.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P144 - Responses compat route scaffold
Batch: B18 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p144_responses_compat_route_scaffold.py (new)
- thomas/cli/commands/gateway/p144_responses_compat_route_scaffold.py (new)
- tests/prompt_pack/test_p144_responses_compat_route_scaffold.py (new)
- docs/openclaw_gap_runs/p144_responses_compat_route_scaffold.md (new)

Task:
- Implement: Responses compat route scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Responses compat route scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p144_responses_compat_route_scaffold.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P145 - Responses create non-stream
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p145_responses_create_non_stream.py (new)
- thomas/cli/commands/gateway/p145_responses_create_non_stream.py (new)
- tests/prompt_pack/test_p145_responses_create_non_stream.py (new)
- docs/openclaw_gap_runs/p145_responses_create_non_stream.md (new)

Task:
- Implement: Responses create non-stream.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Responses create non-stream" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p145_responses_create_non_stream.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P146 - Responses create stream events
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p146_responses_create_stream_events.py (new)
- thomas/cli/commands/gateway/p146_responses_create_stream_events.py (new)
- tests/prompt_pack/test_p146_responses_create_stream_events.py (new)
- docs/openclaw_gap_runs/p146_responses_create_stream_events.md (new)

Task:
- Implement: Responses create stream events.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Responses create stream events" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p146_responses_create_stream_events.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P147 - Responses tool result mapping
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p147_responses_tool_result_mapping.py (new)
- thomas/cli/commands/gateway/p147_responses_tool_result_mapping.py (new)
- tests/prompt_pack/test_p147_responses_tool_result_mapping.py (new)
- docs/openclaw_gap_runs/p147_responses_tool_result_mapping.md (new)

Task:
- Implement: Responses tool result mapping.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Responses tool result mapping" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p147_responses_tool_result_mapping.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P148 - Compat model capability resolver
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p148_compat_model_capability_resolver.py (new)
- thomas/cli/commands/gateway/p148_compat_model_capability_resolver.py (new)
- tests/prompt_pack/test_p148_compat_model_capability_resolver.py (new)
- docs/openclaw_gap_runs/p148_compat_model_capability_resolver.md (new)

Task:
- Implement: Compat model capability resolver.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Compat model capability resolver" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p148_compat_model_capability_resolver.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P149 - Compat request validation layer
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p149_compat_request_validation_layer.py (new)
- thomas/cli/commands/gateway/p149_compat_request_validation_layer.py (new)
- tests/prompt_pack/test_p149_compat_request_validation_layer.py (new)
- docs/openclaw_gap_runs/p149_compat_request_validation_layer.md (new)

Task:
- Implement: Compat request validation layer.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Compat request validation layer" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p149_compat_request_validation_layer.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P150 - Compat auth and rate-limit middleware
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p150_compat_auth_and_rate_limit_middleware.py (new)
- thomas/cli/commands/gateway/p150_compat_auth_and_rate_limit_middleware.py (new)
- tests/prompt_pack/test_p150_compat_auth_and_rate_limit_middleware.py (new)
- docs/openclaw_gap_runs/p150_compat_auth_and_rate_limit_middleware.md (new)

Task:
- Implement: Compat auth and rate-limit middleware.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Compat auth and rate-limit middleware" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p150_compat_auth_and_rate_limit_middleware.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P151 - Compat usage accounting integration
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p151_compat_usage_accounting_integration.py (new)
- thomas/cli/commands/gateway/p151_compat_usage_accounting_integration.py (new)
- tests/prompt_pack/test_p151_compat_usage_accounting_integration.py (new)
- docs/openclaw_gap_runs/p151_compat_usage_accounting_integration.md (new)

Task:
- Implement: Compat usage accounting integration.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Compat usage accounting integration" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p151_compat_usage_accounting_integration.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P152 - Gateway and compat integration tests
Batch: B19 | Lane: Plugins and Gateway API | Domain: gateway

```text
Project root: <repo_root>

Context to read first:
- thomas/cli/parity_commands.py
- thomas/server/app.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/server/routes/gateway/p152_gateway_and_compat_integration_tests.py (new)
- thomas/server/routes/core_aiohttp.py
- thomas/cli/commands/gateway/p152_gateway_and_compat_integration_tests.py (new)
- tests/prompt_pack/test_p152_gateway_and_compat_integration_tests.py (new)
- docs/openclaw_gap_runs/p152_gateway_and_compat_integration_tests.md (new)

Task:
- Implement: Gateway and compat integration tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway and compat integration tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/server/routes/core_aiohttp.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p152_gateway_and_compat_integration_tests.py
- python -m pytest -q tests/test_server_access_mode.py tests/test_server_chats_api.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P153 - Memory command package scaffold
Batch: B20 | Lane: Memory Security System Approvals | Domain: memory

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/v2/fabric.py
- thomas/memory/curator.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/memory/p153_memory_command_package_scaffold.py (new)
- thomas/memory/p153_memory_command_package_scaffold.py (new)
- tests/prompt_pack/test_p153_memory_command_package_scaffold.py (new)
- docs/openclaw_gap_runs/p153_memory_command_package_scaffold.md (new)

Task:
- Implement: Memory command package scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Memory command package scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p153_memory_command_package_scaffold.py
- python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P154 - Memory index command
Batch: B20 | Lane: Memory Security System Approvals | Domain: memory

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/v2/fabric.py
- thomas/memory/curator.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/memory/p154_memory_index_command.py (new)
- thomas/memory/p154_memory_index_command.py (new)
- tests/prompt_pack/test_p154_memory_index_command.py (new)
- docs/openclaw_gap_runs/p154_memory_index_command.md (new)

Task:
- Implement: Memory index command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Memory index command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p154_memory_index_command.py
- python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P155 - Memory search command
Batch: B20 | Lane: Memory Security System Approvals | Domain: memory

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/v2/fabric.py
- thomas/memory/curator.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/memory/p155_memory_search_command.py (new)
- thomas/memory/p155_memory_search_command.py (new)
- tests/prompt_pack/test_p155_memory_search_command.py (new)
- docs/openclaw_gap_runs/p155_memory_search_command.md (new)

Task:
- Implement: Memory search command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Memory search command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p155_memory_search_command.py
- python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P156 - Memory status command
Batch: B20 | Lane: Memory Security System Approvals | Domain: memory

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/v2/fabric.py
- thomas/memory/curator.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/memory/p156_memory_status_command.py (new)
- thomas/memory/p156_memory_status_command.py (new)
- tests/prompt_pack/test_p156_memory_status_command.py (new)
- docs/openclaw_gap_runs/p156_memory_status_command.md (new)

Task:
- Implement: Memory status command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Memory status command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p156_memory_status_command.py
- python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P157 - Memory rebuild command
Batch: B20 | Lane: Memory Security System Approvals | Domain: memory

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/v2/fabric.py
- thomas/memory/curator.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/memory/p157_memory_rebuild_command.py (new)
- thomas/memory/p157_memory_rebuild_command.py (new)
- tests/prompt_pack/test_p157_memory_rebuild_command.py (new)
- docs/openclaw_gap_runs/p157_memory_rebuild_command.md (new)

Task:
- Implement: Memory rebuild command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Memory rebuild command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p157_memory_rebuild_command.py
- python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P158 - Memory cli integration
Batch: B20 | Lane: Memory Security System Approvals | Domain: memory

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/v2/fabric.py
- thomas/memory/curator.py
- thomas/cli/main.py

Ownership (edit only these paths):
- thomas/cli/commands/memory/p158_memory_cli_integration.py (new)
- thomas/cli/main.py
- thomas/memory/p158_memory_cli_integration.py (new)
- tests/prompt_pack/test_p158_memory_cli_integration.py (new)
- docs/openclaw_gap_runs/p158_memory_cli_integration.md (new)

Task:
- Implement: Memory cli integration.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Memory cli integration" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p158_memory_cli_integration.py
- python -m pytest -q tests/test_memory_fabric_v2.py tests/test_memory_curator.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P159 - Security command package scaffold
Batch: B20 | Lane: Memory Security System Approvals | Domain: security

```text
Project root: <repo_root>

Context to read first:
- thomas/policy/config.py
- thomas/policy/policy.py
- thomas/tools/windows_auth.py

Ownership (edit only these paths):
- thomas/cli/commands/security/p159_security_command_package_scaffold.py (new)
- thomas/security/p159_security_command_package_scaffold.py (new)
- tests/prompt_pack/test_p159_security_command_package_scaffold.py (new)
- docs/openclaw_gap_runs/p159_security_command_package_scaffold.md (new)

Task:
- Implement: Security command package scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Security command package scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p159_security_command_package_scaffold.py
- python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P160 - Security audit command
Batch: B20 | Lane: Memory Security System Approvals | Domain: security

```text
Project root: <repo_root>

Context to read first:
- thomas/policy/config.py
- thomas/policy/policy.py
- thomas/tools/windows_auth.py

Ownership (edit only these paths):
- thomas/cli/commands/security/p160_security_audit_command.py (new)
- thomas/security/p160_security_audit_command.py (new)
- tests/prompt_pack/test_p160_security_audit_command.py (new)
- docs/openclaw_gap_runs/p160_security_audit_command.md (new)

Task:
- Implement: Security audit command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Security audit command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p160_security_audit_command.py
- python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P161 - Security config-check command
Batch: B21 | Lane: Memory Security System Approvals | Domain: security

```text
Project root: <repo_root>

Context to read first:
- thomas/policy/config.py
- thomas/policy/policy.py
- thomas/tools/windows_auth.py

Ownership (edit only these paths):
- thomas/cli/commands/security/p161_security_config_check_command.py (new)
- thomas/security/p161_security_config_check_command.py (new)
- tests/prompt_pack/test_p161_security_config_check_command.py (new)
- docs/openclaw_gap_runs/p161_security_config_check_command.md (new)

Task:
- Implement: Security config-check command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Security config-check command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p161_security_config_check_command.py
- python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P162 - Security secrets-check command
Batch: B21 | Lane: Memory Security System Approvals | Domain: security

```text
Project root: <repo_root>

Context to read first:
- thomas/policy/config.py
- thomas/policy/policy.py
- thomas/tools/windows_auth.py

Ownership (edit only these paths):
- thomas/cli/commands/security/p162_security_secrets_check_command.py (new)
- thomas/security/p162_security_secrets_check_command.py (new)
- tests/prompt_pack/test_p162_security_secrets_check_command.py (new)
- docs/openclaw_gap_runs/p162_security_secrets_check_command.md (new)

Task:
- Implement: Security secrets-check command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Security secrets-check command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p162_security_secrets_check_command.py
- python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P163 - Security policy-status command
Batch: B21 | Lane: Memory Security System Approvals | Domain: security

```text
Project root: <repo_root>

Context to read first:
- thomas/policy/config.py
- thomas/policy/policy.py
- thomas/tools/windows_auth.py

Ownership (edit only these paths):
- thomas/cli/commands/security/p163_security_policy_status_command.py (new)
- thomas/security/p163_security_policy_status_command.py (new)
- tests/prompt_pack/test_p163_security_policy_status_command.py (new)
- docs/openclaw_gap_runs/p163_security_policy_status_command.md (new)

Task:
- Implement: Security policy-status command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Security policy-status command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p163_security_policy_status_command.py
- python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P164 - Security cli integration
Batch: B21 | Lane: Memory Security System Approvals | Domain: security

```text
Project root: <repo_root>

Context to read first:
- thomas/policy/config.py
- thomas/policy/policy.py
- thomas/tools/windows_auth.py

Ownership (edit only these paths):
- thomas/cli/commands/security/p164_security_cli_integration.py (new)
- thomas/cli/main.py
- thomas/security/p164_security_cli_integration.py (new)
- tests/prompt_pack/test_p164_security_cli_integration.py (new)
- docs/openclaw_gap_runs/p164_security_cli_integration.md (new)

Task:
- Implement: Security cli integration.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Security cli integration" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p164_security_cli_integration.py
- python -m pytest -q tests/test_policy_redact.py tests/test_server_access_mode.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P165 - System command package scaffold
Batch: B21 | Lane: Memory Security System Approvals | Domain: system

```text
Project root: <repo_root>

Context to read first:
- thomas/core/events.py
- thomas/server/routes/runs.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/system/p165_system_command_package_scaffold.py (new)
- thomas/system/p165_system_command_package_scaffold.py (new)
- tests/prompt_pack/test_p165_system_command_package_scaffold.py (new)
- docs/openclaw_gap_runs/p165_system_command_package_scaffold.md (new)

Task:
- Implement: System command package scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "System command package scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p165_system_command_package_scaffold.py
- python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P166 - System heartbeat command
Batch: B21 | Lane: Memory Security System Approvals | Domain: system

```text
Project root: <repo_root>

Context to read first:
- thomas/core/events.py
- thomas/server/routes/runs.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/system/p166_system_heartbeat_command.py (new)
- thomas/system/p166_system_heartbeat_command.py (new)
- tests/prompt_pack/test_p166_system_heartbeat_command.py (new)
- docs/openclaw_gap_runs/p166_system_heartbeat_command.md (new)

Task:
- Implement: System heartbeat command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "System heartbeat command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p166_system_heartbeat_command.py
- python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P167 - System presence command
Batch: B21 | Lane: Memory Security System Approvals | Domain: system

```text
Project root: <repo_root>

Context to read first:
- thomas/core/events.py
- thomas/server/routes/runs.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/system/p167_system_presence_command.py (new)
- thomas/system/p167_system_presence_command.py (new)
- tests/prompt_pack/test_p167_system_presence_command.py (new)
- docs/openclaw_gap_runs/p167_system_presence_command.md (new)

Task:
- Implement: System presence command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "System presence command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p167_system_presence_command.py
- python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P168 - System events tail command
Batch: B21 | Lane: Memory Security System Approvals | Domain: system

```text
Project root: <repo_root>

Context to read first:
- thomas/core/events.py
- thomas/server/routes/runs.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/system/p168_system_events_tail_command.py (new)
- thomas/system/p168_system_events_tail_command.py (new)
- tests/prompt_pack/test_p168_system_events_tail_command.py (new)
- docs/openclaw_gap_runs/p168_system_events_tail_command.md (new)

Task:
- Implement: System events tail command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "System events tail command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p168_system_events_tail_command.py
- python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P169 - System diagnostics command
Batch: B22 | Lane: Memory Security System Approvals | Domain: system

```text
Project root: <repo_root>

Context to read first:
- thomas/core/events.py
- thomas/server/routes/runs.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/system/p169_system_diagnostics_command.py (new)
- thomas/system/p169_system_diagnostics_command.py (new)
- tests/prompt_pack/test_p169_system_diagnostics_command.py (new)
- docs/openclaw_gap_runs/p169_system_diagnostics_command.md (new)

Task:
- Implement: System diagnostics command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "System diagnostics command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p169_system_diagnostics_command.py
- python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P170 - System cli integration
Batch: B22 | Lane: Memory Security System Approvals | Domain: system

```text
Project root: <repo_root>

Context to read first:
- thomas/core/events.py
- thomas/server/routes/runs.py
- thomas/server/routes/core_aiohttp.py

Ownership (edit only these paths):
- thomas/cli/commands/system/p170_system_cli_integration.py (new)
- thomas/cli/main.py
- thomas/system/p170_system_cli_integration.py (new)
- tests/prompt_pack/test_p170_system_cli_integration.py (new)
- docs/openclaw_gap_runs/p170_system_cli_integration.md (new)

Task:
- Implement: System cli integration.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "System cli integration" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p170_system_cli_integration.py
- python -m pytest -q tests/test_server_usage_invariants.py tests/test_server_done_usage_contract.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P171 - Approvals command package scaffold
Batch: B22 | Lane: Memory Security System Approvals | Domain: approvals

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/autonomy.py
- thomas/autonomy/store.py
- thomas/cli/parity_compat.py

Ownership (edit only these paths):
- thomas/cli/commands/approvals/p171_approvals_command_package_scaffold.py (new)
- thomas/approvals/p171_approvals_command_package_scaffold.py (new)
- tests/prompt_pack/test_p171_approvals_command_package_scaffold.py (new)
- docs/openclaw_gap_runs/p171_approvals_command_package_scaffold.md (new)

Task:
- Implement: Approvals command package scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Approvals command package scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p171_approvals_command_package_scaffold.py
- python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P172 - Approvals get command
Batch: B22 | Lane: Memory Security System Approvals | Domain: approvals

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/autonomy.py
- thomas/autonomy/store.py
- thomas/cli/parity_compat.py

Ownership (edit only these paths):
- thomas/cli/commands/approvals/p172_approvals_get_command.py (new)
- thomas/approvals/p172_approvals_get_command.py (new)
- tests/prompt_pack/test_p172_approvals_get_command.py (new)
- docs/openclaw_gap_runs/p172_approvals_get_command.md (new)

Task:
- Implement: Approvals get command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Approvals get command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p172_approvals_get_command.py
- python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P173 - Approvals set command
Batch: B22 | Lane: Memory Security System Approvals | Domain: approvals

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/autonomy.py
- thomas/autonomy/store.py
- thomas/cli/parity_compat.py

Ownership (edit only these paths):
- thomas/cli/commands/approvals/p173_approvals_set_command.py (new)
- thomas/approvals/p173_approvals_set_command.py (new)
- tests/prompt_pack/test_p173_approvals_set_command.py (new)
- docs/openclaw_gap_runs/p173_approvals_set_command.md (new)

Task:
- Implement: Approvals set command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Approvals set command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p173_approvals_set_command.py
- python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P174 - Approvals allowlist command
Batch: B22 | Lane: Memory Security System Approvals | Domain: approvals

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/autonomy.py
- thomas/autonomy/store.py
- thomas/cli/parity_compat.py

Ownership (edit only these paths):
- thomas/cli/commands/approvals/p174_approvals_allowlist_command.py (new)
- thomas/approvals/p174_approvals_allowlist_command.py (new)
- tests/prompt_pack/test_p174_approvals_allowlist_command.py (new)
- docs/openclaw_gap_runs/p174_approvals_allowlist_command.md (new)

Task:
- Implement: Approvals allowlist command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Approvals allowlist command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p174_approvals_allowlist_command.py
- python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P175 - Approvals revoke reset command
Batch: B22 | Lane: Memory Security System Approvals | Domain: approvals

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/autonomy.py
- thomas/autonomy/store.py
- thomas/cli/parity_compat.py

Ownership (edit only these paths):
- thomas/cli/commands/approvals/p175_approvals_revoke_reset_command.py (new)
- thomas/approvals/p175_approvals_revoke_reset_command.py (new)
- tests/prompt_pack/test_p175_approvals_revoke_reset_command.py (new)
- docs/openclaw_gap_runs/p175_approvals_revoke_reset_command.md (new)

Task:
- Implement: Approvals revoke reset command.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Approvals revoke reset command" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p175_approvals_revoke_reset_command.py
- python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P176 - Approvals cli integration
Batch: B22 | Lane: Memory Security System Approvals | Domain: approvals

```text
Project root: <repo_root>

Context to read first:
- thomas/memory/autonomy.py
- thomas/autonomy/store.py
- thomas/cli/parity_compat.py

Ownership (edit only these paths):
- thomas/cli/commands/approvals/p176_approvals_cli_integration.py (new)
- thomas/cli/main.py
- thomas/approvals/p176_approvals_cli_integration.py (new)
- tests/prompt_pack/test_p176_approvals_cli_integration.py (new)
- docs/openclaw_gap_runs/p176_approvals_cli_integration.md (new)

Task:
- Implement: Approvals cli integration.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Approvals cli integration" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `thomas/cli/main.py` without regressing existing commands/routes.
7) Support machine-readable output mode for automation (`--json` or route JSON schema).

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p176_approvals_cli_integration.py
- python -m pytest -q tests/test_approval_broker.py tests/test_autonomy_api.py -k "approval"

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P177 - Gap score script scaffold
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p177_gap_score_script_scaffold.py (new)
- tests/prompt_pack/test_p177_gap_score_script_scaffold.py (new)
- docs/openclaw_gap_runs/p177_gap_score_script_scaffold.md (new)

Task:
- Implement: Gap score script scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score script scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p177_gap_score_script_scaffold.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P178 - Gap score loc collector
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p178_gap_score_loc_collector.py (new)
- tests/prompt_pack/test_p178_gap_score_loc_collector.py (new)
- docs/openclaw_gap_runs/p178_gap_score_loc_collector.md (new)

Task:
- Implement: Gap score loc collector.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score loc collector" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p178_gap_score_loc_collector.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P179 - Gap score test-loc collector
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p179_gap_score_test_loc_collector.py (new)
- tests/prompt_pack/test_p179_gap_score_test_loc_collector.py (new)
- docs/openclaw_gap_runs/p179_gap_score_test_loc_collector.md (new)

Task:
- Implement: Gap score test-loc collector.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score test-loc collector" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p179_gap_score_test_loc_collector.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P180 - Gap score cli-depth collector
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p180_gap_score_cli_depth_collector.py (new)
- tests/prompt_pack/test_p180_gap_score_cli_depth_collector.py (new)
- docs/openclaw_gap_runs/p180_gap_score_cli_depth_collector.md (new)

Task:
- Implement: Gap score cli-depth collector.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score cli-depth collector" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p180_gap_score_cli_depth_collector.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P181 - Gap score extension and app collector
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p181_gap_score_extension_and_app_collector.py (new)
- tests/prompt_pack/test_p181_gap_score_extension_and_app_collector.py (new)
- docs/openclaw_gap_runs/p181_gap_score_extension_and_app_collector.md (new)

Task:
- Implement: Gap score extension and app collector.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score extension and app collector" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p181_gap_score_extension_and_app_collector.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P182 - Gap score weighted formula
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p182_gap_score_weighted_formula.py (new)
- tests/prompt_pack/test_p182_gap_score_weighted_formula.py (new)
- docs/openclaw_gap_runs/p182_gap_score_weighted_formula.md (new)

Task:
- Implement: Gap score weighted formula.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score weighted formula" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p182_gap_score_weighted_formula.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P183 - Gap score markdown renderer
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p183_gap_score_markdown_renderer.py (new)
- tests/prompt_pack/test_p183_gap_score_markdown_renderer.py (new)
- docs/openclaw_gap_runs/p183_gap_score_markdown_renderer.md (new)

Task:
- Implement: Gap score markdown renderer.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score markdown renderer" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p183_gap_score_markdown_renderer.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P184 - Gap score json output contract
Batch: B23 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p184_gap_score_json_output_contract.py (new)
- tests/prompt_pack/test_p184_gap_score_json_output_contract.py (new)
- docs/openclaw_gap_runs/p184_gap_score_json_output_contract.md (new)

Task:
- Implement: Gap score json output contract.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap score json output contract" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p184_gap_score_json_output_contract.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P185 - Test gap score script
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p185_test_gap_score_script.py (new)
- tests/prompt_pack/test_p185_test_gap_score_script.py (new)
- docs/openclaw_gap_runs/p185_test_gap_score_script.md (new)

Task:
- Implement: Test gap score script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Test gap score script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p185_test_gap_score_script.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P186 - Openclaw gap gate script scaffold
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p186_openclaw_gap_gate_script_scaffold.py (new)
- tests/prompt_pack/test_p186_openclaw_gap_gate_script_scaffold.py (new)
- docs/openclaw_gap_runs/p186_openclaw_gap_gate_script_scaffold.md (new)

Task:
- Implement: Openclaw gap gate script scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Openclaw gap gate script scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p186_openclaw_gap_gate_script_scaffold.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P187 - Gap gate threshold policy
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p187_gap_gate_threshold_policy.py (new)
- tests/prompt_pack/test_p187_gap_gate_threshold_policy.py (new)
- docs/openclaw_gap_runs/p187_gap_gate_threshold_policy.md (new)

Task:
- Implement: Gap gate threshold policy.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap gate threshold policy" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p187_gap_gate_threshold_policy.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P188 - Gap gate docs-update check
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p188_gap_gate_docs_update_check.py (new)
- tests/prompt_pack/test_p188_gap_gate_docs_update_check.py (new)
- docs/openclaw_gap_runs/p188_gap_gate_docs_update_check.md (new)

Task:
- Implement: Gap gate docs-update check.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap gate docs-update check" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p188_gap_gate_docs_update_check.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P189 - Gap gate ci wiring
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p189_gap_gate_ci_wiring.py (new)
- .github/workflows/robustness-gates.yml
- tests/prompt_pack/test_p189_gap_gate_ci_wiring.py (new)
- docs/openclaw_gap_runs/p189_gap_gate_ci_wiring.md (new)

Task:
- Implement: Gap gate ci wiring.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap gate ci wiring" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `.github/workflows/robustness-gates.yml` without regressing existing commands/routes.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p189_gap_gate_ci_wiring.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P190 - Test gap gate script
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p190_test_gap_gate_script.py (new)
- tests/prompt_pack/test_p190_test_gap_gate_script.py (new)
- docs/openclaw_gap_runs/p190_test_gap_gate_script.md (new)

Task:
- Implement: Test gap gate script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Test gap gate script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p190_test_gap_gate_script.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P191 - Cli depth report generator scaffold
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p191_cli_depth_report_generator_scaffold.py (new)
- tests/prompt_pack/test_p191_cli_depth_report_generator_scaffold.py (new)
- docs/openclaw_gap_runs/p191_cli_depth_report_generator_scaffold.md (new)

Task:
- Implement: Cli depth report generator scaffold.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Cli depth report generator scaffold" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p191_cli_depth_report_generator_scaffold.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P192 - Cli depth parser
Batch: B24 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p192_cli_depth_parser.py (new)
- tests/prompt_pack/test_p192_cli_depth_parser.py (new)
- docs/openclaw_gap_runs/p192_cli_depth_parser.md (new)

Task:
- Implement: Cli depth parser.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Cli depth parser" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p192_cli_depth_parser.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P193 - Cli depth markdown trend report
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p193_cli_depth_markdown_trend_report.py (new)
- tests/prompt_pack/test_p193_cli_depth_markdown_trend_report.py (new)
- docs/openclaw_gap_runs/p193_cli_depth_markdown_trend_report.md (new)

Task:
- Implement: Cli depth markdown trend report.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Cli depth markdown trend report" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p193_cli_depth_markdown_trend_report.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P194 - Test cli depth report generator
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p194_test_cli_depth_report_generator.py (new)
- tests/prompt_pack/test_p194_test_cli_depth_report_generator.py (new)
- docs/openclaw_gap_runs/p194_test_cli_depth_report_generator.md (new)

Task:
- Implement: Test cli depth report generator.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Test cli depth report generator" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p194_test_cli_depth_report_generator.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P195 - Browser regression test matrix
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p195_browser_regression_test_matrix.py (new)
- tests/prompt_pack/test_p195_browser_regression_test_matrix.py (new)
- docs/openclaw_gap_runs/p195_browser_regression_test_matrix.md (new)

Task:
- Implement: Browser regression test matrix.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Browser regression test matrix" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p195_browser_regression_test_matrix.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P196 - Node regression test matrix
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p196_node_regression_test_matrix.py (new)
- tests/prompt_pack/test_p196_node_regression_test_matrix.py (new)
- docs/openclaw_gap_runs/p196_node_regression_test_matrix.md (new)

Task:
- Implement: Node regression test matrix.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Node regression test matrix" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p196_node_regression_test_matrix.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P197 - Message regression test matrix
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p197_message_regression_test_matrix.py (new)
- tests/prompt_pack/test_p197_message_regression_test_matrix.py (new)
- docs/openclaw_gap_runs/p197_message_regression_test_matrix.md (new)

Task:
- Implement: Message regression test matrix.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Message regression test matrix" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p197_message_regression_test_matrix.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P198 - Channels regression test matrix
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p198_channels_regression_test_matrix.py (new)
- tests/prompt_pack/test_p198_channels_regression_test_matrix.py (new)
- docs/openclaw_gap_runs/p198_channels_regression_test_matrix.md (new)

Task:
- Implement: Channels regression test matrix.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Channels regression test matrix" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p198_channels_regression_test_matrix.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P199 - Plugin regression test matrix
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p199_plugin_regression_test_matrix.py (new)
- tests/prompt_pack/test_p199_plugin_regression_test_matrix.py (new)
- docs/openclaw_gap_runs/p199_plugin_regression_test_matrix.md (new)

Task:
- Implement: Plugin regression test matrix.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Plugin regression test matrix" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p199_plugin_regression_test_matrix.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P200 - Gateway compat regression tests
Batch: B25 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p200_gateway_compat_regression_tests.py (new)
- tests/prompt_pack/test_p200_gateway_compat_regression_tests.py (new)
- docs/openclaw_gap_runs/p200_gateway_compat_regression_tests.md (new)

Task:
- Implement: Gateway compat regression tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gateway compat regression tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p200_gateway_compat_regression_tests.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P201 - Responses stream contract tests
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p201_responses_stream_contract_tests.py (new)
- tests/prompt_pack/test_p201_responses_stream_contract_tests.py (new)
- docs/openclaw_gap_runs/p201_responses_stream_contract_tests.md (new)

Task:
- Implement: Responses stream contract tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Responses stream contract tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p201_responses_stream_contract_tests.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P202 - Auth hardening regression tests
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p202_auth_hardening_regression_tests.py (new)
- tests/prompt_pack/test_p202_auth_hardening_regression_tests.py (new)
- docs/openclaw_gap_runs/p202_auth_hardening_regression_tests.md (new)

Task:
- Implement: Auth hardening regression tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Auth hardening regression tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p202_auth_hardening_regression_tests.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P203 - Alias compatibility regression tests
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p203_alias_compatibility_regression_tests.py (new)
- tests/prompt_pack/test_p203_alias_compatibility_regression_tests.py (new)
- docs/openclaw_gap_runs/p203_alias_compatibility_regression_tests.md (new)

Task:
- Implement: Alias compatibility regression tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Alias compatibility regression tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p203_alias_compatibility_regression_tests.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P204 - Non-loopback security regression tests
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p204_non_loopback_security_regression_tests.py (new)
- tests/prompt_pack/test_p204_non_loopback_security_regression_tests.py (new)
- docs/openclaw_gap_runs/p204_non_loopback_security_regression_tests.md (new)

Task:
- Implement: Non-loopback security regression tests.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Non-loopback security regression tests" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p204_non_loopback_security_regression_tests.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P205 - Parallel prompt batch runner script
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p205_parallel_prompt_batch_runner_script.py (new)
- tests/prompt_pack/test_p205_parallel_prompt_batch_runner_script.py (new)
- docs/openclaw_gap_runs/p205_parallel_prompt_batch_runner_script.md (new)

Task:
- Implement: Parallel prompt batch runner script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Parallel prompt batch runner script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p205_parallel_prompt_batch_runner_script.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P206 - Prompt merge guard script
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p206_prompt_merge_guard_script.py (new)
- tests/prompt_pack/test_p206_prompt_merge_guard_script.py (new)
- docs/openclaw_gap_runs/p206_prompt_merge_guard_script.md (new)

Task:
- Implement: Prompt merge guard script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Prompt merge guard script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p206_prompt_merge_guard_script.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P207 - Prompt conflict detector script
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p207_prompt_conflict_detector_script.py (new)
- tests/prompt_pack/test_p207_prompt_conflict_detector_script.py (new)
- docs/openclaw_gap_runs/p207_prompt_conflict_detector_script.md (new)

Task:
- Implement: Prompt conflict detector script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Prompt conflict detector script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p207_prompt_conflict_detector_script.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P208 - Smoke umbrella script
Batch: B26 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p208_smoke_umbrella_script.py (new)
- tests/prompt_pack/test_p208_smoke_umbrella_script.py (new)
- docs/openclaw_gap_runs/p208_smoke_umbrella_script.md (new)

Task:
- Implement: Smoke umbrella script.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Smoke umbrella script" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p208_smoke_umbrella_script.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P209 - Nightly benchmark runner update
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p209_nightly_benchmark_runner_update.py (new)
- tests/prompt_pack/test_p209_nightly_benchmark_runner_update.py (new)
- docs/openclaw_gap_runs/p209_nightly_benchmark_runner_update.md (new)

Task:
- Implement: Nightly benchmark runner update.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Nightly benchmark runner update" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p209_nightly_benchmark_runner_update.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P210 - Ci test shard matrix
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p210_ci_test_shard_matrix.py (new)
- .github/workflows/robustness-gates.yml
- tests/prompt_pack/test_p210_ci_test_shard_matrix.py (new)
- docs/openclaw_gap_runs/p210_ci_test_shard_matrix.md (new)

Task:
- Implement: Ci test shard matrix.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Ci test shard matrix" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `.github/workflows/robustness-gates.yml` without regressing existing commands/routes.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p210_ci_test_shard_matrix.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P211 - Ci timeout and retry policy
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p211_ci_timeout_and_retry_policy.py (new)
- tests/prompt_pack/test_p211_ci_timeout_and_retry_policy.py (new)
- docs/openclaw_gap_runs/p211_ci_timeout_and_retry_policy.md (new)

Task:
- Implement: Ci timeout and retry policy.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Ci timeout and retry policy" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p211_ci_timeout_and_retry_policy.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P212 - Changelog automation helper
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p212_changelog_automation_helper.py (new)
- CHANGELOG.md
- tests/prompt_pack/test_p212_changelog_automation_helper.py (new)
- docs/openclaw_gap_runs/p212_changelog_automation_helper.md (new)

Task:
- Implement: Changelog automation helper.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Changelog automation helper" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `CHANGELOG.md` without regressing existing commands/routes.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p212_changelog_automation_helper.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P213 - Gap changelog entry validator
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p213_gap_changelog_entry_validator.py (new)
- docs/OPENCLAW_GAP_CHANGELOG.md
- tests/prompt_pack/test_p213_gap_changelog_entry_validator.py (new)
- docs/openclaw_gap_runs/p213_gap_changelog_entry_validator.md (new)

Task:
- Implement: Gap changelog entry validator.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Gap changelog entry validator" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `docs/OPENCLAW_GAP_CHANGELOG.md` without regressing existing commands/routes.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p213_gap_changelog_entry_validator.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P214 - Release readiness checklist automation
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p214_release_readiness_checklist_automation.py (new)
- tests/prompt_pack/test_p214_release_readiness_checklist_automation.py (new)
- docs/openclaw_gap_runs/p214_release_readiness_checklist_automation.md (new)

Task:
- Implement: Release readiness checklist automation.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Release readiness checklist automation" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p214_release_readiness_checklist_automation.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P215 - Final integration acceptance suite
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p215_final_integration_acceptance_suite.py (new)
- tests/prompt_pack/test_p215_final_integration_acceptance_suite.py (new)
- docs/openclaw_gap_runs/p215_final_integration_acceptance_suite.md (new)

Task:
- Implement: Final integration acceptance suite.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Final integration acceptance suite" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p215_final_integration_acceptance_suite.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```

## Prompt P216 - Final scoreboard and handoff report template
Batch: B27 | Lane: Tests CI Hardening | Domain: hardening

```text
Project root: <repo_root>

Context to read first:
- scripts/check_competitive_scope_gate.py
- scripts/check_surface_parity.py
- docs/OPENCLAW_GAP_CHANGELOG.md

Ownership (edit only these paths):
- scripts/p216_final_scoreboard_and_handoff_report_template.py (new)
- docs/OPENCLAW_GAP_CHANGELOG.md
- tests/prompt_pack/test_p216_final_scoreboard_and_handoff_report_template.py (new)
- docs/openclaw_gap_runs/p216_final_scoreboard_and_handoff_report_template.md (new)

Task:
- Implement: Final scoreboard and handoff report template.
- Build against the existing Thomas codebase and interfaces in the context files.

Implementation requirements:
1) Implement "Final scoreboard and handoff report template" as Thomas-native behavior with no OpenClaw naming reuse.
2) If package directories are missing, create them with minimal __init__.py files.
3) Define clear input and output contracts (TypedDict/dataclass or equivalent) for the new path.
4) Handle invalid input, missing config, and external failure with deterministic errors.
5) Add success and failure tests in the owned test file.
6) Wire the feature into `docs/OPENCLAW_GAP_CHANGELOG.md` without regressing existing commands/routes.

Acceptance checks:
- python -m pytest -q tests/prompt_pack/test_p216_final_scoreboard_and_handoff_report_template.py
- python -m pytest -q tests/test_repo_hygiene.py tests/test_monolith_guard.py

Return format:
- Unified diff only.
- Then exact test commands executed.
- Then short risk list.
```



