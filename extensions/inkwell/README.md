# Inkwell — the smart notepad

Sketch it, say it, type it — Thomas turns it into reminders.

Inkwell is a free-form smart notepad command center:

- **Draw with your mouse** — pen, highlighter, and eraser on an infinite
  dotted page. Strokes save with the page.
- **Type anywhere** — switch to Text mode and click any spot on the page
  to drop a note block there. Drag blocks around, any order, any layout.
- **Speak instead of typing** — the mic button dictates straight into the
  focused block (browser speech-to-text, local-first).
- **Reminders with real alert sounds** — set a date + time and pick a
  chime, bell, alarm, or pulse tone. Inkwell watches the clock and plays
  the alert (plus a desktop notification) when it's time. One-shot,
  daily, or weekly.
- **Thomas reads your notes** — hit "Ask Thomas" (or leave Auto on) and
  the active Thomas model extracts time-bound items from the page and
  proposes reminders and next-step suggestions. One click accepts them.

## Storage

Local-first JSON at `.thomas/plugin-data/inkwell/state.json` under the
configured memory root — same pattern as Life Manager. Nothing leaves
the machine except the note text sent to the configured model when you
ask for smart analysis.

## API

- `GET  /api/plugins/inkwell/bootstrap` — full state
- `*    /api/plugins/inkwell/{notes|reminders}` — list / create
- `*    /api/plugins/inkwell/{collection}/{id}` — patch / delete
- `POST /api/plugins/inkwell/analyze` — `{text, local_now}` → proposed
  reminders + suggestions (503 with a friendly message when no model is
  configured; everything else keeps working)
