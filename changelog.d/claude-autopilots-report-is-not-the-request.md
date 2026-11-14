### Fixed

- **A Thomas project is no longer made to create files nobody asked for.** Three projects created a sign-in-shaped `auth.json` and another project's doc in their copies to get past the completion gate. Three misreadings kept those files as required outputs:
  - A sentence that said the files it named were never outputs was read as asking for them. A sentence or clause that says its files are not outputs, or says not to create them, now names none.
  - Autopilot's report on the last run was read as part of your request: the files it changed, the gate failures it quoted and the tail of its transcript. So whatever a run touched, or failed on, became the next run's required output. The report now sits inside Thomas's notes markers. A report written before that is recognised by its fixed wording, including when a restart quotes it again.
  - Every missed item is kept as a learned check for later runs, so misreadings fixed earlier kept coming back. A learned output is now dropped when the request still mentions the file but no longer reads it as an output, or when the file is in the last commit. A learned output the request never mentions still stands.
