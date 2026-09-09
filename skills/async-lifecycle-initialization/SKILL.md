---
name: async-lifecycle-initialization
description: Implement async service initialization, lifecycle startup, dependency graph ordering, concurrency-limited initializers, rollback/disposal on failure, idempotent initialization, and circular dependency handling for DI containers or resource registries.
---

# Async Lifecycle Initialization

Use this skill when a task adds `initialize()`, async setup hooks, service lifecycle startup, dependency-aware ordering, rollback, disposer cleanup, or concurrency limits to a dependency injection container, plugin registry, resource manager, or service graph.

## Workflow
1. Map the public async contract first. If the API is `async` or returns a Promise, every failure path, including graph construction and circular dependency detection, must reject through that Promise instead of throwing synchronously before the Promise is returned.
2. Separate graph planning from state mutation. Build and validate the initialization graph before marking the container as initializing or failed. Graph-build failures such as circular dependencies should leave the container retryable.
3. Compute dependency levels explicitly: dependencies at lower levels finish before dependents start; independent registrations in the same level may run concurrently.
4. Apply concurrency limits inside each level only. A global limit must not allow a dependent to start before every dependency level has completed.
5. Track initialized services in completion order for rollback. On initializer failure, wait for all in-flight initializers in the current level to settle, then dispose already-initialized services in reverse order. Disposer errors must not replace the original initializer error.
6. Preserve cache semantics. Services without initializers should remain resolvable normally; initialized replacements returned by hooks must update the cached singleton/scoped value used by later resolution.

## Required Tests
- A circular dependency discovered while building the initialization graph rejects `await container.initialize()` with the expected resolution error and does not put the container into a failed state.
- Dependency order: `database -> repository -> service` initializes by level, and metrics report the expected level for each registration.
- Parallel independent initializers run concurrently within a level and obey a configured concurrency limit.
- Failure rollback waits for same-level in-flight initializers, disposes completed services in reverse order, preserves the original failure as `cause`, and ignores disposer failures for the thrown error.
- Initialization is idempotent after success, but a runtime initializer failure prevents unsafe re-initialization unless the API explicitly supports reset.
- Scoped/child containers can initialize their own registrations without reinitializing already initialized parent singletons.

## Rules
- Do not rely only on existing unit tests when adding lifecycle APIs; add or run runtime probes for circular graph rejection, retryability after graph errors, rollback order, and concurrency.
- Avoid resolving dependents while building the graph unless resolution is explicitly safe; use resolver metadata or parsed dependencies when available.
- Treat missing build artifacts or optional native bundler packages as environment issues. Use source-level type checks and targeted runtime probes when the official verifier will build in its own Linux environment.
