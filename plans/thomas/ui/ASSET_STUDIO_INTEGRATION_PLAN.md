# Asset Studio External Integration Plan

Last updated: 2026-02-22
Status: active proposal
Scope: Thomas web `Asset Studio` should orchestrate existing free tools instead of rebuilding full DCC/NLE/engine software from scratch.

## Why This Plan Exists

The user goal is clear:

- Thomas stays free.
- Thomas reuses existing tools and software.
- Asset Studio does as much work as possible from inside Thomas.
- External tool state and outputs are visible in Thomas without constant app switching.

Current Asset Studio already has strong scaffolding (library, presets, queue UI, OTIO export copy actions), but most execution paths are still local simulation/copy-to-clipboard, not live tool control.

## Critical Gap Analysis (Vs Existing Asset Studios)

This is the blunt comparison baseline we need to beat.

| Competitor/Product | What it does better today | Thomas gap today | What Thomas must add |
| --- | --- | --- | --- |
| Unreal Editor toolchain | Real project automation via command line, Python API, remote control websocket | No live Unreal connector, no project sync/status | Unreal connector, live status, task execution, import/export ops |
| Blender pipeline | Mature Asset Browser, scripted rendering via CLI/Python, deep metadata | No direct Blender asset or render orchestration | Blender connector with catalog sync and render jobs |
| Kdenlive | Real render queue/scripts and timeline-to-export flow | Queue is mostly simulated | Real job runner + script generation + output tracking |
| Audacity scripting | External automation via named pipe commands | No live audio workstation bridge | Audacity connector with command templates + job logs |
| ComfyUI | Real node workflow execution, queue, extensibility | Only static "generation tool" command copies | Live Comfy workflow run/monitor/result import |

## Strategic Principle

Do not rebuild full editors. Build an orchestration layer:

- Thomas owns tasking, queueing, history, and cross-tool automation.
- External apps own deep editing UX.
- Asset Studio owns a unified control plane + visibility plane.

## Product Outcome Targets

1. A user can run common asset tasks from Asset Studio with one click.
2. Thomas shows live progress/logs/results while tools run.
3. Jobs survive tab switches, reconnects, and app restarts.
4. Connectors are modular, so new tools can be added without touching core UI logic.
5. Licensing and security are explicit for every connector.

## Architecture Plan

## A. Connector Runtime (Backend)

Create a dedicated backend subsystem:

- `thomas/asset_studio/connector_contract.py`
- `thomas/asset_studio/connector_registry.py`
- `thomas/asset_studio/job_runner.py`
- `thomas/asset_studio/events.py`
- `thomas/asset_studio/connectors/*.py`

Connector contract:

- `id`, `label`, `license`, `requires_local_install`, `platform_support`
- `detect()` -> installed/version/capabilities
- `list_projects()` / `list_assets()` (optional)
- `run_action(action_id, payload)` -> job id
- `stream_events(job_id)` -> progress/log/state updates
- `cancel(job_id)`

Job runner responsibilities:

- persistent queue (sqlite-backed),
- retries and cancellation,
- process supervision (stdout/stderr capture),
- structured event stream for frontend.

## B. Asset Studio API Surface

Add new aiohttp routes, for example:

- `GET /api/asset-studio/v1/connectors`
- `POST /api/asset-studio/v1/connectors/{id}/detect`
- `POST /api/asset-studio/v1/jobs`
- `GET /api/asset-studio/v1/jobs`
- `GET /api/asset-studio/v1/jobs/{job_id}/events`
- `POST /api/asset-studio/v1/jobs/{job_id}/cancel`
- `GET /api/asset-studio/v1/assets`
- `POST /api/asset-studio/v1/assets/sync`

Streaming model:

- SSE endpoint for low-friction browser support.
- Optional websocket fallback for higher throughput later.

## C. Frontend Refactor Path

Current Studio logic is embedded in `thomas/server/web/js/app.js`.
Refactor incrementally:

- extract studio logic into `thomas/server/web/js/asset-studio/` modules,
- keep existing UI shell but replace simulated handlers with API-backed actions,
- preserve fallback mode when connectors are unavailable.

Primary new panels:

