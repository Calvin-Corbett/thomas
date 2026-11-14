### Security

- **The cage's posture pin could be deleted, and now cannot.** It was pinned in
  `C:\ProgramData\ThomasCage` with Administrators-only permissions, and its
  first test proved it could not be *written* — so it was described as a wall.
  It was not one. Your account holds FullControl on that folder so it can run the
  cage channels, and FullControl on a folder includes delete-child, which removes
  any file inside regardless of the file's own permissions. An unelevated process
  deleted an Administrators-only file there with a plain `File.Delete`; a deleted
  pin hands the posture back to the environment, where `THOMAS_CAGE_SHELL=off`
  turns the cage off. (The first check even said it was safe: PowerShell's
  `Remove-Item -Force` clears attributes before deleting, fails there, and
  reports "access denied".)

  Pins now live in `C:\ProgramData\ThomasPins`, created and owned by an elevated
  script. `C:\ProgramData` lets ordinary users create folders, never remove one
  someone else owns, so your unelevated processes can neither write, empty nor
  rename it. The script takes ownership back if anyone created the folder first,
  then proves the result rather than trusting the commands that set it. The old
  location stays readable only as a floor — strictest wins — and the pin script
  removes it so a stale value there cannot defeat a later change.

- **Thomas's approval cards are pinned too.** Every word a Windows PIN prompt may
  carry now comes from one catalogue, `scripts/cage/card_catalogue.py`. Thomas
  names a card and its details; he never writes the words. Its SHA-256 is pinned
  in the same folder, and every PIN flow refuses while the catalogue on disk does
  not match it — so changing a card's wording takes a UAC prompt, not a file
  write. You asked for exactly this: *"So if you try to edit it or do anything,
  then it will it won't work."* The hash is computed by the elevated script from
  the bytes, never by asking the catalogue about itself, and PowerShell and
  Python are tested to agree on it byte for byte.
  - A detail cannot forge a second paragraph on the dialog: it is flattened to
    one line and capped.
  - A six-character pairing code, drawn from characters that cannot be misread
    for each other, follows the exact content. It is shown on the chat card and
    the dialog so you can match them at a glance. It is not a secret and not the
    security boundary — the dialog's wording is.
  - The catalogue is loaded from the very file whose hash was checked, not by
    import name, so a same-named module elsewhere on the path cannot stand in for
    it.
- **A protected write is approved on what it actually changes.** The card used to
  say "Let Thomas change `path`", and your PIN approved writing *any* bytes there.
  Now the chat card shows the real diff, the change size and the pairing code,
  with Thomas's own explanation labelled "Thomas says"; the Windows dialog carries
  the catalogue's wording and the code, and never Thomas's words; and the write
  goes ahead only if the bytes hash to exactly what the card showed.
  - **Two existing tests asserted the hole.** One checked that the model's reason
    — the literal string *"the product owner-approved emergency fix"* — appeared
    on your Windows PIN dialog; the other that the caller's description was
    echoed there verbatim. A sentence claiming you already approved something,
    on the one screen you are meant to trust, is the attack, not the feature.
    Both now assert the opposite.
- **Files that guard Thomas are approved one change at a time (policy C).** A
  gate, the cage, an approval module, or a change that adds network reach can no
  longer ride inside an "approve this task" or "approve everything" you gave for
  something else. Its card offers only "this change" or "no", and approving it is
  never remembered.
- **Dials use the same pinned wording**, and refuse without asking if the catalogue
  is not the pinned one.
- **The protection test suites could quietly stop protecting.** A test anchored
  runtime protection to its own temporary folder and never reset it, so every
  later test in the run checked protection against that stale folder — and the
  runtime-protection *key*, which must never be writable, became writable through
  an ordinary file write. Those tests passed alone and failed together, which read
  as flakiness. Protection is now un-anchored around every test; ten failures that
  had nothing to do with the code under test went away.
