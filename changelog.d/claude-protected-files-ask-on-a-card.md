### Changed

- **Every protected file is its own approval now, asked on a card.** You said
  "Every protected file needs to be its own thing", and asked to "leave the
  option open, like would you like to approve just this task or allow me to do
  whatever". Before Thomas changes one of his protected files, the chat that
  started the work shows a card: which file, why, and four answers: **Approve
  this file**, **Approve this whole task**, **Approve everything** (until you
  restart Thomas), or **No**. Each approve asks for your Windows PIN or
  password once, and reaches exactly as far as you chose.
  - **Nothing carries over by time any more.** An approval used to be reused
    silently for five minutes, so one tap for one file approved the next.
  - **A card option that needs your password is a wall, not a button.** The
    server shows the prompt when you pick it, and records the answer only if
    Windows accepts your PIN. Anything else trying to answer, including an
    agent, is refused. If you say no at the prompt, the card stays open.
  - **Thomas can shape a card to what he needs you to decide.** He can give it a
    heading and the facts that matter. A card he makes himself can never carry
    a password option; only the server builds those, for real approvals.

### Fixed

- **Thomas's question cards now reach the chat that asked.** Tool calls were
  never told which chat they ran for, although the code described itself as
  doing so. Questions were filed under no chat, and the chat page, which only
  shows its own chat's questions, never displayed them.
