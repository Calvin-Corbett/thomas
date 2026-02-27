# Placeholder Completion Policy

## Purpose
Placeholder behavior is allowed only as a short-lived development state. Production runtime paths must not silently succeed when implementation is missing.

## Required Placeholder Note
If a placeholder exists in source, it must include a short completion note with:

1. `why`: why the placeholder exists.
2. `scope_to_finish`: exact user-visible behavior that must be implemented.
3. `owner`: owning stream/team.
4. `exit_rule`: required runtime exit behavior until complete.
5. `acceptance`: concrete completion checks.

## Runtime Rule
For executable CLI/runtime commands:

1. Execute real logic, or
2. Fail non-zero with structured error (`code`, `category`, `message`).

Never return success via implicit noop for run mode.

## Definition of Done
A placeholder is considered complete only when:

1. A real callable runtime entrypoint exists.
2. Direct command execution proves non-noop behavior.
3. JSON mode returns machine-readable output.
4. Tests lock behavior.
