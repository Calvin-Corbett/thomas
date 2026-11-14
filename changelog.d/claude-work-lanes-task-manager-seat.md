### Fixed

- **A project always has a task manager, and the first agent to arrive becomes
  it.** The assignment layer already existed -- `scripts/crew/tasks/manager.py`
  can sync the board, sweep inactive agents, auto-start tasks and dispatch idle
  ones, and it is wired into bootstrap, the startup router and the presence
  monitor. It had never run once. Three breaks, each sufficient alone:
  `ensure_praxis` created a board and appointed nobody; every agent arrived
  `solo`, because `claim_utils` returns `"solo"` when no role is given; and
  `bootstrap_claim` only dispatches when `role == "parent"`. So agents raced for
  claims instead of being assigned work, and that race is what deadlocks a shared
  checkout. The board now carries a `## Task Manager` section, the first agent to
  scaffold takes the seat, later ones are workers, and a vacated seat passes to
  the next arrival. Deliberately not built as a refusal: a gate whose failure mode
  is "no manager yet, so nothing may happen" would deadlock the first agent in
  every new project, which is the exact shape of bug this removes.
