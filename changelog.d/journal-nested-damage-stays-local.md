### Fixed

- Deeply nested JSON in a run journal is reported as journal damage and quarantined on opening instead of letting a recursion error escape. An unreadable deeply nested summary is ignored, so retention can continue processing other runs. Three regressions fail without these handlers and pass with them.
