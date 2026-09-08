# Thomas

Thomas is a local AI workspace for conversation, software development, and recurring work. Connect a supported model provider or a local model, then use Chat, Build, and Work from one interface.

**Status:** beta, version 0.19.37. Features and reliability depend on the selected model, installed dependencies, and permissions.

## Get started

### Windows

1. Download the [latest source release](https://github.com/Calvin-Corbett/thomas/releases/latest) or clone this repository.
2. Run `run-ui.cmd` and wait for dependency setup to finish.
3. Open `http://127.0.0.1:8899` and complete Easy Setup.
4. Configure a model connection before starting a task.

Run `desktop.cmd` for the optional Electron desktop shell. If desktop startup is blocked by your system's application policy, use the browser interface. See [desktop setup](docs/DESKTOP.md).

### Python installation

Python 3.10 or later is required. From a source checkout:

```sh
python -m pip install -e ".[server,repl]"
python -m thomas --help
python -m thomas serve --port 8899
```

Installation and model configuration: [ONBOARDING.md](ONBOARDING.md). Troubleshooting: [support guide](docs/support/TROUBLESHOOTING.md).

## Workspace

- **Chat:** ask questions, use tools, work with files, and manage conversation memory.
- **Build:** delegate development work in a project folder, inspect changes, and review execution and verification results.
- **Work:** define a job, configure its workflows, and follow scheduled or manual runs.
- **Browser:** navigate pages in the workspace and use supported browser tools.
- **Models:** configure supported cloud providers or compatible local model endpoints.
- **Extensions:** install integrations and tools through the plugin system.

Some capabilities require optional packages, provider credentials, or external applications. A module's presence in the source tree does not guarantee that its integration is configured or supported on every platform.

## Data and permissions

Conversation history, project files, and configuration are stored locally. When using a cloud model or connector, relevant requests and data are sent to that service. Keep credentials out of source control and review tool permissions before granting access to files or external accounts.

The server defaults to local access. Remote deployment requires explicit authentication and configuration; read [SECURITY.md](SECURITY.md) and the [gateway runbook](docs/ops/GATEWAY_SECURITY_RUNBOOK.md).

## Current limitations

- Thomas is beta software. Review generated code and results before relying on them.
- Model tool support and task completion vary by provider and model.
- The optional desktop shell may be blocked by Windows application-control settings; the local browser interface remains available.
- Some domain integrations are experimental. Check the relevant module documentation and prerequisites.

## Documentation

- [Setup and onboarding](ONBOARDING.md)
- [Architecture](ARCHITECTURE.md)
- [Technical reference](docs/THOMAS_BIBLE.md)
- [Documentation index](DOCUMENTATION_INDEX.md)
- [Release notes](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING_AI.md)

## Development

```sh
python -m pip install -e ".[server,repl,test]"
python -m pytest -q
ruff check .
```

Read [AGENTS.md](AGENTS.md), [GUARDRAILS.md](GUARDRAILS.md), and any module-specific guidance before changing code. Keep personal data, credentials, conversation histories, local planning records, and generated test evidence out of contributions. Use fictional data in tests.

## License

[MIT](LICENSE).
