### Fixed

- **The tools plugin stays inside its fence again.** `check.run` wrote its wait to the step log by importing a module the tools plugin may not import, so the plugin-fence test failed on dev. The wait is now recorded through the load module, with the same row.
