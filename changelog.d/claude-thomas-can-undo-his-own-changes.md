### Added

- **Anything Thomas changes about himself can be taken back with one click.**
  You want him fixing his own blockers as they happen, without stopping to ask
  first: "you already made the change fixed it and then you have to click on it
  to put it into stone". So every change Thomas makes to his own code is
  recorded with the exact bytes that were there before, and when the run ends
  his chat shows a card: each file, why he changed it, and **Accept**, **Undo**
  or **Leave it for now**.
  - **Undo restores exactly what was there.** A file he created is removed
    again. It does not depend on a patch still applying, so it works even after
    the change has been built on.
  - **Nothing is permanent until you accept.** Changes you leave stay listed and
    undoable, and they survive a restart, including one his own change caused.
  - **A failed run shows the card too**, because a run that failed may still
    have changed something.
  - Taking a change back never asks for a password: the change already passed
    the protected-file approval, and undoing is the safe direction.
