# P006 - Browser actions: scroll and scroll-into-view

This gap run adds two **Thomas-native** browser actions:

- **`scroll`**: scrolls the current page viewport by a pixel delta.
- **`scroll-into-view`**: scrolls an element matching a selector into view.

These are implemented as:
- a CLI surface under `thomas browser ...`
- a backend action handler module under `thomas.browser...` that is tolerant of multiple dispatch styles.

## CLI usage

### Scroll

```bash
thomas browser scroll --y 400
thomas browser scroll --x 0 --y -200
```

Machine-readable output:

```bash
thomas browser scroll --y 400 --json
```

### Scroll into view

```bash
thomas browser scroll-into-view --selector "#footer"
thomas browser scroll-into-view --selector ".load-more" --timeout-ms 5000
```

Machine-readable output:

```bash
thomas browser scroll-into-view --selector "#footer" --json
```

## Selector support notes

- When the connected browser backend exposes a Playwright-style `page.locator(...).scroll_into_view_if_needed(...)`,
  selectors can be any backend-supported selector (CSS, `text=...`, etc.).
- The JavaScript fallback uses `document.querySelector(...)`, so it supports **CSS selectors only**.

## JSON output contract (`--json`)

Success:

```json
{
  "ok": true,
  "result": {
    "action": "scroll",
    "delta_x": 0,
    "delta_y": 400
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "ELEMENT_NOT_FOUND",
    "message": "element was not found or could not be scrolled into view before timeout",
    "details": { "selector": "#footer", "timeout_ms": 5000 }
  }
}
```
