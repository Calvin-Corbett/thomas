---
name: static-taint-analysis
description: Use when implementing static taint/dataflow analysis, interprocedural taint tracking, vulnerability analyzer plugins, Bandit-like checks, B620/B621/B622/B623/B624 rules, or source-to-sink rules for SQL injection, shell injection, path traversal, SSRF, XSS, request.args/form/cookies, sys.argv, input(), os.environ, import aliases, nested functions, f-strings, percent formatting, .format(), or Python walrus/NamedExpr propagation.
---

# Static Taint Analysis

Use this for source-to-sink vulnerability checks, especially when hidden tests count findings and include false-positive fixtures.

## Core Workflow

1. Write the spec as tables before coding:
   - sources;
   - propagation forms;
   - sanitizers;
   - sinks;
   - exact severity, confidence, CWE, and test IDs.
2. Keep source, sanitizer, and sink matching exact unless the spec says to infer broader families. Broad sink matching often passes positive tests but fails false-positive tests.
3. Track taint at expression level and assignment level. Process `Assign`, `AnnAssign`, `AugAssign`, and `NamedExpr`/walrus.
4. Treat walrus as both an expression and an assignment: `(x := tainted)` returns tainted and stores `x` as tainted for later expressions.
5. Propagate taint through multi-hop assignments, concatenation, f-strings, `%` formatting, `.format()`, containers used by formatting, and ordinary function calls unless the callee is an explicit sanitizer.
6. Resolve import aliases before sink matching. Include `import module as alias` and `from module import name as alias`.
7. For nested functions, preserve outer-scope taint for closure reads while letting parameters shadow outer names.
8. Record a finding at every matching sink call whose checked argument is tainted. Hidden tests often assert a minimum count, not just pass/fail.

## Python AST Checks

- Handle `ast.NamedExpr` anywhere `_expr_tainted()` can see an expression.
- For tuples, lists, sets, and dicts, return tainted if any contained value is tainted.
- For `ast.BinOp`, check both sides. For `%` formatting, include tuple and dict members on the right side.
- For `ast.JoinedStr`, check each formatted value.
- For method calls such as `.format()`, check the receiver and arguments.
- For call passthrough, return tainted when any argument or keyword is tainted unless the callee is a spec sanitizer.

## Validation Matrix

Create or run focused tests for:

- each source feeding each sink at least once;
- every sanitizer preventing only the sink family it is supposed to protect;
- non-sanitizer wrappers such as `str()`, `float()`, `html.escape()`, or `os.path.normpath()` still preserving taint unless listed in the spec;
- false-positive fixtures for non-spec sinks;
- alias imports for every sink family;
- nested functions and closures;
- walrus inside sink arguments, walrus assigned before sinks, and walrus inside nested propagation;
- `# nosec` or equivalent suppression at the sink line;
- expected issue counts, not only whether at least one issue appears.

## Safety Rules

- Do not mark parameterized SQL unsafe when taint is only in the params and the query string is untainted.
- Do not add broad sinks like arbitrary `session.get()` or `io.open()` when the spec names only specific modules/functions.
- Keep confidence/severity/CWE stable across all variants of the same rule.
- Run baseline tests plus the new targeted tests; taint plugins easily break existing analyzer behavior through over-broad matching.
