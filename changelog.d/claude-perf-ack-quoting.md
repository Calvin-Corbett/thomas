### Fixed

- **The command that clears the message gate works with a quoted pipe in it.** The gate
  splits a command on `;`, `|` and `&&` to check each part separately, but it could not
  tell a real pipeline separator from the same character inside an argument — so an
  ordinary acknowledgement piped through `grep -oE "acked|already"` was refused, because
  the half after the quoted pipe matched nothing it recognised. Quoting is now read the way
  a shell reads it, including that `$(…)` still expands inside double quotes but not single
  ones, and an unbalanced quote is refused rather than guessed at.
