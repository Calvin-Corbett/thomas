# Retry Policy

Last updated: 2026-02-21

## Goals

1. Retry only transient failures.
2. Avoid duplicate side effects.
3. Keep retries bounded and observable.

## Default Policy

- Attempts: `3`
- Backoff: exponential (`base=500ms`, cap `30s`)
- Jitter: `10%`
- Respect upstream `Retry-After` when present

## Retryable Conditions

- HTTP `429`
- HTTP `5xx` (except deterministic validation/auth errors)
- connect/reset/timeout transport failures

## Non-Retryable Conditions

- HTTP `400`, `401`, `403`, `404`, `422`
- schema/validation failures
- explicit policy denials

## Safety Rules

1. Retries must be per request step, not per whole workflow.
2. Non-idempotent actions must include a request identifier when possible.
3. Log each attempt with reason and delay.

## Operator Checklist

1. Verify upstream rate-limit headers are honored.
2. Confirm repeated failures surface in logs/alerts.
3. Keep retry config consistent across integrations.
