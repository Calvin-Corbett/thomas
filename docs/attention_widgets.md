# Widgets beside the conversation

A widget is a small panel Thomas puts in the empty space left of the conversation. It shows live readings, lists,
progress and switches, drawn in the app's own style, and it stays until you close it. Thomas can summon one that
ships, make one on the fly, or save one he made so it can be summoned again.

Everything here belongs to the row **Cards beside the conversation** (`attention`). Turn that row off and no widget
appears.

## What a widget is

A widget is a title and a list of **blocks**. Thomas never writes markup for one. He names blocks, and the page draws
them the way the Context window and Steps panels in Build are drawn.

```json
{
  "title": "This PC",
  "every_seconds": 4,
  "blocks": [
    {"type": "meter", "label": "CPU", "reading": "machine.cpu"},
    {"type": "meter", "label": "Memory", "reading": "machine.memory"},
    {"type": "spark", "label": "CPU, last few minutes", "reading": "machine.cpu_history"}
  ]
}
```

## The eight kinds of block

| Type | What it shows | What it takes |
|---|---|---|
| `text` | A sentence or two | `text` |
| `reading` | One big number or word | `label`, `value`, optional `unit`, `hint` |
| `meter` | A bar from 0 to 100 with a tick at a limit | `label`, `value`, optional `mark`, `hint` |
| `rows` | A list of name and value | optional `label`, `rows`: `[{label, value, note}]` |
| `steps` | A checklist with a count and a bar | optional `label`, `steps`: `[{label, state, note}]`; `state` is `done`, `active`, `pending` or `blocked` |
| `spark` | A small line of recent values | `label`, `points`: numbers, optional `unit` |
| `buttons` | Up to four buttons that answer | `options`: `[{id, label}]` |
| `toggle` | A switch for one plugin row | `setting`: `row:<the row's id>` |

A widget takes at most 12 blocks. The rules are in `thomas/core/attention_blocks.py`, and anything a block does not
take is dropped.

A `toggle` is the one block whose words are not the maker's to choose. The server writes its label and its position
from the row's real name and state, so a switch cannot be labelled as something it is not. A row that cannot be turned
off shows as locked.

## Live readings

A block can name a **reading** in place of its own value: `"reading": "machine.cpu"`. The server fills it in every
`every_seconds`. These ship:

| Reading | For | What it answers |
|---|---|---|
| `machine.cpu` | `meter` | This PC's CPU load, with the limit where Thomas holds new work |
| `machine.memory` | `meter` | This PC's memory in use, with the same limit |
| `machine.cpu_history` | `spark` | CPU load over the last few minutes |
| `machine.memory_history` | `spark` | Memory in use over the last few minutes |
| `thomas.facts` | `rows` | Version, commit, how long Thomas has been up, whether he is restarting |
| `plugins.summary` | `rows` | How many plugin rows are on, off, starting or failed |
| `plugins.not_on` | `rows` | The plugin rows that are off or failed |
| `cards.open` | `reading` | How many cards and widgets are open now |

## The widgets that ship

| Name | What it shows |
|---|---|
| `machine` | CPU and memory against the limit, and the last few minutes of CPU |
| `thomas` | What is running, for how long, and whether a restart is waiting |
| `plugins` | How many plugin rows are on, and which are not |
| `switches` | Switches for the Agents page, Work, the notification tools and reply display types |
| `overview` | CPU, memory, what is running and the plugin count in one widget |

## How Thomas uses them

Thomas has four tools while the row is on:

- `attention_widget` with a `name` summons a widget. With no name it lists every widget, every reading, and what each
  kind of block takes.
- `attention_show` with `"kind": "widget"` and `blocks` shows a widget made on the fly.
- `attention_widget_save` keeps a widget he designed under a name, so it can be summoned again.
- `attention_read` reads which button you pressed on a widget that has buttons.

Other programs can do the same over HTTP: `GET /api/attention/widgets` lists them, and
`POST /api/attention/widgets/<name>` summons one.

## Making a new template

**A saved template, no code.** Ask Thomas to save one, or put a JSON file shaped like the example above in the
`attention/widgets` folder of Thomas's data folder. The file's name is the widget's name: 2 to 40 lowercase letters,
digits and dashes. It is read from disk each time, so it is there after a restart.

**A template that ships.** Add an entry to `BUILT_IN` in `thomas/server/attention_widget_templates.py`: a `title`, an
`about` sentence, `every_seconds`, and `blocks`. Nothing else changes; the name can be summoned at once. Add a row for
it to the table above, which a test checks against the code.

**A new reading.** Add a function to `thomas/server/attention_widgets.py` with `@reading("area.name", "what it is and
which block it is for")`. It takes the `Widgets` object and answers the fields its block kind takes (see `FILLS` in
`thomas/core/attention_blocks.py`). Keep it quick: it runs every few seconds while a widget that names it is open. A
reading that cannot be taken answers nothing, and its block keeps the last value it had.

**A new kind of block.** This is the rare case, and it has three parts that must agree: the rules in
`thomas/core/attention_blocks.py`, the drawing in `thomas/server/web/js/attention_widget_view.js`, and its style in
`thomas/server/web/css/attention_cards.css`. Use the app's own tokens and sizes, never a colour of its own.

## The tests

`tests/test_attention_widgets.py` covers the blocks, the readings, the templates, saving and the switches, and checks
that this guide lists every block kind, reading and shipped widget. `tests/web_node/attention_widgets.mjs` draws each
kind of block. `tests/test_turning_attention_off_touches_only_its_routes.py` proves the row turns off cleanly.
