#!/usr/bin/env python3
"""Build a Thomas-flavored Ollama model from every installed local base model.

A "Thomas version" is the base model with the canonical Thomas system prompt
(ollama/thomas.system.txt) and a couple of safe sampling defaults layered on
top via a Modelfile. The base weights are shared on disk (Ollama dedupes the
FROM blob), so each Thomas model costs ~nothing extra.

The base model's own chat template and stop tokens are inherited through FROM,
so this stays family-agnostic (works for llama, qwen, mistral, gemma, phi, ...).

Note on scope: inside the Thomas app the baked system prompt is overridden by
the app's own prompt (Ollama replaces, not merges, when the request carries a
system message). These models matter for `ollama run` / standalone use and as
a defense floor for any caller that does NOT send its own system prompt. The
in-app security floor lives in thomas/agent/prompt_templates.py.

Usage:
    python scripts/build_thomas_models.py            # build all missing
    python scripts/build_thomas_models.py --force    # rebuild even if present
    python scripts/build_thomas_models.py --dry-run  # show what would happen
    python scripts/build_thomas_models.py --model mistral:7b   # just one base
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_TEXT_PATH = REPO_ROOT / "ollama" / "thomas.system.txt"
THOMAS_PREFIX = "thomas-"
PARAMS = {"temperature": "0.2", "num_ctx": "8192"}


def _find_ollama() -> str:
    found = shutil.which("ollama") or shutil.which("ollama.exe")
    if found:
        return found
    if os.name == "nt":
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("ollama binary not found on PATH. Install Ollama or start it first.")


def _run(ollama: str, args: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run([ollama, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _installed_models(ollama: str) -> list[str]:
    proc = _run(ollama, ["list"])
    if proc.returncode != 0:
        raise SystemExit(f"`ollama list` failed: {proc.stderr.strip() or proc.returncode}")
    models: list[str] = []
    for line in proc.stdout.splitlines()[1:]:  # skip header
        name = line.split()[0] if line.split() else ""
        if name:
            models.append(name)
    return models


def _thomas_name(base: str) -> str:
    """thomas-<base> with tag/namespace separators flattened to dashes."""
    return THOMAS_PREFIX + base.replace(":", "-").replace("/", "-")


def _is_buildable_base(name: str) -> bool:
    if name.startswith(THOMAS_PREFIX):
        return False  # already a Thomas model
    if name.endswith("-cloud") or ":cloud" in name:
        return False  # cloud-hosted, can't bake a local Modelfile
    return True


def _write_modelfile(base: str, system_text: str) -> str:
    lines = [f"FROM {base}", f'SYSTEM """{system_text.strip()}"""']
    lines += [f"PARAMETER {k} {v}" for k, v in PARAMS.items()]
    fd, path = tempfile.mkstemp(prefix="thomas_modelfile_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Thomas-flavored Ollama models.")
    parser.add_argument("--force", action="store_true", help="Rebuild even if the Thomas model exists.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without creating models.")
    parser.add_argument("--model", default="", help="Only Thomas-ify this one base model.")
    args = parser.parse_args(argv)

    if not SYSTEM_TEXT_PATH.is_file():
        raise SystemExit(f"Canonical system text missing: {SYSTEM_TEXT_PATH}")
    system_text = SYSTEM_TEXT_PATH.read_text(encoding="utf-8")
    if '"""' in system_text:
        raise SystemExit("System text contains a triple-quote, which breaks the Modelfile.")

    ollama = _find_ollama()
    installed = _installed_models(ollama)
    existing = set(installed)

    targets = [args.model] if args.model else [m for m in installed if _is_buildable_base(m)]
    if args.model and not _is_buildable_base(args.model):
        raise SystemExit(f"{args.model} is not a buildable base (thomas-* or cloud).")

    built, skipped, failed = [], [], []
    for base in targets:
        thomas = _thomas_name(base)
        if thomas in existing and not args.force:
            skipped.append(f"{thomas} (exists)")
            continue
        if args.dry_run:
            built.append(f"{thomas}  <-  {base}  (dry-run)")
            continue
        modelfile = _write_modelfile(base, system_text)
        try:
            proc = _run(ollama, ["create", thomas, "-f", modelfile])
        finally:
            with contextlib.suppress(OSError):
                os.unlink(modelfile)
        if proc.returncode == 0:
            built.append(f"{thomas}  <-  {base}")
        else:
            failed.append(f"{thomas}: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'failed'}")

    print(f"\nThomas models — built {len(built)}, skipped {len(skipped)}, failed {len(failed)}")
    for row in built:
        print(f"  OK    {row}")
    for row in skipped:
        print(f"  skip  {row}")
    for row in failed:
        print(f"  FAIL  {row}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
