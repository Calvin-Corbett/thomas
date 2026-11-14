### Fixed
- Starting a task with Thomas as the project no longer fails with "preparation exceeded 8 seconds". The start now keeps waiting while it is making progress (files appearing in the new copy, each step finishing) and is refused only when nothing has moved for 30 seconds, with a message that says which step stood still.
- The copy of Thomas's source is written by 8 parallel workers: on this PC the checkout dropped from 5.3-8.2 seconds to 2.6-3.1 seconds, with the same files.
