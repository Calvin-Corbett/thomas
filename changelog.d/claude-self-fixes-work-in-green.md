### Security

- **A self-fix no longer edits the running Thomas.** You asked for this long ago:
  *"I thought I made a blue-green system just for this, so he would edit the other
  version that's not running"*. You did, and the Doppelganger worked that way until
  its last promotion on 2026-06-22. Six days later chat self-development was merged,
  and it edited the live checkout directly without ever calling it. Now every
  self-development task runs in **green**: a private clone of what Thomas has
  committed, kept outside the running copy in Thomas's data folder
  (`%LOCALAPPDATA%\Thomas\green`).
  - Green first went in `C:\ProgramData`. The first live self-fix in green could
    not write a single file there, because Thomas's file-access rules refuse
    ProgramData at every level as a system folder. The tests had used a temporary
    folder and never saw it. Green now lives in the data folder, and a test asks
    the file-access rules about the real location.
  - A retry no longer throws away a correct fix. Each attempt used to measure
    "what changed since this attempt began". Green keeps the earlier attempt's
    work, so a second attempt that found the job already done counted as
    changing nothing, failed, and the finished change was discarded with green.
    In green, "changed" now means changed from the commit green started at.
  - In green, green is the whole project. At "This project" access, the worker's
    file tools used to count the running copy as the project. A worker in green
    could therefore still write an unprotected file there, such as a test or a
    changelog, by absolute path. A run in green is now held to its own folder;
    starting a self-fix still needs "This project".
  - When the run finishes, green's change is written to the commit-master's inbox
    as one submission. Green is then deleted. A run that fails submits nothing, and
    any blocker report it wrote is copied to the running copy's `runtime/` first.
  - If green cannot be made, the task fails and tells you why. Before this change,
    a failure to start the worker handed the task to the Task Manager, which works
    in the live checkout. A self-fix now never falls back to the running copy.
  - The reply used to say "Changed live Thomas files". It now says the change was
    made in a private copy and reaches the running Thomas once you approve it.
    Until the commit-master's approval step lands, a submitted self-fix waits in
    the inbox.
  - Green's git folder is separate from its files, and the cage's account can only
    read it. The one-line pointer to that folder, which anything in green could
    rewrite, is never used by the server: every git call names the real folder
    itself. A test proves this by replacing the pointer and checking that the diff
    is still right.
  - The cage's own `git` needs one elevated setting to read green's history. It
    rides the same approval tap as the pin move.
