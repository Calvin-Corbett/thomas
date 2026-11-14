### Fixed

- The native background worker now carries each tool call ID into its start and output events and hashes the actual result arguments into an action ID. Raw arguments are not added to those events. For file reads and writes inside the workspace, absolute and relative paths to the same target produce the same receipt identity, so completion review can distinguish a later retry of the same action from an unrelated success.
