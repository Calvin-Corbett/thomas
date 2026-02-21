# Thomas Agentic Smoke Test

Single-task shortest benchmark smoke test.

## Protocol

- Run on a single local model profile.
- Keep workspace unchanged during run.

## Tasks

### 1. Artifact Probe Write (`artifact_probe_write`)
Time budget: 180 seconds
Success criteria: Writes required artifact file with exact probe line.

Prompt:

```text
Create file {{artifact_dir}}/smoke_probe.txt with this exact line:
THOMAS_SMOKE_PROBE=1
Then return one line confirming smoke_probe.txt was created.
```
