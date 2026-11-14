### Fixed

- **A curly quote no longer erases a file's history in the monolith guard.** The
  guard asks `git show HEAD:<path>` how many lines a file had before your change,
  and it requested text without naming an encoding, so Python fell back to the
  platform codec -- cp1252 here. One byte outside that set took the read down. On
  Windows subprocess decodes on a reader thread, so the `UnicodeDecodeError` died
  there, never reached the caller, and `returncode` stayed 0; the function read
  that as "git succeeded, output empty" and returned **0 lines**. Growth is
  `now - baseline`, so a decode failure reported the whole file as new: the
  maximum blocking verdict, justified by a number that was not true.
  `thomas/server/web/js/unified_work_mode.js` -- valid UTF-8, 864 lines, barely
  changed -- was refused as `baseline 0, growth 864`. All five git readers in the
  guard now name their codec, and a decode that produces nothing returns "unknown"
  rather than zero.