- Connected Tools
- Live Jobs
- Asset Graph (source -> transform -> output)
- Action Recipes (saved automation chains)

## D. Persistent State Model

Persist:

- connected tool snapshots,
- job history and artifacts,
- per-project paths and mappings,
- recipe templates.

Do not persist:

- secret tokens in plain text,
- transient raw process buffers beyond capped log windows.

## Integration Matrix (Free/OSS First)

Priority order balances value, integration effort, and legal clarity.

| Priority | Connector | Mode | First shipped actions |
| --- | --- | --- | --- |
| P0 | FFmpeg | CLI | transcode, loudness, concat, waveform/probe metadata |
| P0 | Blender | CLI + Python | batch render, gltf/fbx/usd conversion, asset thumbnail generation |
| P1 | Unreal | command line + Python + remote control websocket | open project tasks, run scripted import, sequence/export helpers |
| P1 | ComfyUI | local API | queue workflow, poll progress, ingest images/metadata |
| P1 | Kdenlive/MLT | project file + scripts | parse `.kdenlive`, generate batch render scripts, track outputs |
| P2 | Audacity | named pipe scripting | normalize/cleanup chains, export variants |
| P2 | Krita | Python plugin bridge | batch exports, sprite sheets, template-based output |
| P2 | Inkscape | CLI actions | svg optimization/export variants/png outputs |

## Unreal-Specific Plan

Why Unreal is special:

- It can be automated by command line and Python scripting.
- Remote Control WebSocket allows live remote operations (beta feature; keep it opt-in).

Implementation slices:

1. Detect Unreal install + project roots.
2. Run safe scripted tasks via command line job runner.
3. Add optional Remote Control bridge for live property/sequence operations.
4. Surface project status in Asset Studio.
5. Offer "open in editor" fallback for unsupported operations.

Guardrails:

- Explicit project allow-list.
- User-confirmed script execution profile.
- No unauthenticated remote endpoints exposed beyond localhost by default.

## Phase Plan

## Phase 0 - Foundation (1 week)

Deliver:

- connector contract + registry,
- persistent job runner,
- base Asset Studio API,
- frontend "Connected Tools" + "Live Jobs" skeleton.

Acceptance:

- at least one mock connector runs end-to-end with persistent logs and cancellation.

## Phase 1 - Realize Existing Presets (1-2 weeks)

Deliver:

- replace simulated queue actions with real FFmpeg-backed jobs,
- job artifacts + metadata in asset library,
- resilient job replay after reload.

Acceptance:

- render queue executes real commands,
- failed jobs show actionable error logs,
- tests cover queue/run/cancel/retry.

## Phase 2 - High-Value Connectors (2-3 weeks)

Deliver:

- Blender connector productionized,
- Unreal connector v1 (CLI + Python task runner),
- ComfyUI connector v1.

Acceptance:

- each connector exposes detect/list/run/status,
- at least 3 production actions per connector,
- connectors can run in parallel jobs safely.

## Phase 3 - Deep Pipeline + Interchange (2 weeks)

Deliver:

- OTIO-native timeline import/export workflows,
- Kdenlive project/script integration,
- Unreal OTIO bridge workflow support where available.

Acceptance:

- timeline round trip tests (Thomas -> OTIO -> tool -> Thomas),
- no data-loss for clip timing/name fields in supported paths.

## Phase 4 - Audio/Design Expansion (2 weeks)

Deliver:

- Audacity scripting connector,
- Krita + Inkscape connectors,
- recipe builder for repeatable chains (ex: "voice cleanup + thumbnail pack + publish set").

Acceptance:

- one-click multi-step recipe execution,
- per-step status timeline visible in UI.

## Phase 5 - Hardening and Scale (ongoing)

Deliver:

- connector health checks and telemetry,
- per-connector sandbox policy,
- safer defaults for remote endpoints,
- docs and recovery flows.

Acceptance:

- deterministic restart recovery,
- regression suite for connector APIs and Studio UX,
- stress test with sustained background jobs.

## UX Requirements (Non-Negotiable)

1. Users stay in Asset Studio for 80 percent of routine operations.
2. Every job has a visible state: queued, running, blocked, failed, done.
3. Every failure has a plain-English explanation + suggested fix.
4. Every connector card shows install status, version, license, and quick setup.
5. "Open in app" remains available for advanced manual edits.

