### Fixed

- **A default `claim.py --claim` was refused for every new agent.** The board's task-manager seat named an agent that stopped weeks ago and holds no claim; the claim tool made newcomers its workers, and the claims check then refused the claim as having an unknown parent. A seat holder that holds no claim is no longer made anyone's parent, so the newcomer claims on its own, as the first agent in a new project already did.
