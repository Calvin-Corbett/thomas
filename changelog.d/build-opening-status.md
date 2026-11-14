### Fixed

- While a saved Build conversation loads, its Activity header says “Opening…” instead of “Ready,” matching the loading message in the conversation. The header returns to the run status when loading finishes.
- Reopening a running Build restores its run identity before following the stream, so a saved final reply can confirm completion instead of leaving the Activity header at “Disconnected.”
