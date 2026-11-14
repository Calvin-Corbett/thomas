### Security

- **Everything the gates trust is now protected while Thomas runs, not only when
  committing.** A sweep of every file Thomas's gates read found fifteen that an agent's
  file tools could rewrite live, including `.git/hooks/pre-commit` (the hook that runs
  every gate), `.git/config`, the verification records two gates read, the bulk-commit
  waiver list, the board whose claims and acks the coordination gates judge, the
  "already passed" markers, the rule files gates quote, and `.gitignore`, which decides
  what a gate can see at all. Each was refused at commit time and writable at run time,
  which is the moment a running gate reads it. All of them now need your approval at
  the OS prompt. Git itself is unaffected: the refusal applies to the agent's file
  tools, not to git commands. `.gitignore` is protected in every project, because
  hiding a file from a check is the same problem wherever it happens.
