### Fixed

- **A task is no longer failed for old oversized files it never touched.** When a Build
  run could not run commands, Thomas ran the file-size guard over the whole project and
  failed the run on any violation. On Thomas's own code every task, even writing a
  two-byte file, came back "not finished yet" because of files such as a 1,386-line
  gate script, and the agent was pushed to edit that protected script. The check now
  judges the files the task changed (the files it wrote, plus anything git shows as
  changed), the same rule the commit gate uses, and lists older violations as not
  counted.
