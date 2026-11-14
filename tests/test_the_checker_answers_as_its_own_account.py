"""The checker runs a change's tests in its own copies and answers only for the exact job it was given.

Part 4 of docs/superpowers/specs/2026-10-12-praxis-production-line-design.md, section 8.1: before any window opens,
the check runs as an account the Build teams cannot write the answer of. These tests use their own git repo and tmp
folders, and fake the test runner: nothing here runs the real suite, the real checker account or the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage import checker_service as cs

from tests.green_support import git, make_blue
from thomas.server import proof

FAILING = "tests/test_fix_me.py::test_value"


def _commit(repo: Path, rel: str, text: str) -> tuple[str, str]:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"change {rel}")
    return git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_blue(tmp_path)


def _job(repo: Path, value: int = 2, **over: object) -> cj.Job:
    base = git(repo, "rev-parse", "HEAD")
    commit, tree = _commit(repo, "thomas/fix_me.py", f"VALUE = {value}\n")
    fields = {
        "id": "a" * 24,
        "kind": cj.CHECK,
        "base": base,
        "commit": commit,
        "tree": tree,
        "changed": ("thomas/fix_me.py",),
        "tests": (),
        "posted_at": 1.0,
    }
    fields.update(over)
    return cj.Job(**fields)  # type: ignore[arg-type]


class FakeTools(cs.Tools):
    """The runner's answers, decided by which copy a test runs in."""

    def __init__(self, *, failed: tuple[str, ...] = (), on_change: str = proof.FAILED, on_base: str = proof.PASSED,
                 ran: bool = True, boot: tuple[int, str] = (0, "")) -> None:  # fmt: skip
        self.seen: dict[str, object] = {}

        def select(work: Path, changed: list[str]) -> proof.Selection:
            self.seen["changed"] = changed
            return proof.Selection(("tests/test_fix_me.py",))

        def run_tests(work: Path, files: list[str], **kwargs: object) -> proof.ProofRun:
            self.seen["files"] = files
            self.seen["work_value"] = (work / "thomas" / "fix_me.py").read_text(encoding="utf-8")
            return proof.ProofRun(ran, "" if ran else "shard 1 of 1 was stopped", failed, 3, 1)

        def run_one(work: Path, test: str, **kwargs: object) -> str:
            return on_base if work.name == "base" else on_change

        def run(command: list[str], **kwargs: object) -> tuple[int, str]:
            self.seen["boot"] = command
            return boot

        super().__init__(select=select, run_tests=run_tests, run_one=run_one, confirm=proof.confirm, run=run)


def test_a_job_and_an_answer_are_read_back_exactly(repo: Path) -> None:
    job = _job(repo)
    assert cj.Job.parse(json.loads(json.dumps(job.to_json()))) == job
    answer = cj.Result(job.id, job.kind, job.base, job.commit, job.tree, cj.PASSED, ran=3, finished_at=2.0)
    assert cj.Result.parse(json.loads(json.dumps(answer.to_json()))) == answer
    assert answer.answers(job)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "short"},
        {"kind": "land"},
        {"base": "HEAD"},
        {"changed": ["has space.py"]},
        {"posted_at": float("nan")},
        {"extra": 1},
    ],
)
def test_anything_that_is_not_exactly_a_job_is_refused(repo: Path, change: dict[str, object]) -> None:
    data = {**_job(repo).to_json(), **change}
    with pytest.raises(ValueError):
        cj.Job.parse(data)


def test_a_file_with_a_repeated_key_or_a_link_is_not_read(tmp_path: Path) -> None:
    repeated = tmp_path / "repeated.json"
    repeated.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(ValueError):
        cj.read_json(repeated)
    assert cj.read_json(tmp_path / "absent.json") is None
    folder = tmp_path / "folder.json"
    folder.mkdir()
    with pytest.raises(ValueError):
        cj.read_json(folder)


def test_an_answer_for_another_job_does_not_answer_this_one(repo: Path) -> None:
    job = _job(repo)
    other_tree = cj.Result(job.id, job.kind, job.base, job.commit, job.base, cj.PASSED)
    other_kind = cj.Result(job.id, cj.AFTER, job.base, job.commit, job.tree, cj.PASSED)
    assert not other_tree.answers(job) and not other_kind.answers(job)


