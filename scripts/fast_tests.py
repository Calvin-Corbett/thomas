"""Opt-in fast test runner: a faster way to run the same tests, never a different set of tests.

    python scripts/fast_tests.py [TARGET ...] [-n N] [--serial] [--no-pyc] [--dry-run] [--ledger PATH]
    python scripts/fast_tests.py --parity --sample 30 --seed 7     # compare against a plain serial run

What it changes against ``pytest FILE FILE FILE ...`` (all measured 2026-10-03):

* many file targets become one directory argument plus an ignore hook (60 file arguments cost 52.9 s of collection,
  a directory with the hook 4.1 s); a handful of files are still passed as files because that is cheaper. A target is
  NEVER dropped: the directory form is used only when every target is a plain existing ``test_*.py`` file or a folder;
  anything else (a ``file::nodeid``, a named file that is not ``test_*.py``, a missing path) makes the whole run use
  plain pytest argument passing, and after a directory run a named file that produced no outcome fails the run;
* bytecode is cached in a folder named for this exact tree (a warm collection fell from about 60 s to about 25 s);
* pytest-xdist is used only when the test interpreter can import it, with workers capped by free RAM and CPUs;
  without it the run is serial and still gets the other two gains;
* every run appends its wall time and slowest tests to a ledger.

It is not wired into precard, commit or any gate, and a verdict never depends on it. Standard library only.
Every THOMAS_* variable is removed from the workers' environment and their state is pointed at a scratch folder.
Run it from a short checkout path. The bytecode key ignores git-ignored files and installed packages.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fast_tests_capacity as capacity  # noqa: E402
import fast_tests_plugin as plugin  # noqa: E402

ROOT = HERE.parent
DIR_THRESHOLD = 5


def cache_dir() -> Path:
    user = (
        "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
    )  # not a name another local user can pre-create
    return Path(os.environ.get("FAST_TESTS_CACHE") or Path(tempfile.gettempdir()) / f"thomas_fast_tests_{user}")


def absolute_target(item: str) -> str:
    """The target exactly as given, only anchored to the caller's folder (pytest runs from the repo root).

    A ``file::nodeid`` keeps its ``::nodeid`` suffix untouched; only the file part is made absolute.
    """
    head, sep, tail = item.partition("::")
    path = Path(head)
    return str(path if path.is_absolute() else Path.cwd() / path) + sep + tail


def directory_mode_is_safe(targets: list[str]) -> bool:
    """True only when a directory run is guaranteed to collect exactly what the file arguments would."""
    for item in targets:
        path = Path(item)
        path = path if path.is_absolute() else (Path.cwd() / path)
        if "::" in item or not path.exists():
            return False
        if path.is_file() and not (path.name.startswith("test_") and path.suffix == ".py"):
            return False
    return True


def split_targets(targets: list[str]) -> tuple[list[Path], list[Path]]:
    files, dirs = [], []
    for item in targets:
        path = Path(item)
        path = path if path.is_absolute() else (Path.cwd() / path)
        (dirs if path.is_dir() else files).append(path.resolve())
    return files, dirs


def has_xdist(python: str) -> bool:
    code = "import importlib.util as u,sys;sys.exit(0 if u.find_spec('xdist') else 1)"
    return subprocess.run([python, "-c", code], capture_output=True, check=False).returncode == 0  # noqa: S603


def build_plan(args: argparse.Namespace, *, xdist: bool, memory: tuple[int | None, int | None]) -> dict[str, Any]:
    files, dirs = split_targets(args.targets or ["tests"])
    use_dir = len(files) > args.dir_threshold and directory_mode_is_safe(args.targets or ["tests"])
    cpus = os.cpu_count() or 1
    workers, why = capacity.pick_workers(
        1 if args.serial else args.n,
        cpus=cpus,
        total=memory[0],
        available=memory[1],
        files=(len(files) + len(dirs) * 50) or None,
    )
    if not xdist and workers > 1:
        workers, why = 1, "pytest-xdist is not installed for the test interpreter: serial"
    selection = None
    if use_dir:
        base = Path(os.path.commonpath([str(p.parent) for p in files]))
        argv = [str(base)] + [str(d) for d in dirs if not d.is_relative_to(base)]
        selection = {"files": [str(p) for p in files], "dirs": [str(p) for p in dirs]}
    else:
        argv = [absolute_target(item) for item in args.targets] if args.targets else [str(p) for p in [*files, *dirs]]
    mode = "dir+ignore" if selection else "args"
    return {"argv": argv, "selection": selection, "workers": workers, "workers_why": why, "mode": mode}


def scrubbed_environment(run_dir: Path) -> dict[str, str]:
    """The parent environment without any THOMAS_* variable, and with state pointed at a scratch folder.

    Mirrors audit2/tools/scratch_env.ps1: a worker that inherited THOMAS_MEMORY_ROOT would write the owner's real
    runtime, and several xdist workers would write it at once. Home and app-data folders move too.
    """
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("THOMAS_")}
    scratch = run_dir / "state"
    for sub in ("data", "data/runtime", "memroot", "home", "home/AppData/Roaming", "home/AppData/Local"):
        (scratch / sub).mkdir(parents=True, exist_ok=True)
    home = str(scratch / "home")
    env.update(
        THOMAS_DATA_DIR=str(scratch / "data"),
        THOMAS_HOME=str(scratch / "data"),
        THOMAS_RUNTIME_DIR=str(scratch / "data" / "runtime"),
        THOMAS_MEMORY_ROOT=str(scratch / "memroot"),
        USERPROFILE=home,
        HOME=home,
        APPDATA=str(scratch / "home" / "AppData" / "Roaming"),
        LOCALAPPDATA=str(scratch / "home" / "AppData" / "Local"),
    )
    return env


def child_env(args: argparse.Namespace, plan: dict[str, Any], run_dir: Path, key: str) -> dict[str, str]:
    env = scrubbed_environment(run_dir)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(HERE), env.get("PYTHONPATH", "")) if p)
    env[plugin.RUN_DIR_ENV] = str(run_dir)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    if plan["selection"]:
        (run_dir / "select.json").write_text(json.dumps(plan["selection"]), encoding="utf-8")
        env[plugin.SELECT_ENV] = str(run_dir / "select.json")
    if not args.no_pyc:
        prefix = cache_dir() / "pyc" / key
        prefix.mkdir(parents=True, exist_ok=True)
        env[plugin.PYC_ENV] = str(prefix)
        env["PYTHONPYCACHEPREFIX"] = str(prefix)
    return env


def pytest_command(args: argparse.Namespace, plan: dict[str, Any]) -> list[str]:
    cmd = [args.python, "-m", "pytest", *plan["argv"], "-p", "fast_tests_plugin", "-p", "no:cacheprovider", "-q"]
    if plan["workers"] > 1:
        cmd += ["-n", str(plan["workers"]), "--dist", "worksteal"]
    return cmd + list(args.pytest_args)


def merge_results(run_dir: Path) -> tuple[dict[str, str], dict[str, float]]:
    outcomes: dict[str, str] = {}
    durations: dict[str, float] = {}
    for part in sorted(run_dir.glob("results-*.json")):
        data = json.loads(part.read_text(encoding="utf-8"))
        outcomes.update(data["outcomes"])
        durations.update(data["durations"])
    return outcomes, durations


def run_once(args: argparse.Namespace, plan: dict[str, Any], key: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="fast_tests_run_") as tmp:
        run_dir = Path(tmp)
        started = time.monotonic()
        done = subprocess.run(
            pytest_command(args, plan), cwd=ROOT, env=child_env(args, plan, run_dir, key), check=False
        )  # noqa: S603
        wall = time.monotonic() - started
        outcomes, durations = merge_results(run_dir)
    counts = {kind: sum(1 for v in outcomes.values() if v == kind) for kind in ("passed", "failed", "skipped")}
    lost = unrun_files(plan, outcomes, args)
    exit_code = done.returncode
    if lost and exit_code == 0:
        print(f"fast_tests: REFUSING a pass: these named files produced no test outcome: {lost}", file=sys.stderr)
        exit_code = 2
    slowest = sorted(durations.items(), key=lambda item: -item[1])[:10]
    return {
        "exit": exit_code,
        "unrun": lost,
        "wall_s": round(wall, 1),
        "outcomes": outcomes,
        "counts": counts,
        "slowest": slowest,
    }


def unrun_files(plan: dict[str, Any], outcomes: dict[str, str], args: argparse.Namespace) -> list[str]:
    """Named files of a directory run that produced no outcome at all (a narrowing option such as -k can explain it)."""
    if not plan.get("selection") or any(a in ("-k", "-m", "--deselect", "--lf", "--ff") for a in args.pytest_args):
        return []
    seen = {os.path.normcase(os.path.abspath(nodeid.split("::")[0])) for nodeid in outcomes}
    seen |= {os.path.normcase(str((ROOT / nodeid.split("::")[0]).resolve())) for nodeid in outcomes}
    return [f for f in plan["selection"]["files"] if os.path.normcase(os.path.abspath(f)) not in seen]


def append_ledger(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def sample_targets(count: int, seed: int) -> list[str]:
    names = sorted(str(p) for p in (ROOT / "tests").rglob("test_*.py"))
    return random.Random(seed).sample(names, min(count, len(names)))


def solo(args: argparse.Namespace, nodeid: str) -> str:
    plan = {"argv": [nodeid], "selection": None, "workers": 1, "mode": "args"}
    return run_once(args, plan, "solo")["outcomes"].get(nodeid, "missing")


def parity(args: argparse.Namespace, fast_plan: dict[str, Any], key: str) -> int:
    """Serial file-argument run versus the fast path, same targets. Differences are re-run alone, serially."""
    files, dirs = split_targets(args.targets)
    base_plan = {"argv": [str(p) for p in [*files, *dirs]], "selection": None, "workers": 1, "mode": "args"}
    no_pyc = argparse.Namespace(**{**vars(args), "no_pyc": True})
    reference = run_once(no_pyc, base_plan, key)
    fast = run_once(args, fast_plan, key)
    ids = set(reference["outcomes"]) | set(fast["outcomes"])
    differing = sorted(i for i in ids if reference["outcomes"].get(i, "missing") != fast["outcomes"].get(i, "missing"))
    verdicts = {
        i: {
            "serial": reference["outcomes"].get(i, "missing"),
            "fast": fast["outcomes"].get(i, "missing"),
            "solo": solo(args, i),
        }
        for i in differing[:20]
    }
    only_one_side = sorted(set(reference["outcomes"]) ^ set(fast["outcomes"]))
    real = sorted(set([i for i, v in verdicts.items() if v["solo"] != v["fast"]] + differing[20:] + only_one_side))
    report = {
        "targets": len(files) + len(dirs),
        "tests": len(ids),
        "serial_s": reference["wall_s"],
        "fast_s": fast["wall_s"],
        "mode": fast_plan["mode"],
        "workers": fast_plan["workers"],
        "differing": len(differing),
        "unexplained": len(real),
        "ids_only_in_one_run": only_one_side[:20],
        "details": verdicts,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if real else 0


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Opt-in fast test runner (see the module docstring).")
    parser.add_argument("targets", nargs="*", help="files or folders; default is the tests folder")
    parser.add_argument("-n", type=int, default=None, help="most workers to use (the machine may allow fewer)")
    parser.add_argument(
        "--serial", action="store_true", help="one process, still with the directory and bytecode gains"
    )
    parser.add_argument("--no-pyc", action="store_true", help="do not cache bytecode")
    parser.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
    parser.add_argument("--ledger", type=Path, default=None, help="ledger file (default: in the cache folder)")
    parser.add_argument(
        "--dir-threshold", type=int, default=DIR_THRESHOLD, help="file targets above this many use a directory run"
    )
    parser.add_argument("--parity", action="store_true", help="compare outcomes with a serial file-argument run")
    parser.add_argument("--sample", type=int, default=0, help="with --parity: use this many random test files")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args, extra = parser.parse_known_args(argv)
    args.pytest_args = [a for a in extra if a != "--"]
    if args.sample:
        args.targets = sample_targets(args.sample, args.seed)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    plan = build_plan(args, xdist=has_xdist(args.python), memory=capacity.memory_bytes())
    warning = capacity.short_root_warning(ROOT)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    if args.dry_run:
        print(json.dumps({**plan, "command": pytest_command(args, plan)}, indent=2))
        return 0
    key = capacity.tree_key(ROOT)
    if key is None:
        print("warning: git cannot name this tree, so bytecode is not cached (no shared key is safe)", file=sys.stderr)
        args.no_pyc = True
        key = "nocache"
    else:
        capacity.prune_prefixes(cache_dir(), key)
    if args.parity:
        return parity(args, plan, key)
    result = run_once(args, plan, key)
    row = {
        "ts": int(time.time()),
        "tree": key,
        "mode": plan["mode"],
        "workers": plan["workers"],
        "targets": len(args.targets),
        **{k: result[k] for k in ("exit", "wall_s", "counts", "slowest")},
    }
    append_ledger(args.ledger or cache_dir() / "ledger.jsonl", row)
    print(
        f"fast_tests: {plan['mode']}, {plan['workers']} worker(s) ({plan['workers_why']}), {result['wall_s']} s, {result['counts']}"
    )
    return int(result["exit"])


if __name__ == "__main__":
    raise SystemExit(main())
