### Fixed

- Your window control now rejects `--minutes` outside 1 through 525600 before writing a request, instead of promising a sign-in for a request the window loop would discard. Valid duration boundaries, `--until-off`, and the existing defaults are unchanged.