def test_a_failure_alone_with_the_change_and_not_without_it_fails_the_job(repo: Path, tmp_path: Path) -> None:
    job = _job(repo)
    tools = FakeTools(failed=(FAILING,))

    result = cs.run_job(job, repo=repo, copies=tmp_path / "copies", python="python", tools=tools)

    assert result.verdict == cj.FAILED and result.findings == (FAILING,)
    assert result.answers(job)
    assert tools.seen["work_value"] == "VALUE = 2\n", "the tests ran in a copy at the job's commit"
    assert tools.seen["changed"] == ["thomas/fix_me.py"]
    assert not (tmp_path / "copies" / job.id).exists(), "the copies are removed after the job"


def test_a_failure_dev_has_too_does_not_fail_the_job(repo: Path, tmp_path: Path) -> None:
    job = _job(repo)
    result = cs.run_job(
        job, repo=repo, copies=tmp_path / "c", python="python", tools=FakeTools(failed=(FAILING,), on_base=proof.FAILED)
    )
    assert result.verdict == cj.PASSED and result.failed == (FAILING,) and result.findings == ()


def test_noise_that_passes_alone_does_not_fail_the_job(repo: Path, tmp_path: Path) -> None:
    job = _job(repo)
    tools = FakeTools(failed=(FAILING,), on_change=proof.PASSED)
    assert cs.run_job(job, repo=repo, copies=tmp_path / "c", python="python", tools=tools).verdict == cj.PASSED


def test_a_run_that_did_not_finish_is_unavailable_never_passed(repo: Path, tmp_path: Path) -> None:
    job = _job(repo)
    result = cs.run_job(job, repo=repo, copies=tmp_path / "c", python="python", tools=FakeTools(ran=False))
    assert result.verdict == cj.UNAVAILABLE and "stopped" in result.why


def test_a_change_that_stops_thomas_starting_fails_even_with_every_test_passing(repo: Path, tmp_path: Path) -> None:
    job = _job(repo)
    tools = FakeTools(boot=(1, "Traceback ...\nImportError: cannot import name 'x'"))

    result = cs.run_job(job, repo=repo, copies=tmp_path / "c", python="python", tools=tools)

    assert result.verdict == cj.FAILED and "ImportError" in result.why and result.boot
    assert "import thomas, thomas.core.config" in " ".join(tools.seen["boot"])  # type: ignore[arg-type]


def test_a_job_whose_tree_is_not_its_commits_tree_is_unavailable(repo: Path, tmp_path: Path) -> None:
    job = _job(repo)
    wrong = cj.Job(job.id, job.kind, job.base, job.commit, git(repo, "rev-parse", f"{job.base}^{{tree}}"), job.changed)
    result = cs.run_job(wrong, repo=repo, copies=tmp_path / "c", python="python", tools=FakeTools())
    assert result.verdict == cj.UNAVAILABLE and "not the job's" in result.why


def test_the_checker_answers_the_oldest_job_once_and_passes_over_what_is_not_a_job(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "check"
    (root / cj.JOBS).mkdir(parents=True)
    old, new = _job(repo, 2, id="b" * 24, posted_at=1.0), _job(repo, 3, id="c" * 24, posted_at=2.0)
    for job in (new, old):
        cj.write_json(root / cj.JOBS / f"{job.id}.json", job.to_json())
    (root / cj.JOBS / ("d" * 24 + ".json")).write_text("{not json", encoding="utf-8")

    first = cs.serve_once(root, repo, python="python", tools=FakeTools())
    second = cs.serve_once(root, repo, python="python", tools=FakeTools())

    assert first is not None and first.job == old.id
    assert second is not None and second.job == new.id
    assert cs.serve_once(root, repo, python="python", tools=FakeTools()) is None
    written = cj.Result.parse(cj.read_json(root / cj.RESULTS / f"{old.id}.json"))
    assert written.answers(old) and written.verdict == cj.PASSED


def test_the_fence_probe_says_whether_this_account_can_reach_out() -> None:
    def refused(*_args: object, **_kwargs: object) -> object:
        raise OSError("blocked")

    class Conn:
        closed = False

        def close(self) -> None:
            Conn.closed = True

    assert cs.fence_probe(refused)["fenced"] is True
    assert cs.fence_probe(lambda *_a, **_k: Conn())["fenced"] is False and Conn.closed
