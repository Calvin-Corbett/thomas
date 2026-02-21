# Thomas V1 Launch Plan

Date: 2026-02-16

## Intent
Ship a V1 that is functional-first (UI polish later), with a launch-quality demo video fully produced by Thomas and a set of core capabilities proven via tests and scripted demos.

## Non-Goals (For V1)
- UI overhaul and visual polish (explicitly deferred until functionality is stable).
- Broad feature expansion beyond the V1 launch requirements below.

## Launch-Quality Demo Video (Must-Have)
Thomas must be able to produce a complete product/intro video end-to-end.

Minimum bar:
- Script generation
- Storyboard/shot list
- Asset generation (visuals + audio)
- Voiceover (TTS or voice model)
- Editing/assembly into a final export
- Final delivery in common formats (mp4 + web-friendly encode)

In-video demonstrations required:
- Create a simple video game workflow
- Demonstrate Unreal Engine integration (via plugin)
- Voice-to-voice model demo
- Spawn and coordinate agents (swarm + single-agent tasks)
- Memory continuity across chats (show persistence and recall)

## V1 Functional Requirements
Core system:
- Reliable agent spawning and coordination primitives (single + swarm)
- Memory works across chats/channels, with clear retrieval behavior
- Evolution loop works end-to-end (self-improvement pipeline)
- Voice-to-voice model available and stable
- Tool execution pipeline is robust with clear failure modes

Developer/operator:
- Versioning + changelog discipline for behavioral changes
- Tests executed for any risky change
- Clear rollback path for breaking changes

## Parity And Gaps vs OpenClaw (From docs/OPENCLAW_PARITY.md)
Status:
- Routing + failover reliability: active
- Memory architecture (episodic + profile): active
- Channel consistency (Telegram/web/CLI): active
- Token efficiency and cost control: active

Remaining to exceed OpenClaw:
- Curator pipeline approval workflow for promoted facts
- Source quality model (trust score + recency decay)
- Memory governance workflows and severity routing
- Adaptive context compaction policies and dashboards

## V1 Validation Plan (Tests + Demos)
Automated tests:
- Smoke: boot, route, and tool execution
- Memory: persistence + retrieval across sessions
- Agents: spawn, delegation, result collation
- Voice: V2V roundtrip with latency bounds
- Evolution loop: pipeline executes with version bump + changelog

Scripted demos:
- End-to-end launch video build
- Unreal Engine integration walkthrough
- Swarm coordination scenario
- Memory persistence scenario

## V1 Open Questions
- Confirm whether "OpenClock" refers to "OpenClaw"
- Define the exact Unreal Engine plugin and required capabilities
- Define target video length + style guide for the launch video
- Confirm acceptable latency thresholds for voice-to-voice

## Sequence (Functional-First)
1. Lock V1 requirements + parity gap list
2. Prove core functionality with tests + scripts
3. Implement launch video pipeline
4. Stabilize memory + agent coordination
5. UI overhaul and polish
