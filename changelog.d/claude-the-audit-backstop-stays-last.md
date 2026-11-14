### Changed

- **The audit backstop task stays last in the board's Up For Grabs list.** The chat dispatcher and the sweeps that return a task to the queue used to add tasks after `audit-24h-backstop`, which made the board check that runs before every push fail. They now insert before it or put it back at the end, so a push no longer stops on the board's order. The brainstorm dispatch still writes through a protected tool and is covered by a written proposal.
