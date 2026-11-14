### Changed

- **The plugin guards now work across every plugin.** The fence covers every repo package instead of only `thomas.*`, so `scripts/` can be fenced too, and each file is read and parsed once however many plugins ask, so the checks stay quick with 35 manifests.
