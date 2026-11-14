### Fixed

- **The status line's words now shimmer in place instead of sliding across the screen, and the clock sits right beside them.** You said the effect should be the letters themselves shimmering, and that the clock was still further away than the composer. The line's animation shared its name with an older one that slides things sideways, so the words were being pushed about 128px instead of lit from left to right. It now has its own animation, the words stay where they are, and the clock follows them at the composer's left edge instead of at the far end of a wider row.
