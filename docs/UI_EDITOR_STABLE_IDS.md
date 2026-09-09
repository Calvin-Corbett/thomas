# UI Editor Stable IDs (`data-thomas-id`)

The UI Editor now persists overrides and notes by stable target IDs first, with selector-hash fallback only when no ID exists.

## Why this matters

- Stable keys survive DOM reshuffles.
- Notes and token overrides stay attached to the same semantic element.
- Runtime apply/rollback is predictable.

## How to add IDs

1. Add a unique `data-thomas-id` on the element you want to be editable.
2. Keep IDs semantic and stable (`area.component_name`).
3. Never reuse the same ID for different UI meaning.

Example:

```html
<div class="composer-input-row" data-thomas-id="chat.composer_row">
  ...
</div>
```

## Starter ID map in current Thomas UI

- `app.root`
- `sidebar.left`
- `sidebar.chat_panel`
- `sidebar.chat_list`
- `sidebar.collapse`
- `sidebar.new_chat`
- `sidebar.search_input`
- `main.content`
- `main.top_nav`
- `top.sidebar_toggle`
- `chat.stream`
- `chat.composer_container`
- `chat.composer`
- `chat.composer_row`
- `chat.composer_input`
- `chat.send_button`
- `chat.mic_button`
- `chat.attach_button`
- `chat.suggestions`
- `chat.suggestion_bubbles`
- `chat.disclaimer`

## Override model

`overridesById` and `notesById` are keyed by:

- Primary: `data-thomas-id` (for example `chat.composer_input`)
- Fallback: `selector:<hash>`

Shape:

```json
{
  "overridesById": {
    "chat.composer_row": {
      "selector": "body > ...",
      "styleOverrides": { "width": "640px" },
      "tokenOverrides": {
        "density": "compact",
        "gap": "sm",
        "padding": "sm",
        "buttonSize": "sm",
        "flexPriority": "preferInput"
      }
    }
  },
  "notesById": {
    "chat.composer_row": [
      { "id": "ui-note-...", "text": "make this tighter", "status": "open" }
    ]
  }
}
```
