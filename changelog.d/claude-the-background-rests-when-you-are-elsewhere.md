### Fixed

- **The animated background rests while you use another window.** The moving world behind the page ran all day whether or not Thomas was the window in use. On the desktop app it took about 3% of a 16-core PC, nearly all in the graphics process (5.8% with it running, 2.5% paused, measured over 15 seconds each). It now pauses when the window loses you or is hidden, and carries on when you come back. Only the background rests: a dot that shows work going on keeps moving. Add `?motion=1` to the address to keep it moving always.
