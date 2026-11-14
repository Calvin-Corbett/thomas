### Fixed

- **A clean install now leaves a machine that can run `thomas serve`.**
  `install.cmd` and `install.sh` ran a bare `pip install .`, which leaves out the
  `server` extra (aiohttp, fastapi, pydantic and the rest). `thomas serve` then
  stopped with "Server dependencies missing" straight after an install that ended by
  advertising the web UI. Both now install `.[server,repl]`, the set
  `scripts/setup.ps1` already used. `install.cmd` also installs into `.venv` instead
  of the global Python (`THOMAS_NO_VENV=1` skips that), checks that Python is between
  3.10 and 3.13 (Thomas pins numpy 2.2.6, which has no prebuilt package for 3.14, so
  pip used to fail inside a source build), honours `THOMAS_DEV=1` for an editable
  install the way `install.sh` does, leaves an editable install in `.venv` editable
  (a copy install would have replaced the one `run-ui.cmd` makes, and every launch
  after that would have run the old copy), and prints plain ASCII where it printed
  garbage dashes. `install.sh` stops at the same Python range, tries `python3.13`
  down to `python3.10` before plain `python3` (a default `python3` newer than 3.13,
  which Homebrew ships, no longer hides a supported Python installed beside it),
  leaves an editable install in its venv editable too, offers
  to start the UI when it finishes, and its header no longer advertises
  `curl ... | bash`: the script installs the checkout it sits in, and piped it died
  with "BASH_SOURCE[0]: unbound variable". DEPLOYMENT.md and ONBOARDING.md now say to
  activate the environment before `thomas serve`.

- **The Windows installer ships the release bundle, not the machine it was built
  on.** `ThomasSetup.iss` read the working tree, and its Excludes list was separated
  by semicolons where Inno Setup wants commas, so nothing was excluded: an installer
  built on your machine would have carried `.venv`, `runtime/`, `.thomas/`,
  `.env.local` and every untracked file, more than a gigabyte. The build script now
  stages the bundle that `scripts/package_release.py` selects from tracked files,
  hands it to the installer script as `/DStageDir`, and the installer script refuses
  to compile without it. Its Excludes list is comma-separated and anchored at the top
  of the bundle: a bare `runtime\*` would have removed the product's own
  `thomas/server/web/js/runtime/` scripts. The source zip keeps its folders; it used
  to put every file in the zip root. The bundle now carries
  `scripts/startup_recovery_watch.ps1`, which `run-ui.ps1` starts and which the
  allow-list had left out, and a test reads every launcher and fails when one names a
  script the bundle does not ship. The bundle's own `RELEASE_MANIFEST.json` no longer
  records the folder it was built in or the name of every file it left out (it keeps
  counts), and `THIRD_PARTY_NOTICES.md` and `RELEASE_SUMMARY.md` are real lines
  instead of one line joined with a backslash and an `n`. Shell scripts in the
  bundle are staged with Unix line endings: a Windows checkout holds `install.sh`
  with CRLF, so the zip built from it stopped bash at `set -euo pipefail\r`.

- **The installer is versioned and finished properly.** The version comes from
  `pyproject.toml` (the default was `0.0.0-dev` and the guide told maintainers to
  type `0.1.0`). Shortcuts carry the Thomas icon, Add/Remove Programs links to the
  project instead of `http://127.0.0.1:8899`, uninstall removes the `.venv` the first
  launch built, and the script stops with a clear message on an Inno Setup older than
  6.3, which does not understand `x64compatible`. The finish page's "Launch Thomas
  now" box, ticked by default, could not start `launch-thomas.vbs` (Inno needs
  `shellexec` for anything that is not an `.exe`), so it now has that flag, and its
  label says what the first launch does: it downloads dependencies and can install
  Node.js, the Codex CLI and Ollama. Installing
  over an existing copy keeps `thomas.toml`, because first-run setup writes your chosen
  default model into it. The Windows installer guide now lists what a launch changes
  outside the install folder: the `thomas://` handler, and the tray packages. The
  README no longer hard-codes a version that had drifted.

- **DEPLOYMENT.md no longer calls `docker compose up` locked down.** The compose
  file points `THOMAS_CONFIG` at the development `thomas.toml`; only the image's
  `THOMAS_ENV=production` overrides apply, and the guide now says so.

- **The My Stuff import form no longer suggests a real project's folder.** Its
  example path and name were a real project's folder and title, shown to everyone
  who opened the form. They are now neutral examples.
