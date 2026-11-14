### Security

- **A self-fix reaches the running Thomas only after you approve it, and only in
  the exact form you approved.** Every self-fix now arrives in the commit-master
  inbox from green, and a new promoter is the only thing that puts one into the
  running Thomas. It runs as you, in your session, because it has to show the
  Windows sign-in. For each self-fix it works through these steps, in order:
  - **Refuses before asking** if the patch is unsafe, the approval catalogue
    doesn't match its pin, or anyone outside the pinned set can write Thomas's
    code. An unsafe patch is one that adds a symlink or submodule, changes a file
    mode, renames, touches `runtime/` or git itself, climbs out with `..`, or
    writes through a folder that is really a link.
  - **Rebuilds the change without running any of it.** It applies the patch to a
    temporary git index and compiles changed Python without importing it. Code
    from a self-fix that ran here would run under your account before you had
    approved anything, so tests stay the worker's job, run caged inside green.
  - **Asks you first about each file that guards Thomas.** The cage, the approval
    code and anything that adds network reach each get their own card, and any
    of them can be left out.
  - **Then asks about the whole change.** Every card is worded by the pinned
    catalogue and carries a pairing code tied to the exact files that would land.
    The chat that asked shows the same card and code, and says the card itself
    cannot approve anything.
  - **Moves `dev` only if nobody else committed in the meantime.** If someone
    did, it rebuilds the change on the new `dev` and asks again: an approval
    covers one exact result.
  - **Updates only the changed files** in the running copy. If any of them has
    uncommitted work, it refuses and overwrites nothing.
- **Who may write Thomas's code is pinned, and anyone new is refused.** An
  elevated script records today's set in the pin folder:
  - you, SYSTEM and Administrators;
  - your Codex's sandbox group, plus the five unnamed accounts beside it that are
    that sandbox's writable folders.

  Those Codex entries are your own tool, so they are part of the baseline, not
  removed. Removing them would stop Codex editing this repo, and that is your
  decision to make. A new writer, including the cage's own account gaining
  write access, stops every promotion until you look.
- **Two limits, stated plainly:**
  - A self-fix that edits the gate files themselves is refused. Those changes go
    through your own commit path, where the gate manifest changes in the same
    commit.
  - The server-side "Undo" for a promoted self-fix is a revert commit made the
    usual way. It is not wired to a button yet.
- **The first real self-fix through all of this would have broken Thomas, and
  now cannot.** You asked for a docstring in one module. The worker spent its
  first reads on the repo's required checks. A guard meant to stop endless
  searching then refused to let it read the file it had to edit, so it wrote
  that 107-line module blind: its new 5-line docstring and nothing else.
  - The approval card would have said only "Apply 1 change(s):" and the file
    name. It now shows each file's size, `(+5 -102)`. The card in the chat
    that asked also shows the change itself, so you can read exactly what
    would land before you approve at the Windows prompt. The prompt stays the
    catalogue's own short wording.
  - Before asking, the promoter now refuses any change that removes a name
    another module imports, naming both files. It parses the code; it never
    runs it.
  - The guard no longer blocks reading a file.
- **Fixed: a self-fix touching a file with Windows line endings could never
  apply.** The patch was read as text, which silently drops the carriage return
  of every such line, so the patch no longer matched the file it came from. It
  is now carried as the exact bytes git produced.
