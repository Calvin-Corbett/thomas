### Fixed

- **A helper builder's own read-only finish check is no longer refused for having a
  `>` in it.** The finish-check guard matched a bare `>` anywhere, so a Python
  comparison quoted inside `-c "..."` (`p.stat().st_size > 0`) or a JS arrow function
  read the same as a shell redirection and was refused with "the VERIFY: command is
  not allowed to run" — measured live in your Pokemon build, where the css/styles.css
  helper's file check failed for exactly this reason and its work was thrown away.
  The guard now ignores a `>` quoted inside a script argument and allows a command's
  own stream duplication (`2>&1`) or discarding its own output when the null device is
  the whole target (`> nul`, `> /dev/null`); a review round then found five real ways
  a check could still write outside the workspace under cmd.exe even with that first
  fix — an unanchored null-device check Windows path collapse defeated, single quotes
  that do not quote at all in cmd.exe, a stray `=` before `>` that was read as safe
  everywhere instead of only inside quotes, a caret-escaped quote (`^"`) that is not a
  real delimiter, and a shell re-entered inside a quoted argument (`cmd /c "...>..."`,
  `sh -c '...>...'`). All five are refused now: the null-device exemption only applies
  when it is the whole target, quoting is OS-aware (only `"..."` on Windows, and a
  caret-escaped quote is never a delimiter), and re-entering `cmd`, `sh`, `bash`,
  `powershell`, or `pwsh` inside the command line is refused outright. Every other
  destructive verb (now including `del`, `erase`, `rd`, `rmdir`, `format`,
  `remove-item`, `rimraf`) and piping into any shell (`sh`, `bash`, `zsh`, `cmd`,
  `powershell`, `pwsh`, `iex`/`Invoke-Expression`) still stays refused — but those new
  verbs were then matched against the raw command text, so Python's own `del d[1]` and
  `'{}'.format(1)` quoted inside a `-c` script were refused too, even though no shell
  ever runs them. A destructive verb is now matched only against the quote-stripped
  text; a re-entered shell or a pipe into one still has to match the raw text, since a
  re-entered shell's own quoted payload is exactly what must not be stripped away.
- **A helper's finish check now runs with the Python your own commands already
  use.** The check ran through a plain subprocess, not the cage, so it inherited that
  process's own PATH — which carries no bare `python`. The same build's README.md
  helper failed with `'python' is not recognized as an internal or external command`
  even though its check was correct. A leading `python`/`python3` is now resolved to
  the interpreter this run already uses before the shell sees it, quoted the way that
  shell actually expects.
- **A helper that never wrote anything is no longer reported as having kept
  content.** A private builder's workspace starts from a snapshot that already
  includes whatever the target file held before the helper ran, so a file being
  present there was never proof the helper wrote it. A kept-copy note is now recorded
  only when the file's content actually differs from that starting snapshot.

### Changed

- **A failed helper hands its file back instead of losing it.** A helper's private
  workspace already keeps whatever it last wrote; a child that ends failed with real
  new content now has that file's path recorded in the team ledger and named in the
  lead's tool result — which file, where the kept copy is, and why it failed — so the
  lead can repair it instead of starting over from nothing.
- **At maximum reasoning effort, Build is told to split independent work across
  helpers.** You asked for Thomas to split the game across multiple builders; at
  maximum effort the lead's own instructions now say plainly to give each independent
  part its own helper, then integrate and check the whole. Below maximum effort,
  splitting remains the lead's own call, and `task.team`'s description now says when
  splitting pays either way.
