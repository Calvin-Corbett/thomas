# Quality Execution Policy

Thomas execution and evaluation are quality-first and not cycle-limited.

## Core Rules

- Quality is king. Shipping quality and measurable reliability outrank speed.
- Cycle count is not a stop condition. Iteration continues until known meaningful gaps are closed.
- Competitive work does not stop at one pass; it repeats as needed.
- Work only stops when:
  - no known meaningful gaps remain, or
  - the user explicitly directs a stop or reprioritization.

## Suite Binding

- The comparison suite must carry this policy in its config under `execution_policy`.
- Suite outputs must surface this policy in JSON and markdown artifacts.
