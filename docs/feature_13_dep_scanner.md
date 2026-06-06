# Feature 13 — Dependency Vulnerability Scanner (v4 "consumer-grade")

This pack keeps your original interface **exactly** (same tool names, required params, and required output keys),
but adds *meaningful* upgrades that humans actually like using.

## What consumers love here

### 1) Less noise, more signal
- Stable, sorted, de-duplicated vulnerability list.
- Optional ignore rules (by package / advisory id).
- Optional minimum severity threshold.

### 2) Actionable remediation
`deps.scan` now includes an additive `remediation` block:
- grouped per package
- best known fix version
- command to run

### 3) Faster + more reliable enrichment
- OSV cache on disk (TTL) so you don't re-fetch severities/fixes every scan.
- OSV can fill missing fix versions (best-effort).

## Config (optional)

### thomas.toml
```toml
[dep_scanner]
min_severity = "medium"           # low|medium|high|critical
ignore_packages = ["somepkg"]
ignore_cves = ["CVE-2024-12345", "GHSA-xxxx-yyyy-zzzz"]
osv_enabled = true
osv_ttl_s = 604800
```

### .thomas/dep_scanner.json
```json
{
  "min_severity": "medium",
  "ignore_packages": ["somepkg"],
  "ignore_cves": ["CVE-2024-12345"],
  "osv_enabled": true,
  "osv_ttl_s": 604800
}
```

### Env overrides
- `THOMAS_DEP_SCANNER_MIN_SEVERITY=high`
- `THOMAS_DEP_SCANNER_IGNORE_PACKAGES=pkg1,pkg2`
- `THOMAS_DEP_SCANNER_IGNORE_CVES=CVE-2024-12345,GHSA-...`
- `THOMAS_DEP_SCANNER_NO_OSV=1`
- `THOMAS_DEP_SCANNER_OSV_TTL_S=86400`
- `THOMAS_PROJECT_ROOT=<repo_root>`

## Wiring

Dependency scanning is **on-demand** via the `deps.scan` tool — call it from chat,
a route, or a scheduled job. (A background daily-watchdog wrapper, `dep_monitor.py`,
was removed 2026-06-05 as unwired scaffolding; the scan capability below is unaffected.)

Tool registry manual registration (if needed):

```python
from thomas.tools import dep_scanner
dep_scanner.register_tools(tool_registry)
```
