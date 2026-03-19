# Placeholder Completion Policy

## Purpose
Placeholder behavior is allowed only as a short-lived development state. Production runtime paths must not silently succeed when implementation is missing.

## Required Placeholder Note
If a placeholder exists in source, it must include a short completion note in the file itself with:

1. `why`: why the placeholder exists.
2. `scope_to_finish`: exact user-visible behavior that must be implemented.
3. `owner`: owning stream/team.
4. `exit_rule`: required runtime exit behavior until complete.
5. `acceptance`: concrete completion checks.

Supported inline format for Python/commented source:

```py
# Source placeholder for module.py (bytecode in __pycache__)
# placeholder-why: Path-stable source placeholder retained while the source-backed implementation is restored.
# placeholder-scope_to_finish: Check in the real source for module.py or replace all imports/callers with a source-backed module.
# placeholder-owner: thomas/<module>
# placeholder-exit_rule: Runtime must fail fast or use an explicit fallback; it must never silently noop as a successful implementation.
# placeholder-acceptance: Real source is checked in, cached-bytecode dependence is removed, and targeted import/runtime tests pass.
```

## Runtime Rule
For executable CLI/runtime commands:

1. Execute real logic, or
2. Fail non-zero with structured error (`code`, `category`, `message`).

Never return success via implicit noop for run mode.

## Gate Rule
Placeholder-backed files are incomplete unless all required placeholder-note fields are present.
Thomas agents should fail quality gates when they create or modify placeholder-backed files without these annotations.

## Definition of Done
A placeholder is considered complete only when:

1. A real callable runtime entrypoint exists.
2. Direct command execution proves non-noop behavior.
3. JSON mode returns machine-readable output.
4. Tests lock behavior.
5. The placeholder note is removed because source-backed implementation is checked in.
