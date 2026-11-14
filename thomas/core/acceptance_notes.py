"""Thomas's own notes to a Thomas project's team, which the acceptance contract never reads as the request.

A Thomas project's first message is the request followed by Thomas's notes (``thomas/server/thomas_project_start.py``):
standing notes, lessons from earlier hand-ins and the files other running projects have changed. Read as the request,
they made every file another project had changed a required output of this one (2026-09-27), and no project could
finish. The notes now sit between :data:`THOMAS_NOTES_START` and :data:`THOMAS_NOTES_END`; Autopilot's goal quotes
every message whole, so both markers survive into it. A message sent before the markers existed still loses its
list of other projects' files, the part that named files this project was never asked to make.

Autopilot's report on the last run (``autopilot_messages``) is Thomas's notes too: read as the request, the files a run
changed and the gate failures it quoted became the next run's required outputs. It is marked now, and a report written
before that is recognised by its fixed wording.
"""

from __future__ import annotations

import re

THOMAS_NOTES_START = "[Thomas's notes for this team -- not part of the request]"
THOMAS_NOTES_END = "[End of Thomas's notes]"
_MARKED = re.compile(re.escape(THOMAS_NOTES_START) + r".*?" + re.escape(THOMAS_NOTES_END), re.S)
# thomas_project_words.siblings_note: its header line, then one "- <execution id>: <files>" line per project,
# each possibly indented where Autopilot's goal quotes the message.
_SIBLINGS = re.compile(
    r"^[ \t]*Other Thomas projects are working in their own copies right now\.[^\n]*(?:\n[ \t]*- [^\n]*)*", re.M
)
# autopilot_messages' report on the last run, as written before it was marked (2026-09-27): a continuation's outcome,
# files and transcript tail; a done check's or a resume's files; a repair round's findings, always last. A restart
# still quotes such a message whole after its mark.
# thomas_project_words.TEAM_NOTES, which a first message sent before the markers carried unmarked after the request.
# It always opens with this sentence and runs to the end of that message: the end of the text, or the next message
# where Autopilot's goal numbers them at the start of a line. Read as the request, it made `python -m pytest` over
# the whole suite a command that had to exit 0 and every key of the size rule's baseline a field to consume.
_OLD_TEAM_NOTES = re.compile(
    r"Record this change in a new changelog\.d/<short-name>\.md fragment; never edit CHANGELOG\.md directly\."
    r".*?(?=\n\d+\. |\Z)",
    re.S,
)
_OLD_REPORTS = (
    _OLD_TEAM_NOTES,
    re.compile(r"Last outcome: .*?(?=Diagnose what went wrong, fix it)", re.S),
    re.compile(r"The last run finished: .*?Files changed: [^\n]*", re.S),
    re.compile(r"The last run stopped because .*?Files changed so far: [^\n]*", re.S),
    re.compile(r"^(?:What breaks it|The findings, in full|Why it came back, in full):\n.*\Z", re.S | re.M),
)


def without_thomas_notes(text: str) -> str:
    """*text* without Thomas's notes to the team: marked, or from before the markers the other-projects list and
    Autopilot's report on the last run."""
    text = _SIBLINGS.sub(" ", _MARKED.sub(" ", text))
    for report in _OLD_REPORTS:
        text = report.sub(" ", text)
    return text


__all__ = ["THOMAS_NOTES_END", "THOMAS_NOTES_START", "without_thomas_notes"]
