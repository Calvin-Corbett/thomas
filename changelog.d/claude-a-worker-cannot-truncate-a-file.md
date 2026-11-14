### Fixed

- **A self-fix worker can no longer truncate a file it means to edit.** Workers
  changed files only with whole-file `fs.write_file`; earlier tool arguments are
  compacted out of the model's own context, so a worker rewriting a large file
  from memory truncated it -- one live run did this twice, each followed by a
  long chain of "Recover truncated..." helper runs. You asked: "Are you making
  sure they're actually doing shit? They're not just being dumb." `fs.write_file`
  now refuses a write that would remove more than 40% of an existing file's
  lines or characters (whichever fraction is larger, and only above a 20-line/
  2,000-character floor, so a small legitimate rewrite is never blocked),
  naming `diff.create` as the way to change part of a file instead; pass
  `replace_whole_file: true` when a full replacement really is intended.
  Creating a new file is unaffected, and the same guard applies whether the
  write lands in a self-development green copy or a Build project workspace.
- **`diff.create` actually works inside a self-fix green, for Thomas's own
  folders.** The first landing of this fix pointed self-development workers at
  `diff.create` as the safer alternative to a whole-file rewrite -- but
  `diff.create` and `diff.apply_patch` checked runtime protection against their
  own sandbox root, unlike `fs.write_file` (which checks the real project, not
  the sandbox). A green is a private copy OUTSIDE the project tree, so every
  `thomas/server`, `thomas/tools`, `thomas/agent`, `thomas/core`, and `scripts/`
  path inside a green matched the protected-directory names and was BLOCKED --
  the one place workers were being told to use the patch tool most. Until this
  landed, a self-fix of a core file had only `replace_whole_file: true` left as
  a route past the truncation guard: the rewrite-from-memory the guard exists
  to stop. Both tools now check the same protection roots `fs.write_file`
  already used, so a green's own copy is editable and the real checkout stays
  protected. Every instruction the worker receives -- the isolated worker's
  system prompt, the self-development system prompt, the task-prompt reminder,
  the retry text, the completion requirement, and the write-first guard's own
  refusal -- now agrees: patch an existing file with `diff.create`, create a
  new one with `fs.write_file`, and reserve `replace_whole_file: true` for a
  deliberate full rewrite (the isolated worker's own prompt still said
  `fs.write_file` for every edit through the first landing of this fix; it is
  fixed now too). A single committed read -- a bare `git show <rev>:<path>`,
  `git cat-file -p <rev>:<path>`, or `git cat-file blob <rev>:<path>`, nothing
  else, with no shell characters in `<path>` and a dot in its last segment --
  is exempt from the guard's inspection-loop limit, the same as
  `fs.read_file`. That is one file's committed text, or, for a dotted folder
  such as `changelog.d` or `.github`, at most a one-level listing of that
  folder. The exemption used to also cover an unlimited directory listing and
  two command forms that write a file (`git show HEAD:a.py>x`, with no
  spaces, and `git show --output=<file>`), which the first landing of this fix
  wrongly said it could never do. The failure card's own remedy sentence used
  to say changing Thomas's own code "is not something a chat task can do",
  which was false; it now says plainly that changes are made in a private
  copy and reach the running Thomas when you approve the card, or straight
  through at your operating system's prompt for a one-off change. Text that
  told a green worker it was changing "the live repo" -- the completion
  requirement, two retry sentences, the runner's own failure text, and the
  retry after the run's proof could not be saved -- now says "this self-fix
  run" when the workspace actually is a green, and keeps the old wording only
  when it is not. A retry also looks its green up once, not up to three times.
- **An Autopilot attempt keeps its own momentum, for real.** The first landing
  of this fix tripled the pass budget inside the token-economy calculation,
  before the per-model cap was applied -- so for the default `openai_codex`
  model (capped at 30 passes) the cap won every time and the tripling never
  reached a live run; the changelog and commit message said otherwise. The
  multiplier now applies AFTER the cap: at autonomy 5, a self-development
  worker's per-attempt pass budget is three times whatever it would otherwise
  get, capped or not (90 passes for the default model). The attempt count
  itself is unchanged -- it stays the runaway guard. Likewise, the replan
  prompt after a pass-budget stop was written to carry the last three progress
  lines, but the one caller that builds it still passed a single line, so the
  live retry prompt never saw more than one; it now carries three, alongside
  the files already changed in the green copy.
- **The 40%-truncation boundary gives the same answer for the same edit.**
  Removing exactly 40% of a file's lines was allowed with a trailing newline
  but refused without one (the character share read 40.03%, since a missing
  final newline is one separator short of the same content with one).
  Character counts are now normalised to count as if the file ends in exactly
  one line break either way, so the same edit is judged the same regardless of
  which convention the file happens to use. The 2,000-character floor and
  the counts a refusal reports are the file's own, so a 1,999-character file
  is not guarded. The `fs.write_file` description
  and the worker's own reminder, which still described a lines-only,
  no-floor 40% rule, now state the rule as it actually runs: files of at
  least 20 lines or 2,000 characters, refused above 40% by lines or
  characters, `replace_whole_file: true` to mean a full replacement.