## Security + Legal Policy

- Local-first execution by default.
- Connector permissions are explicit and revocable.
- External command templates are allow-listed.
- Model/plugin licenses are tracked per asset recipe.
- Remote-control connectors default to localhost only.

## Metrics and Benchmarking

Use measurable targets instead of design opinions:

- Time to first export from fresh install.
- Queue success rate across 100 batch jobs.
- Mean time to diagnose failed job.
- Percent of tasks completed without switching apps.
- Recovery success after browser refresh/restart.

Comparison scorecard should track Thomas vs:

- Blender native pipeline,
- Unreal scripted pipeline,
- Kdenlive render queue,
- ComfyUI workflow queue.

## Immediate Build Order (Next 10 Engineering Tasks)

1. Scaffold `thomas/asset_studio/` runtime package and connector contract.
2. Add `asset_studio_aiohttp.py` route module and register routes.
3. Build sqlite-backed job queue with process runner + event bus.
4. Wire existing Studio "queue/export/copy" actions to backend API.
5. Ship FFmpeg connector with probe + transcode + concat actions.
6. Add frontend live jobs panel with log stream and cancellation.
7. Ship Blender connector detect/list/run basics.
8. Ship Unreal connector detect + scripted task runner.
9. Add ComfyUI queue/poll/result-import connector.
10. Add integration tests for connectors + Studio API smoke tests.

## Risks and Mitigations

- Risk: connector sprawl and brittle scripts.
  - Mitigation: strict connector contract + conformance tests.
- Risk: security issues with automation endpoints.
  - Mitigation: localhost default, explicit trust prompts, allow-listed actions.
- Risk: UI regressions from monolithic app.js edits.
  - Mitigation: modular extraction with snapshot tests and fallback mode.
- Risk: licensing confusion for third-party models/plugins.
  - Mitigation: enforce per-asset license metadata before export/publish.

## Sources (Primary Docs)

- Unreal Engine command line arguments: https://dev.epicgames.com/documentation/en-us/unreal-engine/command-line-arguments-in-unreal-engine
- Unreal Python API docs: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/
- Unreal Remote Control WebSocket reference: https://dev.epicgames.com/documentation/en-us/unreal-engine/remote-control-api-websocket-reference-for-unreal-engine
- Unreal licensing: https://www.unrealengine.com/en-US/license
- Blender command line rendering: https://docs.blender.org/manual/en/latest/advanced/command_line/render.html
- Blender command line arguments: https://docs.blender.org/manual/en/3.6/advanced/command_line/arguments.html
- Blender Python API: https://docs.blender.org/api/5.0/index.html
- Blender Asset Browser: https://docs.blender.org/manual/en/3.1/editors/asset_browser.html
- Blender GPL notes: https://docs.blender.org/manual/en/latest/getting_started/about/license.html
- FFmpeg legal and license: https://ffmpeg.org/legal.html
- FFmpeg documentation hub: https://www.ffmpeg.org/documentation.html
- OpenAssetIO intro: https://docs.openassetio.org/OpenAssetIO/
- OpenTimelineIO core project: https://github.com/AcademySoftwareFoundation/OpenTimelineIO
- OpenTimelineIO Unreal plugin: https://github.com/OpenTimelineIO/OpenTimelineIO-Unreal-Plugin
- Kdenlive manual (rendering): https://docs.kdenlive.org/en/exporting/render.html
- Kdenlive project file details: https://docs.kdenlive.org/en/project_and_asset_management/file_management/project_files.html
- Krita Python scripting docs: https://docs.krita.org/en/user_manual/python_scripting.html
- Krita license: https://krita.org/en/about/license/
- Audacity scripting (named pipe): https://manual.audacityteam.org/man/scripting.html
- Audacity modules preference (mod-script-pipe): https://manual.audacityteam.org/man/modules_preferences.html
- Inkscape licensing: https://inkscape.org/en/about/license/
- Inkscape command line migration notes: https://wiki.inkscape.org/wiki/Using_the_Command_Line
- Comfy custom nodes/workflows docs: https://docs.comfy.org/custom-nodes/overview
