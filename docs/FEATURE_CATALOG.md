# Feature guide

Thomas provides three primary workspace areas:

| Area | Purpose | Implementation |
|---|---|---|
| Chat | Conversation, files, tools, and memory | `thomas/server/routes/`, `thomas/agent/`, `thomas/memory/` |
| Build | Project work, execution, previews, and verification | `thomas/forge/anvil/` |
| Work | Jobs, workflows, schedules, and run history | `thomas/work/`, `thomas/marketplace/autonomy/` |
| Browser | Workspace navigation and browser tools | `thomas/browser/`, `thomas/server/web/` |
| Desktop | Optional Electron application | `desktop/` |
| Extensions | Additional integrations and tools | `extensions/`, `thomas/plugins/` |

Capabilities depend on the selected model, configuration, optional dependencies, and permissions. The presence of domain modules does not certify every integration as production-ready.

See [README](../README.md) for setup and [technical reference](THOMAS_BIBLE.md) for component responsibilities.
