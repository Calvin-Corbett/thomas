### Fixed

- **Pasting and dropping files on the composer is now actually in the page.** The first landing of the paste and drop fix carried only the new helper and its test; the changes to the composer, the message bubbles, Build's send and the page itself had been rewritten on disk before they were committed, so nothing changed for you. They are landed now: paste a screenshot or drop a PDF on the composer and it attaches, and the message shows it in Chat and in Build.
