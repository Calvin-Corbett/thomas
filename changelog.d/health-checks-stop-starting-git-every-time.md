### Changed

- **Pages load faster because Thomas no longer starts git to check which commit it is on.** You asked for everything to feel snappy. Thomas's own timing showed that check running 448 times at about 1.4 seconds each in one run, holding up the server while pages loaded. It now reads the answer from git's own files and remembers it until the commit changes; if anything looks unusual it asks git as before.
