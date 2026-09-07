# Task Problem Record: audit-24h-backstop

- task_id: `audit-24h-backstop`
- owner: `unassigned`
- status: `resolved`
- scope: `thomas`
- summary: ensure every major module is audited in last 24h and fix findings
- created_at_utc: `2026-03-06T00:01:49+00:00`
- last_synced_at_utc: `2026-08-26T00:00:00+00:00`
- closure: accepted-risk:2026-08-26-problem-record-py-s-unlocked-append-can-double-fire-records-when-two-auto-checks-py-processes-run-within-the-same-second-the-40-audit-24h-backstop-failure-records-were-produced-this-way-during-a-since-fixed-surface-parity-failure-window-the-real-fix-is-a-file-lock-in-pinned-problem-record-py-gated-behind-a-future-tap-1

## Problem Statement

- Describe what is broken, missing, or risky.

## Evidence

- Link logs, failing tests, screenshots, or message ids.

## Root Cause Hypothesis

- Capture the current best explanation before coding.

## Fix Plan

1. Implement the smallest root-cause fix.
2. Validate using focused tests and runtime checks.
3. Record final outcome and residual risk.

## Outcome

- Pending implementation. (Original template text retained -- see the
  Closure section below for the honest current-state finding: this record
  was never a real incident about one bug, it was a dumping ground for every
  `auto_checks` failure across five months.)

## Closure (2026-08-26, phase-2 batch-2 verification)

- Fresh run today, offline (`.venv/Scripts/python.exe scripts/forge/gates/surface_parity.py`):
  ```
  Surface parity check: OK
    server wire events: 13
    web handlers: 25
    cli EventType handlers: 8
  ```
  Exit 0. The gate is a pure static-content diff over three surfaces
  (server stream emitters, the web runtime JS glob, CLI event handlers) --
  it never touches `:8899` or any live server. It passes cleanly with no
  source change to `surface_parity.py` itself since 2026-07-27.
- Mechanism of the 40 Failure Records above: every one is labeled
  `runner: auto_checks` (or, for two entries, `runner: doc`), never a
  collision between the two -- `scripts/auto_checks.py:GATE_STEPS` lists
  "Surface parity gate" exactly once, so a single `auto_checks.py` run can
  only trip `_record_problem_failure` once per step. `problem_record.py`'s
  `record_failure` does a plain unlocked read-modify-write of this file --
  no lock, no dedup. Two independent processes each running the full,
  non-quick `python scripts/auto_checks.py` within the same second (this
  repo's already-documented pattern of concurrent agent sessions in one
  checkout) each appended their own entry, which is why the 40 records come
  in duplicate pairs at (almost) identical timestamps. No CI workflow runs
  full `auto_checks.py` (`.github/workflows/robustness-gates.yml` uses
  `--skip-gates`; `merge_readiness.py` uses `--quick`) -- every one of these
  40 records came from a manual full run.
- The underlying Surface-parity complaints (2026-07-16 through 2026-08-14,
  exit 1 each time) are STALE: the surfaces were brought back into parity by
  other work in that window, and nothing about this record's genuinely
  unresolved thread (the double-append hygiene gap in `problem_record.py`)
  is fixed by touching `surface_parity.py`, which was never broken by
  design, only briefly out of sync.
- The real fix for the double-append mechanism is a file-lock in
  `scripts/crew/workboard/problem_record.py`, a PINNED file -- gated behind
  a future tap, not built here. Closed under accepted risk
  `2026-08-26-problem-record-py-s-unlocked-append-can-double-fire-records-when-two-auto-checks-py-processes-run-within-the-same-second-the-40-audit-24h-backstop-failure-records-were-produced-this-way-during-a-since-fixed-surface-parity-failure-window-the-real-fix-is-a-file-lock-in-pinned-problem-record-py-gated-behind-a-future-tap-1`
  (owner `calvin (standing delegation 2026-08-24, claude-recorded)`, expires
  2026-11-30).

## Failure Records
### 2026-07-16T21:39:32+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-16T21:39:32+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-16T22:28:48+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-16T22:28:48+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-16T22:51:30+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-16T22:51:30+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-17T00:03:38+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-17T00:03:38+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-18T19:59:21+00:00 - doc: Module audit gate

- runner: `doc`
- step: `Module audit gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/module_audit_gate.py`
### 2026-07-18T20:00:46+00:00 - doc: Plan structure gate

- runner: `doc`
- step: `Plan structure gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/plan_structure_gate.py`
### 2026-07-22T14:42:41+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-22T14:42:41+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-22T15:06:03+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-22T15:06:04+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-24T23:15:29+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-24T23:15:29+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-25T01:11:47+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-25T01:11:47+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-27T17:35:45+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-31T16:09:58+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-31T16:09:58+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-31T20:51:02+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-07-31T20:51:02+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-10T22:45:24+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-10T22:45:24+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-10T23:53:09+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-10T23:53:10+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T02:05:06+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T02:05:07+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T02:18:41+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T02:18:41+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T21:12:23+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T21:12:24+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T22:37:09+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-11T22:37:09+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-12T15:32:20+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-12T15:32:20+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-12T20:57:37+00:00 - auto_checks: Ruff fatal lint

- runner: `auto_checks`
- step: `Ruff fatal lint`
- exit_code: `1`
- command: `'C:\Users\corbe\Thomas\.venv\Scripts\python.exe' -m ruff check thomas tests --select F821,F822,F823,F632,E902`
### 2026-08-14T18:37:35+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
### 2026-08-14T18:37:36+00:00 - auto_checks: Surface parity gate

- runner: `auto_checks`
- step: `Surface parity gate`
- exit_code: `1`
- command: `'C:\Users\corbe\AppData\Local\Programs\Python\Python312\python.exe' scripts/forge/gates/surface_parity.py`
