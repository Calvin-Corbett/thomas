"""Release-level token-efficiency engineering (CAP-095).

Where :mod:`thomas.core.usage_telemetry` (CAP-014) breaks a *single turn's*
token usage into categories, this module rolls efficiency up to the level of a
**release** -- a version string or tag -- so the team can answer the questions a
token budget actually cares about:

* **Retry rate** -- what fraction of runs needed at least one retry?
* **First-pass success** -- what fraction of runs succeeded on the very first
  attempt (no retries)?
* **Cost per outcome** -- how many tokens did the release spend, and how many
  tokens did it burn per successful run (``tokens_per_success``)?

Every run is recorded against the shared **token ledger** so efficiency is
expressed as *success per token*, not just as a raw pass/fail count. Comparing
two releases then shows the trend that matters: did first-pass success rise
while tokens-per-success fell?

Design notes
------------
* Stdlib only. This module sits at the bottom of the dependency tree
  (``thomas/core``) and must not import from ``agent``/``server``/``tools``.
* Deterministic: aggregates carry no timestamps or ordering-dependent state, so
  the same sequence of ``record_run`` calls always yields the same report and
  the same on-disk JSON.
* Durable: state persists to a JSON file after every mutation. The path is
  overridable via the ``THOMAS_TOKEN_EFFICIENCY_PATH`` environment variable or
  an explicit constructor argument; both make the ledger fully hermetic for
  tests.
* Thread-safe: a single lock guards every read/write so concurrent run
  recordings cannot corrupt the aggregates.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "EfficiencyReport",
    "ReleaseComparison",
    "TokenEfficiencyLedger",
]

# Environment variable that overrides the default persistence path.
ENV_PATH = "THOMAS_TOKEN_EFFICIENCY_PATH"


def _coerce_int(value: Any, *, minimum: int = 0) -> int:
    """Coerce ``value`` to an int no smaller than ``minimum``."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return minimum
    return result if result >= minimum else minimum


@dataclass(frozen=True)
class EfficiencyReport:
    """Immutable efficiency snapshot for one release.

    Attributes
    ----------
    release:
        The version/tag this report describes.
    runs:
        Total number of runs recorded for the release.
    retry_rate:
        Fraction of runs (``0.0``-``1.0``) that needed at least one retry
        (i.e. ran more than one attempt).
    first_pass_rate:
        Fraction of runs that succeeded on the first attempt with no retries.
    total_tokens:
        Total tokens spent across every run in the release (the token ledger).
    successes:
        Number of runs that ultimately succeeded (on any attempt).
    tokens_per_success:
        ``total_tokens / successes`` -- the token cost of one successful
        outcome. ``None`` when the release has no successful runs, because the
        ratio is undefined rather than zero.
    """

    release: str
    runs: int
    retry_rate: float
    first_pass_rate: float
    total_tokens: int
    successes: int
    tokens_per_success: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "release": self.release,
            "runs": self.runs,
            "retry_rate": self.retry_rate,
            "first_pass_rate": self.first_pass_rate,
            "total_tokens": self.total_tokens,
            "successes": self.successes,
            "tokens_per_success": self.tokens_per_success,
        }


@dataclass(frozen=True)
class ReleaseComparison:
    """Trend between two releases: ``baseline`` -> ``candidate``.

    ``improved`` is ``True`` only when the candidate release both raised
    first-pass success *and* lowered tokens-per-success relative to the
    baseline -- the definition of a token-efficiency win.
    """

    baseline: EfficiencyReport
    candidate: EfficiencyReport
    first_pass_delta: float
    tokens_per_success_delta: float | None
    first_pass_improved: bool
    tokens_per_success_improved: bool
    improved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "first_pass_delta": self.first_pass_delta,
            "tokens_per_success_delta": self.tokens_per_success_delta,
            "first_pass_improved": self.first_pass_improved,
            "tokens_per_success_improved": self.tokens_per_success_improved,
            "improved": self.improved,
        }


