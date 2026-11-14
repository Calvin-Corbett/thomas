### Fixed
- `thomas plugins install-from-local-path <folder>` now invokes the folder installer instead of a pack proxy; installation uses the CLI data directory's plugin root, which the running supervisor also watches.
- The Marketplace Plugged in empty state gives the CLI command, its `python -m thomas` fallback, and the sync step. The Windows `thomas.cmd` launcher routes commands with arguments to the CLI while keeping a bare `thomas` invocation for the desktop.
