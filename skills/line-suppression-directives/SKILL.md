---
name: line-suppression-directives
description: Use when implementing analyzer or linter suppression directives such as nosec, nosec-begin/nosec-end, nosec-next-line, noqa, ignore-next-line, disable/enable regions, per-rule selectors, inline comments, warning filters, or line-based suppression for multi-line AST statements and metrics.
---

# Line Suppression Directives

Use this for scanners, linters, and analyzers that suppress findings from comments or directive markers.

## Critical Rule

For AST-backed or parser-backed analyzers, suppression is usually semantic, not just physical. Build a `line -> statement range` map before applying directives. A directive found inside a multi-line statement must be projected through that whole statement range, including earlier lines where findings may be reported.

Before finishing, run a literal probe with `subprocess.Popen(` on one line and `shell=True,  # nosec-begin B602` on a later argument line, followed by `# nosec-end`. The expected remaining IDs for that probe are `[]`; `B602` must be suppressed even though the directive appears on a later physical line than the call expression.

Do not substitute a nearby multi-line case for that probe. A marker on a separate preceding line, or `# nosec-end` inside the statement, does not prove the same behavior. The marker must be on the later argument line itself.

Common failure to avoid: adding a statement-line range to issue filtering is not enough if the directive is never recorded on that statement range. Expand the directive's physical line into its semantic statement range while building the suppression table, before issue filtering and metrics.

## Core Workflow

1. Preserve the existing suppression contract first. If an empty set or sentinel already means "suppress all", keep that meaning stable.
2. Model directives as structured data before applying them: kind, physical line, selector, and scope.
3. Parse selectors separately from scope. Support exact IDs/names first; add globs or boolean operators only when the task asks for them.
4. Convert directive scope to the analyzer's semantic range, not just the directive's physical line.
5. Combine all applicable suppressions for a finding. Blanket suppression dominates specific suppression; specific sets union unless the spec says intersection.
6. Keep metrics aligned with the final suppression decision. Count blanket suppression and specific skipped tests the same way existing inline suppression does.

## Multi-Line Statement Rules

- For AST-backed analyzers, build statement ranges from `lineno` through `end_lineno`, including decorators when relevant.
- Build a `line -> statement range` map. Every directive target line should be expanded through this map before insertion into the suppression table.
- If any line in a multi-line statement carries an applicable inline, region, or next-statement suppression, apply that suppression to the whole statement range before evaluating issues. This includes statement lines before and after the physical directive line.
- Do not implement regions as only active physical lines. A region directive found on line `L` inside a multi-line statement must be projected through `statement_range_for_line[L]`, so a finding reported on the statement's first line is suppressed even when the directive appears on a later argument line.
- `next-line` means the next executable statement, not the next physical nonblank line. Skip comments, blank lines, and grouping-only continuation lines.
- Regions must not leak outside their intended block or file. If the spec supports dedent auto-end, end the active region before applying it to the dedented line.
- Region begin/end marker lines should only suppress themselves when the legacy inline behavior already would.

## Implementation Pattern

Use this pattern unless the repository already has an equivalent semantic range helper:

1. Build `statement_range_for_line` from the parser/AST before parsing suppression comments.
2. Resolve each suppression event to a selector state: `None`, empty set, or non-empty set.
3. When adding a suppression for physical line `L`, call `expand(L)` where `expand` returns the full statement range containing `L`, or `{L}` when no range is known.
4. Insert the suppression on every line returned by `expand(L)`, combining with existing entries.
5. For active regions, apply step 3 on every covered physical line, including the line where the region starts if the marker is inside a statement. Do this immediately when the begin marker is parsed, before advancing to later lines.
6. After the line table is built, issue filtering should inspect all lines in the issue's statement/context range and union the suppressions found there. Do not inspect only `issue.lineno`.

## Selector and Metrics Guardrails

- Keep three states distinct: `None` means no suppression, empty set means blanket suppression, and a non-empty set means specific suppression.
- Do not downgrade a recognized specific selector to blanket suppression. If a selector such as `B602` resolves to a specific rule, metrics should count `skipped_tests`, not `nosec`.
- Do not infer blanket suppression just because the selected specific IDs equal the current enabled-test universe. `# nosec B602` remains a specific suppression even in a profile where B602 is the only enabled check. Only an omitted selector or explicit `all` should produce the blanket sentinel.
- For analyzers with separate plugin and blacklist registries, include both plugin IDs and blacklist/check IDs in selector resolution. In Bandit-like analyzers, rules such as `B602`, `B603`, and `B607` can come from blacklist data, not only plugin functions.
- Unknown free text after legacy inline comments may preserve existing blanket behavior, but explicit directive selectors should only become blanket for omitted selector or `all`.
- When several specific suppressions apply to one issue through region, inline, or next-statement rules, union the specific IDs and keep the result specific.
- Metrics must be checked against the actual sentinel used at skip time. Specific region, next-statement, and inline suppressions should increment the same per-rule skipped counter as existing inline `# nosec B602`; blanket region, next-statement, and inline suppressions should increment the same blanket `nosec` counter.

## Required Local Probes

Before finishing, run probes that mirror the hard semantic boundaries in the prompt, not only adjacent easy cases:

- existing inline suppression compatibility;
- region begin/end with blanket and per-rule selectors;
- next-statement suppression across blank/comment/grouping lines;
- multi-line calls, assignments, decorators, and chained expressions where the finding is reported on a different line than the directive;
- overlapping region, inline, and next-line directives;
- region begin inside a multi-line statement where the issue is reported on an earlier line in the same statement;
- a literal case shaped like `subprocess.Popen(` on one line and `shell=True,  # nosec-begin B602` on a later argument line, expecting no `B602`;
- `none` or no-op selectors;
- unknown selector text preserving legacy blanket behavior only when the prior analyzer treated it that way;
- `ignore_nosec` or equivalent global disable flags;
- suppression metrics for blanket and per-rule cases;
- metrics where a specific selector is the only enabled check, to prove it still counts as specific rather than blanket;
- per-rule selectors for blacklist-style checks, not only ordinary plugin functions.
