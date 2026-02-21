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

### 4) DepMonitor that doesn’t spam you
- Alerts include **new** high/critical since last scan (still includes the full current set).
- Stores a small **history** ring buffer (default 30) for charts/trends.

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
- `THOMAS_PROJECT_ROOT=f:\DevHub\Thomas`

## Wiring

```python
from thomas.core.dep_monitor import get_dep_monitor

def notify_fn(payload):
    # route into your notification center / SSE stream
    print(payload)

get_dep_monitor().start(notify_fn)
```

Tool registry manual registration (if needed):

```python
from thomas.tools import dep_scanner
dep_scanner.register_tools(tool_registry)
```
