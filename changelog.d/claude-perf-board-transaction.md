### Fixed

- **A message delivered while a claim takeover is running is no longer erased.** The
  takeover captured the board, wrote to it, and on any failure restored the text it had
  captured — but it held no lock across those steps, so another agent's message could land
  in between and be wiped by the restore, with no error and no acknowledgement. Measured on
  the live board: it returned to a byte-identical earlier state and the message written in
  between was simply gone. Two coordination messages were lost that way within two minutes,
  and agents were left following instructions the board had already discarded. The whole
  takeover now runs under one hold of the shared board lock, so the state its rollback
  restores is still the state it verified.
