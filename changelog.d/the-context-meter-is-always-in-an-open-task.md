### Fixed

- **The context meter is always there when a task is open.** You said you could not see the context window bar you asked for. It only appeared while a run that started after the last restart was live, and showed nothing otherwise, so there was nothing to find. Now an open task always shows the bar: empty with "no reading yet" until Thomas has made a model call, then "75% left" and so on. Opening a task you worked on earlier loads the reading its last run left behind, instead of waiting for a live run. Runs from before today's restart left no reading, so those read "no reading yet".
