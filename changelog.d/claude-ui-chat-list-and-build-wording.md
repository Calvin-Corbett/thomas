### Fixed

- **Every row in the sidebar list has a visible "⋯".** Rename, pin, archive and delete were reachable only by right-clicking a row, which nothing on screen said. The "⋯" shows when you point at a row or reach it with the keyboard, and opens the same menu.
- **The row menu offers only what works for that row.** Export, share and branch are for chats, and on a Build task they answered with an alert. Delete on a Work job asked the chat store and failed. Those items are no longer offered where they cannot work.
- **A chat's second line says what Thomas answered.** It used to repeat the first thing you typed, which is also where an unnamed chat gets its title, so a row read "pong" over "pong".
- **The cost line explains itself.** Pointing at it now says why a one-word message reads "6.1k in": the count is everything the model read for the reply, which includes Thomas's standing instructions and his list of tools on every message.
- **Build says Build.** About fifty messages still called the mode Code ("Could not open that Code task", "Code history could not be refreshed", "A Code approval is in progress"). They now use the name on the tab.
- **A sidebar test that failed on the code as committed passes again.** The list is put in order with `insertBefore`, and the test's stand-in element never had that method.

You said: "you're going to see a lot of stuff that's probably wrong ... So you go ahead and fix those too."
