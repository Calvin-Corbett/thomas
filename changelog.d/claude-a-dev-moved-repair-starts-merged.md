### Changed

- **A repair round because dev moved starts with dev already merged in.** When
  the promoter refused a Thomas project's finished change because "the change
  no longer applies to dev", the round that sent it back told the team to run
  `git merge` in its copy. The team cannot: Build's Claude team edits files and
  has no shell. On 2026-09-25 the ratchet project spent its rounds checking that
  its files were intact without ever seeing what dev had changed, was refused
  again, and stopped. Now Thomas merges dev into the project's private copy
  before the round starts. It keeps the team's whole change in the copy's own
  git folder first, applies it to dev's tip the way the promoter does (every
  part that still fits applies), and writes conflict markers, labelled `dev`
  and `your change`, into each file where dev and the team changed the same
  lines. Only files that differ are rewritten; the Build conversation, the
  runtime folder and anything else the copy keeps untracked are never touched,
  and dev may not add a file on top of one of them. The copy's recorded base
  moves to dev, so its next hand-in carries only the team's work. The round's
  message says the copy now stands on dev, lists the files that still hold
  `<<<<<<<` / `>>>>>>>` markers to resolve keeping both sides' intent, and has
  no git step. If the merge cannot be done (the team deleted a file dev
  changed, for instance), or fails part way, the copy is put back exactly as it
  was and the message says why before the steps it gave until now.
