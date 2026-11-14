### Fixed

- When a run stops early, for example when a background worker on a task you handed to Chat stops at a provider error, Thomas now finishes closing that run, including a quality retry inside it, before moving on. Before, the inner part of the run was left waiting and cleaned up later from somewhere else, so the label tying model calls to their run could remain after the run ended, and the worker shut its model connection before its run finished closing.
