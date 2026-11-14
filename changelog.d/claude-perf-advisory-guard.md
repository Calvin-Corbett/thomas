### Security

- **A hook that cannot fail is no longer allowed to look like a gate.** Three checks that
  make an agent read its coordination messages before committing had been switched to
  advisory — they printed the unread messages and let the commit through, on every stage at
  once. It was never committed, and its author removed it, but nothing would have stopped
  it coming back: the existing test covers a gate that fails without failing the commit,
  and a gate told to advise never fails in the first place. Registering any check in
  advisory mode now fails the suite unless it is listed with a reason.
