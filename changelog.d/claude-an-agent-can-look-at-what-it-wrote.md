### Fixed

- **An agent can open the page it just wrote.** `browser.open` refused every `file://` URL, so a worker that had written a good `index.html` in one minute spent eleven more and roughly 390 MB failing to look at it: it shelled out to `npx playwright install chromium` twice — downloading a browser the tool already had five builds of — and stood up its own `python -m http.server` to reach a file on its own disk. A `file://` path inside the run's own workspace is now allowed.
- **Nothing was loosened to do it.** `check_url`, the SSRF guard shared with `web.fetch` and `eng.web_extract`, is untouched. The allowance is a separate check: it needs a workspace to have been configured for that run, and the path is resolved through symlinks before the containment test, so a link planted inside the workspace pointing outside it is refused. No workspace means no file access at all, which is the default for every caller that does not know its own.

### Changed

- **`browser.py` is three modules instead of 1001 lines.** It sat past the 800-line soft limit, so nothing in it could be changed until some of it moved. The session-free helpers are now `browser_page.py` (URL and selector handling, error phrasing, and the workspace check) and `browser_reading.py` (locator resolution and text extraction); the browser session, the tools and their registration stayed behind.
