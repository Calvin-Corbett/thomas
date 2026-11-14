### Fixed

- Your private secret canary tooling (thomas/security/secret_canaries.py and its tests) is now on the publish strip list, so the next public release leaves both files out instead of shipping them again after you remove them from the public repository. A test builds a publish snapshot and fails if either file reaches it.
