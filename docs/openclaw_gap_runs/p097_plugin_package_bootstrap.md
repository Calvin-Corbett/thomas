# P097 - Plugin package bootstrap

This gap run adds a Thomas-native library + CLI path to **bootstrap a plugin
package skeleton** (a Python package directory with a minimal `Plugin` class).

## Library entrypoint

- `thomas.plugins.p097_plugin_package_bootstrap.bootstrap_plugin_package`

### Input contract

`PluginBootstrapRequest` (dataclass):

- `plugin_name`: Python package identifier (`^[a-zA-Z_][a-zA-Z0-9_]*$`)
- `destination_dir`: directory in which to create the package folder
- `description`: optional description (used in generated files)
- `author`: optional author string (used in generated metadata)
- `overwrite`: overwrite existing files if the package exists

### Output contract

`PluginBootstrapResult` (dataclass):

- `plugin_name`
- `package_dir`
- `files_created`
- `warnings`

## CLI

The command is exposed through the existing `plugins` CLI group via a register hook:

- `thomas/cli/commands/plugins/p097_plugin_package_bootstrap.py`

Example:

```bash
thomas plugins bootstrap my_plugin --dest ./plugins
thomas plugins bootstrap my_plugin --dest ./plugins --json
```

## Errors

All failures raise `PluginBootstrapError` (or subclasses) with:

- `code`: stable machine-readable error code
- `message`: human-readable summary
- `details`: structured context for automation
