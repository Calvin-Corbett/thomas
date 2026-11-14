### Security

- **The owner's desk: approvals that still reach you when the server cannot ask
  by itself.** The next step is running the server as the cage's own account,
  and a server running that way has no desktop to show the Windows sign-in on.
  A hacked server would not show it anyway. So the server can now file a request
  instead, and wait for the answer:
  - The request holds only a catalogue card kind, its details and a content
    hash. It never carries words.
  - Your promoter service, which runs as you, renders the card from the pinned
    catalogue, asks at the Windows sign-in with a pairing code, and writes the
    answer where the cage account cannot write.
  - The server counts an answer only for exactly what it asked: same id, same
    kind, same content hash. No answer in time is a no.
  - A kind the catalogue does not have, or a catalogue that fails its pin, is
    answered no without asking.
  - Raising a dial uses the desk when `THOMAS_OWNER_DESK=1`. Until the server
    actually runs caged, nothing changes: prompts appear exactly as before.
