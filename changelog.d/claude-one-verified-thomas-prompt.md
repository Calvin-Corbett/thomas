### Security

- **Thomas has one password prompt now, and it checks the password.** You were
  shown a "Thomas authorization" box asking for your password so that Thomas
  could change one of his own protected files. That box never checked what you
  typed: pressing OK approved the change with any password, or none. It guarded
  every protected-file write and tool approval, and a second copy of it guarded
  third-party access. There were four different-looking password boxes in all.
  Every Thomas approval now uses the same Windows sign-in, titled "Thomas". It
  takes your PIN or password, and Windows checks it. It deliberately stays
  Windows' own box: that is the only box that accepts a PIN, and Thomas's code
  never sees what you type, so a misbehaving Thomas can neither capture your
  password nor fake the answer.
