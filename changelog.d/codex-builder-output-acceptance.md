### Fixed

- Isolated Build helpers now verify their assigned output file without requiring files owned by sibling helpers. Existing semantic, data, command, and finish verification checks remain active; the lead still verifies the combined project.
