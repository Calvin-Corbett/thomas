### Added

- **Thomas can summon widgets beside the conversation.** A widget is a small panel that stays open and shows live readings, lists, progress and switches. Five ship: `machine` (CPU and memory against the limit where Thomas holds new work, and the last few minutes of CPU), `thomas` (what is running, for how long, and whether a restart is waiting), `plugins` (how many are on and which are not), `switches` (four plugin rows you can turn off and on from the widget) and `overview`.
- **He can make one on the fly, and save it.** A widget is a list of blocks he names: text, a reading, a meter, rows, steps, a spark line, buttons or a toggle. A block can name a live reading such as `machine.cpu` and it is refilled every few seconds without the widget blinking. A widget he saves is kept in the data folder and can be summoned again by name.
- **A switch on a widget always says what it really is.** Its label and position are written by the server from the plugin row's real name and state, never by whoever made the widget, and a row that cannot be turned off shows as locked.
- **A guide.** `docs/attention_widgets.md` lists the eight kinds of block, every live reading and every widget that ships, and says how to add a saved template, a shipped one, a new reading or a new kind of block. A test holds the guide to the code.

### Changed

- **Cards and widgets are drawn as the app's own panels.** The coloured left edge is gone. They use the surface, border, corner, type, bars and pill buttons of the Context window and Steps panels in Build. You said of the first version: "I don't like the color you added, looks simple AI, not like an Apple product ... the stuff I'm talking about looks like the stuff on the right."

### Fixed

- **Cards no longer fold into a counter on a Build tab.** The space beside the conversation was measured against Build's transcript box, which spans the whole width, so it read as no space at all. It is measured against the column the composer sits in.
