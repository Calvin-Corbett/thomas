### Fixed

- **A start that fails now gets a real Boot Doctor report.** The recovery tool opened
  its probe log in a folder a fresh install does not have yet, so the report came out
  as a "(Fallback)" traceback with no findings, and the source-patching repairs behind
  it aimed at code that is no longer there. It now creates the folder, drops those
  repairs, and after a failed startup probe adds the likely cause and the last lines of
  the probe log to the report's findings: a damaged database, a `thomas.toml` that will
  not parse, a busy port, a port Windows has blocked, or a missing package.
- **Boot Doctor looks at your config and data, not only the port.** A damaged
  database, a `thomas.toml` that will not parse or open, and a data folder Thomas
  cannot write to were never looked at, and the status only said the runtime was not
  detected. Each is now a `[fail]` finding that names the file, and the recovery notice
  carries it. The checks do not change what is stored in your databases, and a database
  that another program holds open is reported as busy, never as damaged. Any program
  listening on the port also used to count as Thomas. Boot Doctor now asks
  `/api/health`, names the program that holds the port when it is not Thomas, and
  reports that taken port as a failure in the status and the notice instead of a
  healthy start. It does not start a second Thomas at a port another program holds,
  since that server could not bind it, and `python -m thomas.bootdoctor rescue` ends
  with that report instead of handing the failure to a model for repair attempts. On
  Windows a Thomas that is still starting, or too busy to answer in time, is still
  recognised as Thomas, including when Windows prints `netstat`'s status column in
  another language. If `netstat` or PowerShell does not answer within 10 seconds, the
  holder counts as unknown, is not taken for Thomas, and nothing is stopped.
- **The report's findings now include file paths and the last lines of the startup
  log.** In the summary Boot Doctor asks your model for, the path of your home folder
  is written as `~`.
- **A `thomas.toml` that will not parse is named, with its line.** `thomas serve` ended
  in a Python traceback that never said which file, and `thomas doctor` died on the same
  line, so the command every recovery message recommends could not report it. The
  `thomas` commands now stop with one line naming the file and line, and `thomas doctor`
  runs on the built-in defaults, lists the file first and exits 1. `python -m thomas.server`,
  which the launcher starts, still prints Python's own traceback; after a failed start the
  launcher's Boot Doctor report names the file and line.
- **`repair.cmd` checks what a failed start leaves behind, and asks before acting.**
  It reinstalled dependencies and never looked at your config or databases. After setup
  has repaired the dependencies it now runs the new `python -m thomas.bootdoctor check`,
  and offers to move a damaged database aside (renamed, never deleted;
  `-QuarantineCorrupt` answers yes). A console run asks before installing tools with
  winget and before moving anything; with no console to ask at, the answer is no and the
  repair carries on. A script that runs repair with its window hidden has to pass
  `-NoPrompt`, since nobody can answer at a hidden prompt. If Thomas is running on port
  8899, repair says so and asks you to close it instead of moving files from under it;
  on another port Windows itself refuses to rename a database Thomas has open. The
  in-app Auto Repair button still installs tools without asking, since pressing it was
  the ask, and the `-NoPrompt` switch it passes now does something. It also runs the new
  check and lists what it finds, moves nothing, and ends with issues when a database is
  damaged.
- **The rescue prompt is readable, and its helper commands stay out of sight.** The
  prompt Boot Doctor builds was one line of literal backtick-n, and told the model to
  edit `*_part*.py` files that do not exist. On Windows the startup probe and the helper
  commands it runs no longer open a console window. With the new `--no-interactive`
  flag, `python -m thomas.bootdoctor rescue` ends instead of waiting at a prompt, for a
  run whose window nobody can see; without it the rescue stays open for you as before.
