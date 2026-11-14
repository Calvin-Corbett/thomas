### Fixed

- **The shard plugin regression reads the child test's output from its sandbox data directory.** `test_the_copys_own_tests_import_the_copys_plugin_and_the_servers_is_the_one_registered` derives `THOMAS_DATA_DIR` through `sandbox_env` instead of assuming it is the runner's report directory. It still checks that the server's pinned plugin is registered while the child imports the copy's plugin.
