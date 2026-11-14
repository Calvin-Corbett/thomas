### Fixed

- **A Build update no longer buries its own words under a pasted diff.** A block of code longer than 12 lines now folds behind one line that says how long it is ("Show 30 lines of code"); the sentences before and after it stay in the open, and a short block is drawn as before.
- **Coming back to a task that kept running reads "Reconnected".** It used to draw a row titled "disconnected" over the words "Reattached", which read as a failure. A real drop is now titled "Connection lost".
- **Build stopped printing the names of Thomas's own parts.** After a restart you were told "The Build lead disconnected during restart. Praxis child activity is shown below"; it now says Thomas restarted during the task, that his helpers' steps from before are below, and to start a new run to continue.
- **Work's first step no longer prints a checker's name at you.** Setting up a job showed "selection-is-the-users: selected_workflow_id is empty", and kept showing it after you had chosen a workflow. It now reads "Choose one of the workflows below." and goes away once you choose. The same list is cleared when you start another job, where the last job's steps used to carry over.
- **An empty Work page says what a job is.** It used to be a title, "No jobs yet." and one card. It now gives two examples and says where to type.
- **Saving a new job shows that it is saving, and that it saved.** The button reads "Saving your job…" while the dozen requests behind it run, and the job's page opens with "Job saved". Before, nothing changed on screen until the job appeared in the list.
- **A job's name stops at a whole phrase.** "TEST for UI critique: a job whose only goal is…" was named "TEST for UI critique: a job whose"; it is now "TEST for UI critique".
- **Work's headings use plain words.** "Durable jobs with their own workflows, connector identities, memory, skills, and Mission-backed runs" and "Define the job before the machinery" are gone, and "runs through Mission" reads "run by Thomas's job queue".
- **An empty reply in Work is no longer dressed up as Thomas asking for "one more detail".** It says the reply was empty and to send the message again.

You said: "I like all those critiques. Work on those first."
