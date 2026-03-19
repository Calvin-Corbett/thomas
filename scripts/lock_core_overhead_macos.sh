#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST_PATH="${1:-$REPO_ROOT/docs/core_overhead_manifest.json}"

if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "Manifest not found: $MANIFEST_PATH" >&2
  exit 1
fi

mapfile -t FILES < <(
  python3 - "$MANIFEST_PATH" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8-sig") as f:
    data = json.load(f)
for rel in data.get("protected_files", []):
    rel = str(rel or "").strip()
    if rel:
        print(rel)
PY
)

if [[ "${#FILES[@]}" -eq 0 ]]; then
  echo "Manifest has no protected_files." >&2
  exit 1
fi

for rel in "${FILES[@]}"; do
  full="$REPO_ROOT/$rel"
  if [[ ! -f "$full" ]]; then
    echo "Skip missing file: $rel" >&2
    continue
  fi
  sudo chown root:wheel "$full"
  sudo chmod 644 "$full"
done

echo "Core overhead locked (root-owned, read-only for non-root writes)."
