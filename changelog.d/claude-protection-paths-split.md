### Changed

- **The path-protection rules moved into their own modules,**
  `thomas/tools/runtime_protection_paths.py` and `thomas/tools/runtime_protection_auth.py`,
  unchanged and re-exported from `thomas/tools/filesystem.py`, which keeps that file
  well under the 800-line limit as the protected set grows.