class TokenEfficiencyLedger:
    """Durable, per-release retry-rate / first-pass / token-cost accumulator.

    Example
    -------
    >>> ledger = TokenEfficiencyLedger(path=":memory-example:")  # doctest: +SKIP
    >>> ledger.record_run("v1", attempts=1, succeeded=True, tokens=500)
    >>> ledger.record_run("v1", attempts=3, succeeded=True, tokens=1500)
    >>> report = ledger.release_report("v1")
    >>> report.retry_rate
    0.5
    >>> report.first_pass_rate
    0.5
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._lock = threading.Lock()
        self._path = self._resolve_path(path)
        # release -> aggregate counters. Aggregates (not per-run rows) keep the
        # state deterministic and compact while remaining exactly sufficient to
        # compute every reported metric.
        self._releases: dict[str, dict[str, int]] = {}
        self._load()

    # -- path / persistence --------------------------------------------------

    @staticmethod
    def _resolve_path(path: str | os.PathLike[str] | None) -> Path:
        if path is not None:
            return Path(path)
        env = os.environ.get(ENV_PATH)
        if env:
            return Path(env)
        repo_root = Path(__file__).resolve().parents[2]
        return repo_root / "thomas_token_efficiency.json"

    @staticmethod
    def _blank_aggregate() -> dict[str, int]:
        return {
            "runs": 0,
            "retried_runs": 0,
            "first_pass_runs": 0,
            "successes": 0,
            "total_tokens": 0,
        }

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        releases = data.get("releases") if isinstance(data, dict) else None
        if not isinstance(releases, dict):
            return
        loaded: dict[str, dict[str, int]] = {}
        for name, agg in releases.items():
            if not isinstance(agg, dict):
                continue
            blank = self._blank_aggregate()
            for key in blank:
                blank[key] = _coerce_int(agg.get(key))
            loaded[str(name)] = blank
        self._releases = loaded

    def _save(self) -> None:
        payload = {
            "version": 1,
            "releases": {name: dict(agg) for name, agg in sorted(self._releases.items())},
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self._path)

    # -- recording -----------------------------------------------------------

    def record_run(
        self,
        release: str,
        *,
        attempts: int,
        succeeded: bool,
        tokens: int,
    ) -> None:
        """Record one run against ``release`` and persist.

        Parameters
        ----------
        release:
            Version string / tag the run belongs to.
        attempts:
            Total attempts the run took. ``1`` means it needed no retry;
            ``>= 2`` means at least one retry. Coerced to a minimum of ``1``.
        succeeded:
            Whether the run ultimately succeeded (on any attempt).
        tokens:
            Tokens the run spent, added to the release's token ledger.
        """
        release_key = str(release)
        attempt_count = _coerce_int(attempts, minimum=1)
        token_count = _coerce_int(tokens)
        won = bool(succeeded)
        retried = attempt_count >= 2
        first_pass = won and not retried

        with self._lock:
            agg = self._releases.get(release_key)
            if agg is None:
                agg = self._blank_aggregate()
                self._releases[release_key] = agg
            agg["runs"] += 1
            agg["total_tokens"] += token_count
            if retried:
                agg["retried_runs"] += 1
            if won:
                agg["successes"] += 1
            if first_pass:
                agg["first_pass_runs"] += 1
            self._save()

    # -- reporting -----------------------------------------------------------

    def releases(self) -> list[str]:
        """Return the recorded release names in sorted order."""
        with self._lock:
            return sorted(self._releases)

    def release_report(self, release: str) -> EfficiencyReport:
        """Return the :class:`EfficiencyReport` for ``release``.

        A release with no recorded runs yields an all-zero report with a
        ``None`` ``tokens_per_success`` (the metric is undefined, not zero).
        """
        release_key = str(release)
        with self._lock:
            agg = self._releases.get(release_key)
            snapshot = dict(agg) if agg is not None else self._blank_aggregate()

        runs = snapshot["runs"]
        successes = snapshot["successes"]
        total_tokens = snapshot["total_tokens"]
        if runs <= 0:
            return EfficiencyReport(
                release=release_key,
                runs=0,
                retry_rate=0.0,
                first_pass_rate=0.0,
                total_tokens=total_tokens,
                successes=successes,
                tokens_per_success=None,
            )

        retry_rate = snapshot["retried_runs"] / runs
        first_pass_rate = snapshot["first_pass_runs"] / runs
        tokens_per_success = total_tokens / successes if successes > 0 else None
        return EfficiencyReport(
            release=release_key,
            runs=runs,
            retry_rate=retry_rate,
            first_pass_rate=first_pass_rate,
            total_tokens=total_tokens,
            successes=successes,
            tokens_per_success=tokens_per_success,
        )

    def compare_releases(self, baseline: str, candidate: str) -> ReleaseComparison:
        """Compare two releases and describe the efficiency trend.

        The comparison is directional: ``baseline`` is the earlier release,
        ``candidate`` the newer one. ``improved`` is ``True`` only when the
        candidate raised first-pass success and lowered tokens-per-success.

        When either release lacks a defined ``tokens_per_success`` (no
        successful runs), the token-cost delta is ``None`` and
        ``tokens_per_success_improved`` is ``False`` -- an undefined cost cannot
        be shown to have fallen.
        """
        base = self.release_report(baseline)
        cand = self.release_report(candidate)

        first_pass_delta = cand.first_pass_rate - base.first_pass_rate
        first_pass_improved = first_pass_delta > 0.0

        if base.tokens_per_success is None or cand.tokens_per_success is None:
            tps_delta: float | None = None
            tps_improved = False
        else:
            tps_delta = cand.tokens_per_success - base.tokens_per_success
            tps_improved = tps_delta < 0.0

        return ReleaseComparison(
            baseline=base,
            candidate=cand,
            first_pass_delta=first_pass_delta,
            tokens_per_success_delta=tps_delta,
            first_pass_improved=first_pass_improved,
            tokens_per_success_improved=tps_improved,
            improved=first_pass_improved and tps_improved,
        )
