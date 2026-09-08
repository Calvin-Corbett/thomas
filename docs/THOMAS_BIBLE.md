# Thomas technical reference

This is the public technical baseline for the source distribution. It describes component responsibilities and entry points. It is not a record of development conversations, historical test runs, or individual installations.

Version: 0.19.37. Updated: 2026-09-08.

## Entry points

- `thomas/cli/main.py`: command-line application, exposed as `thomas`.
- `thomas/server/__main__.py`: server command-line entry point.
- `thomas/server/app.py`: web application assembly.
- `run-ui.cmd`: Windows setup and browser launch.
- `desktop/main.js`: optional Electron desktop shell.

Inspect the current imports and route registrations when tracing behavior. Documentation does not replace execution evidence.

## Core services

`thomas/core/` provides configuration, model clients, persistence, task coordination, and shared policy services. Changes should preserve the dependency direction documented in `thomas/_architecture.py`.

`thomas/agent/` contains the agent loop and its execution support. Tools are defined under `thomas/tools/`. Tool access depends on configured policy and runtime permissions.

`thomas/memory/` contains conversation and retrieval stores. Local data directories and profiles are described in [DATA_DIR_AND_PROFILES.md](support/DATA_DIR_AND_PROFILES.md).

## Chat

The chat server routes live under `thomas/server/routes/`. Chat delegation and delivery modules live directly under `thomas/server/`. The UI begins with the HTML page and the script files that page loads.

A conversation can answer directly, use available tools, or delegate work. Completion reporting should reflect recorded outcomes, including partial results and failures. Check the selected provider's capabilities when diagnosing tool behavior.

## Build

`thomas/forge/anvil/` contains development dispatch, project handling, verification, preview, and self-edit support. Build work must use the intended workspace and respect file ownership and permissions.

Generated projects and verification outputs are user data. They are not part of this source distribution.

## Work

`thomas/work/` and `thomas/marketplace/autonomy/` provide job storage, workflows, and execution services. Server routes expose the configured jobs and their runs to the UI.

Scheduling depends on the configured runtime. A saved schedule does not by itself prove a job ran; inspect the associated execution record.

## Browser and desktop

`thomas/server/web/` contains the web application. Trace scripts from their HTML entry point or explicit loader manifest before editing them. The optional Electron shell is under `desktop/`.

See [DESKTOP.md](DESKTOP.md) for setup and platform limitations.

## Models and integrations

`thomas/models/` and the provider clients manage model configuration and routing. Optional integrations require their own dependencies and credentials.

`extensions/` contains extension manifests. `thomas/marketplace/` includes domain-specific implementations; their support level and prerequisites vary. Do not treat every registered implementation as a configured feature.

## Contributor coordination

The source distribution includes an empty `plans/thomas/WORKBOARD.md` template for local development tools. Populate coordination records only in local or private workspaces. Existing runtime and gate code may use these paths; preserve their expected formats when changing tooling.

Use [AGENTS.md](../AGENTS.md), [GUARDRAILS.md](../GUARDRAILS.md), [AGENT_FILE_EDITING_RULES.md](AGENT_FILE_EDITING_RULES.md), and module-specific policies. Validate behavior through focused tests and applicable runtime checks.

## Release boundary

Public releases contain product source, required assets, installation files, useful documentation, and tests with fictional fixtures. Exclude personal information, credentials, populated agent boards, private task plans, conversation transcripts, generated QA reports, and local screenshots.

Run the public-content check against the source tree and built distributions before publishing. Keep all required notices and third-party licenses.

## Security and deployment

Local access is the default. A cloud model or connector receives data sent to it. Remote server use needs deliberate authentication and configuration.

Read [SECURITY.md](../SECURITY.md), [THREAT_MODEL_WEB_API.md](THREAT_MODEL_WEB_API.md), and [GATEWAY_SECURITY_RUNBOOK.md](ops/GATEWAY_SECURITY_RUNBOOK.md).

## Private file markers

[`docs/trash_marker.md`](trash_marker.md) defines the file-marker contract. The shared parser is [`scripts/forge/publish/private_markers.py`](../scripts/forge/publish/private_markers.py).

`scripts/forge/publish/preflight.py` rejects tracked private-marker files. `scripts/forge/publish/snapshot.py` removes marker files before publication. Accepted marker lines include `THOMAS_PRIVATE`, `# THOMAS_PRIVATE`, `// THOMAS_PRIVATE`, `/* THOMAS_PRIVATE */`, and `<!-- THOMAS_PRIVATE -->`.
