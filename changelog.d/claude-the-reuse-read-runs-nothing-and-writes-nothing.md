### Fixed

- **Checking whether a project has changed runs no program the project names, and writes nothing.** Before Thomas answers a repeated test run from its last result he asks git for the state of the project. A git project can name a program for git to start, and the project folder is where an agent writes. The checks Thomas already had turned that off; this new read did not, and it also let git refresh its index, which another agent may be using. It now does neither. An automated security review caught this within minutes of the change landing.
