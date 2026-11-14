### Fixed

- Every self-fix approval card now says what Cancel does on it, and the change card names up to 600 characters of files, each with its size and never cut mid-name; a 200-character cap used to hide files without saying so. Code is named before test data.
- A Windows sign-in that is not accepted (a mistyped PIN, or a prompt that cannot show) no longer declines your self-fix: the same card comes back up to three times, then waits two minutes and asks again. Only Cancel declines. A hand-in moved aside to be checked while its card is up is not asked about again.
- Pressing Cancel on a guarded-file card leaves out exactly that file, even when its name has `[` or `]`; it used to keep that file, drop another, and stop every other hand-in.
- While the approval cards do not match their pin, every hand-in now waits instead of being refused, and is asked once the pin matches again.
- The promoter reads each hand-in's patch once, so what it checked is what lands, and it also checks the tree that would land: no symlink, submodule, mode change, unusual path (an 8.3 short name included), `runtime/` file, approval-card edit, or `.gitattributes`/`.gitmodules` change gets through. Cards show each file from its own bytes, whatever a `.gitattributes` in the running copy says.
- The running copy is checked again right after your answer, so work that appeared while the card was up is never overwritten. A commit made while the card was up is not mistaken for that work: the new tree is asked about again.
- A self-fix that landed just before the promoter stopped now gets a "landed" verdict naming its commit, instead of being refused as "already on dev".
- Hand-ins are asked in the order they arrived, not by folder name, including those that arrive while a card is up. A hand-in the promoter cannot read or check gets its own verdict instead of holding up every hand-in behind it.
