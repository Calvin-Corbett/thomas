---
name: recursive-json-schema-validation
description: Implement JSON Schema parsers with recursive $ref, $defs, dependencies, dependentRequired, dependentSchemas, if/then/else, anyOf/allOf composition, and deep enum/const equality without stack overflows or shallow-only tests.
---

# Recursive JSON Schema Validation

Use this skill when a task involves JSON Schema parsing, local `$ref` / `$defs`, recursive schemas, dependencies, `dependentRequired`, `dependentSchemas`, conditional `if` / `then` / `else`, object-keyword schemas without explicit `type`, or schema composition such as `anyOf`, `oneOf`, and `allOf`.

## Workflow
1. Identify the parser entrypoint and how recursive calls share state. Keep one root parse context for the whole schema so nested properties, arrays, dependencies, conditionals, and composition all resolve `$ref` against the same root `$defs`.
2. Treat `$ref` as a lazy validation boundary. Cache or mark a reference as in-progress before recursively parsing or validating its target, and use traversal/data-level cycle guards so self-recursive and mutually recursive data cannot re-enter indefinitely.
3. Do not assume a simple recursive smoke test is enough. Add probes where `$ref` appears under `properties`, array `items`, `anyOf` / `oneOf`, `allOf`, `dependentSchemas`, and inside `then` or `else`.
4. For object-keyword schemas without `type`, parse them as implicit object schemas when they contain object keywords such as `properties`, `required`, `additionalProperties`, `patternProperties`, `propertyNames`, `dependencies`, `dependentRequired`, or `dependentSchemas`.
5. Validate conditional semantics silently: `if` chooses whether `then` or `else` applies; `if` alone, `then` without `if`, and `else` without `if` are no-ops.
6. Preserve public error contracts for unsupported `$ref` formats and missing `$defs` entries.

## Required Tests
- Self-recursive `$ref` where a node has `children.items.$ref` back to itself; verify valid nested data passes and invalid nested data fails without `RangeError` or stack overflow.
- Deep recursion through at least two layers of object properties plus array items and composition, not just one direct `$ref`.
- `$ref` inside `dependentSchemas`, and `$ref` inside `if` / `then` / `else`, all resolving against root `$defs`.
- Invalid `$ref` format and missing `$defs` name should assert the exact required error messages.
- Deep `enum` or `const` equality for object/array values should compare structure, not object identity.

## Rules
- Never stop after only typecheck and existing tests when implementing recursive references; add a targeted runtime probe that exercises nested recursive data.
- If a recursive reference implementation uses a predicate or lazy wrapper, ensure the wrapper does not call back into full schema parsing for the same `$ref` while that ref is already being resolved.
- Distinguish environment failures from logic failures: broken bind-mounted `node_modules` or missing local build artifacts are not proof the schema implementation is wrong; rerun the focused package tests in the repository's native test mode.
