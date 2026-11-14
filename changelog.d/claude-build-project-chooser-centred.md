### Fixed

- **Build's project chooser opens on the reading column.** You reported that "the
  project folder renders off to the right rather than centered". The panel is
  `position:absolute; left:0` inside the folder button's wrap, and that wrap is the
  third control in the composer's row — so `left:0` was the button's left edge, about
  140px in from the composer card, while the panel is sized to the whole 760px reading
  column. It started a third of the way across the column it was sized for, and got
  worse rather than better as the window changed: across the viewer in Build's viewer
  layout, off the right edge of the screen at phone widths. Nothing in the markup
  could fix it, because the offset needed is the distance between the trigger and the
  column's centre and neither is known until layout. `positionLibraryMenu()` now
  measures the composer rail — which is the reading column — and the trigger, centres
  the panel on the column, caps its width by the rail, by its own 760px design width
  and by the viewport, and clamps the left edge so a 16px margin survives a
  phone-width window. It is rewritten on every open, on window resize, and through a
  ResizeObserver on the rail, so Build's activity drawer and viewer move the panel
  with the column they narrow. A notification that lands before the rail has a box —
  Build's surface mid-swap — is ignored rather than pushed through the arithmetic, so
  an open panel keeps its geometry instead of collapsing to nothing for a frame.
  Verified by measurement, not by reading the CSS: the shipped arithmetic is run
  against Build's normal, activity, viewer, narrow and narrow-then-wide layouts,
  against two layouts that force the 16px edge margin to be the answer rather than the
  centre — a column beginning left of the window, and a column pushed right by the
  viewer in a small one, so the margin that keeps the chooser on a phone screen is
  something a check can fail on — and through the open path itself — clicking the
  folder button — so the case you take is covered by the check that runs on every
  machine and not only by the browser test, which skips where Chromium cannot launch.
  A headless Chromium run then opens the real chooser inside a real Build tab at 1440,
  1100 and 390 wide — onto a library of six projects, so what is measured is the shelf
  you pick from and not an empty panel — finds its centre on the column's centre,
  checks the page logged no error while getting there, and photographs each width
  twice — once fixed, once with the old `left:0` anchor put back on the same open
  panel — so the two layouts can be compared rather than taken on description;
  `THOMAS_CHOOSER_SHOTS=<folder>` collects that pair somewhere you can open it instead
  of pytest's temp folder. `tests/web_node/build_project_chooser.html` is a probe you
  can open in a browser to see it, with a button that puts the old `left:0` anchor
  back beside it. (`thomas/server/web/js/chat_composer_panels.js`,
  `tests/test_build_project_chooser_position.py`,
  `tests/web_node/build_project_chooser_position.mjs`,
  `tests/web_node/build_project_chooser.html`, `tests/web_node/conftest.py`)
