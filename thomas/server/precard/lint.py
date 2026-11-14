"""``ruff check`` and ``ruff format --check`` on the changed files, counting only what the change adds.

Run on the copy with the change alone, ruff answers with everything wrong in those files, most of which
was wrong on dev this morning and is not this team's to fix. So it runs on both copies over the same
files and only the difference is reported: a rule violation the change adds, or a file the change leaves
unformatted that dev had formatted.

Line numbers are dropped from the comparison. A change that adds a line moves every finding below it, and
comparing positions would call the whole file new.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from thomas.server.proof import deadline as clock
from thomas.server.proof.environment import run_quietly, sandbox_env

RUFF_TIMEOUT_S = 300.0
_NOT_INSTALLED = "no module named ruff"
# ``path:line:col: CODE message`` -- ruff's concise output.
_FINDING = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+):\s+(?P<code>[A-Z]+\d+)\s+(?P<text>.*)$")
_WOULD_REFORMAT = "would reformat:"
_Finding = tuple[str, str, str]


@dataclass(frozen=True)
class LintResult:
    """What ruff says the change adds. ``ran`` is False when ruff could not be used at all."""

    ran: bool
    why: str
    added: tuple[str, ...]
    unformatted: tuple[str, ...]


def _python_files(work: Path, files: Sequence[str]) -> list[str]:
    return [rel for rel in dict.fromkeys(files) if rel.endswith(".py") and (Path(work) / rel).is_file()]


def _findings(output: str) -> Counter[_Finding]:
    """Every ruff finding as (file, rule, message), without its position, counted."""
    found: Counter[_Finding] = Counter()
    for raw in output.splitlines():
        match = _FINDING.match(raw.strip())
        if match:
            found[(match["path"].replace("\\", "/"), match["code"], match["text"].strip())] += 1
    return found


def _unformatted(output: str) -> set[str]:
    names = set()
    for raw in output.splitlines():
        line = raw.strip()
        if line.lower().startswith(_WOULD_REFORMAT):
            names.add(line[len(_WOULD_REFORMAT) :].strip().replace("\\", "/"))
    return names


class _Ruff:
    """Ruff, run over one set of files in one copy at a time. ``why`` is set once it could not be used."""

    def __init__(
        self,
        python: str,
        data_dir: Path,
        extra_env: Mapping[str, str] | None,
        deadline: clock.Deadline | None,
        trusted_cwd: Path | None = None,
    ) -> None:
        self.python, self.data_dir, self.extra_env, self.why = python, Path(data_dir), extra_env, ""
        self.deadline, self.trusted_cwd = deadline, trusted_cwd

    def __call__(self, work: Path, tag: str, args: Sequence[str], files: Sequence[str] = ()) -> str:
        if self.deadline is not None and self.deadline.passed:
            self.why = self.deadline.words()
            return ""
        env = sandbox_env(Path(work), self.data_dir / tag, self.extra_env)
        timeout_s = clock.cap(self.deadline, RUFF_TIMEOUT_S)
        if self.trusted_cwd is None:
            command = [self.python, "-m", "ruff", *args, "--no-cache", "--", *files]
            code, output = run_quietly(command, cwd=Path(work), env=env, timeout_s=timeout_s)
        else:
            code, output = self._isolated(Path(work), env, args, files, timeout_s)
        if _NOT_INSTALLED in output.lower():
            self.why = "ruff is not installed in the interpreter the check runs with"
        elif code < 0:  # timed out, or never started
            self.why = output.strip()[:300]
        return output

    def _isolated(
        self, work: Path, env: dict[str, str], args: Sequence[str], files: Sequence[str], timeout_s: float
    ) -> tuple[int, str]:
        """Ruff for files somebody else wrote: Python in isolated mode, started in a folder of ours, the files named by
        path. Nothing in *work* can then be imported, and no PYTHONPATH points at it."""
        env.pop("PYTHONPATH", None)
        env["PYTHONSAFEPATH"] = "1"
        root = work.resolve()
        # Every file is an absolute path whatever its name starts with, and sits after "--", so none is an option.
        command = [self.python, "-I", "-m", "ruff", *args, "--no-cache", "--", *(str(root / f) for f in files)]
        code, output = run_quietly(command, cwd=self.trusted_cwd or work, env=env, timeout_s=timeout_s)
        for spelling in {str(root), root.as_posix(), str(work), Path(work).as_posix()}:
            output = output.replace(spelling + "\\", "").replace(spelling + "/", "")
        return code, output


def ruff_findings(
    base_work: Callable[[], Path],
    change_work: Path,
    files: Sequence[str],
    *,
    python: str,
    data_dir: Path,
    extra_env: Mapping[str, str] | None = None,
    deadline: clock.Deadline | None = None,
    trusted_cwd: Path | None = None,
) -> LintResult:
    """What ``ruff check`` and ``ruff format --check`` say about *files* that they did not already say on dev."""
    on_change = _python_files(Path(change_work), files)
    if not on_change:
        return LintResult(True, "", (), ())
    ruff = _Ruff(python, data_dir, extra_env, deadline, trusted_cwd)

    def base_files() -> tuple[Path, list[str]]:
        work = base_work()
        return work, _python_files(work, on_change)

    checked = ["check", "--output-format=concise", "--force-exclude"]

    after = _findings(ruff(Path(change_work), "check-change", [*checked], on_change))
    before: Counter[_Finding] = Counter()
    if after and not ruff.why:  # nothing to excuse when the change's own copy is clean
        work, on_base = base_files()
        if on_base:
            before = _findings(ruff(work, "check-base", [*checked], on_base))
    if ruff.why:
        return LintResult(False, ruff.why, (), ())
    added = tuple(
        f"{path}: {rule} {text}"
        for (path, rule, text), count in sorted(after.items())
        if count > before[path, rule, text]
    )

    messy = _unformatted(ruff(Path(change_work), "format-change", ["format", "--check"], on_change))
    if ruff.why:
        return LintResult(False, ruff.why, added, ())
    if messy:
        work, on_base = base_files()
        if on_base:
            messy -= _unformatted(ruff(work, "format-base", ["format", "--check"], on_base))
    if ruff.why:
        return LintResult(False, ruff.why, added, ())
    return LintResult(True, "", added, tuple(sorted(messy)))


__all__ = ["RUFF_TIMEOUT_S", "LintResult", "ruff_findings"]
