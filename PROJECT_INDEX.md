# Thomas Project Index

This file is the contributor-facing map of the public Thomas repo. Use it when you need a quick view of the main entry points, major code surfaces, and high-value docs.

## Primary Docs

- `README.md` - install and daily use
- `DOCUMENTATION_INDEX.md` - stable docs hub
- `docs/CHAT_EXECUTION_MODEL.md` - chat and execution architecture
- `AGENTS.md` - repo guardrails for contributor and agent-driven work
- `SECURITY.md` - security policy
- `CHANGELOG.md` - release history
- `KNOWN_ISSUES.md` - current limitations

## Product Surfaces

| Surface | Path | Purpose |
|---|---|---|
| Core runtime | `thomas/` | Server, tools, memory, chat, and automation |
| Companion and client apps | `apps/` | Site and client surfaces |
| Installer assets | `installer/` | Packaging and installer inputs |
| Scripts and automation | `scripts/` | Setup, checks, release helpers, and maintenance tooling |
| Tests | `tests/` | Regression and release checks |

## Entry Points

| Command | Purpose |
|---|---|
| `run-ui.cmd` | Start the UI flow on Windows |
| `setup.cmd` | Manual setup |
| `repair.cmd` | Repair a broken local setup |
| `bootdoctor.cmd` | Startup diagnostics |
| `python -m thomas.server` | Start the server directly |
| `thomas serve` | CLI entry point to the server runtime |

## Where to Start

- User install or run issues: `README.md` plus `setup.cmd` and `repair.cmd`
- Server behavior: `thomas/server/README.md`
- Chat flow: `docs/CHAT_EXECUTION_MODEL.md`
- UI work: `thomas/server/web/README.md`
- Tools: `thomas/tools/README.md`
- Memory: `thomas/memory/README.md`
- Packaging and release work: `docs/WINDOWS_INSTALLER_GUIDE.md` and `scripts/README.md`

## Notes

- Prefer live code and the docs above over scratch notes or archived planning material.
- Some domain directories under `thomas/` are scaffolds and are not part of the main user path.
